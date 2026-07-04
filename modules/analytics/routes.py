"""Analitika — boshqaruv qarorlari uchun strategik ko'rinish.

Falsafa (katta kompaniya analitikasi maktabi): raqam emas — QAROR muhim.
Har bo'lim bitta savolga javob beradi:
  • KPI + delta        — «o'tgan oyga nisbatan qayoqqa ketyapmiz?»
  • 6 oylik trend      — «o'sish barqarormi?» (soat + tushum + bandlik %)
  • Bandlik xaritasi   — «qaysi vaqtlar pul, qaysilari bo'sh turadi?»
  • Kelgusi 7 kun      — «oldinda nima kutilyapti?» (forward pipeline)
  • Segmentlar/Churn   — «kimni yo'qotayapmiz, kimga sotamiz?»
  • Top mijozlar       — «kimga bog'liqmiz?» (kontsentratsiya xavfi)
  • Montaj SLA         — «va'dani bajaryapmizmi?»
  • Aqlli xulosalar    — hammasidan avtomatik tavsiya chiqaradi.

Pul ko'rsatkichlari faqat rahbarга (operator soat/bandlikni ko'radi).
"""
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, render_template

from core.auth import login_required, current_user
from core.timeutils import now_tashkent, today_iso
from models.billing import Teacher, Payment
from models.montaj import EditJob
from models.studio import Booking, Studio

bp = Blueprint("analytics", __name__)

CHURN_DAYS = 30
MONTH_UZ = ["", "Yan", "Fev", "Mar", "Apr", "May", "Iyn",
            "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]


def _month_bounds(d):
    """(YYYY-MM-01, keyingi oy 01) — sana satrlari uchun."""
    first = d.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")


def _delta(cur, prev):
    """O'zgarish % (prev=0 bo'lsa None — «yangi» deb ko'rsatiladi)."""
    if not prev:
        return None
    return round((cur - prev) / prev * 100, 1)


def _capacity_hours(year, month, active_studios):
    """Oylik sig'im: studiyalar × ish soati (12h) × oy kunlari."""
    from calendar import monthrange
    days = monthrange(year, month)[1]
    return active_studios * 12 * days


@bp.route("/analytics")
@login_required
def index():
    is_admin = bool(current_user() and current_user().is_admin)
    today = today_iso()
    t0 = now_tashkent().date()

    # ── Davrlar ──────────────────────────────────────────────────────────
    # MUHIM (halol taqqoslash): joriy oy hali tugamagan, shuning uchun delta
    # to'liq o'tgan oyga emas — o'tgan oyning XUDDI SHU KUNIGACHA bo'lgan
    # davriga (MTD vs prior-MTD) solishtiriladi. Aks holda oy boshida har
    # doim «-70%» ko'rinadi va panel ishonchni yo'qotadi.
    from calendar import monthrange
    cur_start, cur_end = _month_bounds(t0)
    prev_last = t0.replace(day=1) - timedelta(days=1)     # o'tgan oy oxiri
    prev_start = prev_last.replace(day=1).strftime("%Y-%m-%d")
    prev_end = _month_bounds(prev_last)[1]                # to'liq oy (trend uchun)
    _pdays = monthrange(prev_last.year, prev_last.month)[1]
    prev_mtd_end = (prev_last.replace(day=min(t0.day, _pdays))
                    + timedelta(days=1)).strftime("%Y-%m-%d")
    d30 = (t0 - timedelta(days=29)).strftime("%Y-%m-%d")
    d90 = (t0 - timedelta(days=89)).strftime("%Y-%m-%d")

    all_bookings = Booking.query.filter(Booking.date >= prev_start).all()
    done_like = ("active", "done")

    def _stats(lo, hi):
        """Bitta oy statistikasi: soat, mijozlar, bekor %, bronlar."""
        hours = total = bad = 0
        cset = set()
        for b in all_bookings:
            if not (lo <= b.date < hi):
                continue
            total += 1
            if b.status in done_like:
                hours += b.hours
                cset.add(b.teacher_id)
            elif b.status in ("cancelled", "noshow"):
                bad += 1
        return {"hours": round(hours, 1), "clients": len(cset),
                "total": total, "bad": bad,
                "bad_pct": round(bad / total * 100, 1) if total else 0.0}

    cur = _stats(cur_start, cur_end)
    prev = _stats(prev_start, prev_mtd_end)   # prior-MTD — halol delta

    # Yangi mijozlar (ro'yxatga olingan sana bo'yicha)
    def _new_teachers(lo, hi):
        n = 0
        for t in Teacher.query.all():
            c = t.created_at.strftime("%Y-%m-%d") if t.created_at else ""
            if lo <= c < hi:
                n += 1
        return n
    cur_new = _new_teachers(cur_start, cur_end)
    prev_new = _new_teachers(prev_start, prev_mtd_end)

    # Tushum (faqat rahbar): tasdiqlangan studiya to'lovlari
    revenue = {"cur": 0.0, "prev": 0.0, "cur_n": 0}
    if is_admin:
        for p in Payment.query.filter(Payment.is_paid.is_(True),
                                      Payment.date >= prev_start).all():
            if cur_start <= p.date < cur_end:
                revenue["cur"] += p.amount or 0
                revenue["cur_n"] += 1
            elif prev_start <= p.date < prev_mtd_end:   # prior-MTD
                revenue["prev"] += p.amount or 0
    avg_check = (revenue["cur"] / revenue["cur_n"]) if revenue["cur_n"] else 0

    kpi = {
        "hours": cur["hours"], "hours_d": _delta(cur["hours"], prev["hours"]),
        "clients": cur["clients"],
        "clients_d": _delta(cur["clients"], prev["clients"]),
        "new": cur_new, "new_d": _delta(cur_new, prev_new),
        "bad_pct": cur["bad_pct"], "bad_pct_prev": prev["bad_pct"],
        "revenue": revenue["cur"],
        "revenue_d": _delta(revenue["cur"], revenue["prev"]),
        "avg_check": avg_check,
    }

    # ── 6 oylik trend: soat + tushum + bandlik % ─────────────────────────
    n_studios = Studio.query.filter_by(is_active=True).count() or 1
    months = []
    m = t0.replace(day=1)
    for _ in range(6):
        months.append(m)
        m = (m - timedelta(days=1)).replace(day=1)
    months.reverse()
    b6 = Booking.query.filter(
        Booking.date >= months[0].strftime("%Y-%m-%d"),
        Booking.status.in_(done_like)).all()
    p6 = (Payment.query.filter(Payment.is_paid.is_(True),
                               Payment.date >= months[0].strftime("%Y-%m-%d"))
          .all()) if is_admin else []
    trend = []
    for m in months:
        lo, hi = _month_bounds(m)
        h = sum(b.hours for b in b6 if lo <= b.date < hi)
        rev = sum(p.amount or 0 for p in p6 if lo <= p.date < hi)
        cap = _capacity_hours(m.year, m.month, n_studios)
        trend.append({
            "label": MONTH_UZ[m.month], "hours": round(h, 1),
            "revenue": round(rev),
            "util": round(h / cap * 100, 1) if cap else 0})

    # ── Bandlik xaritasi (30 kun): hafta kuni × soat ─────────────────────
    heat = [[0] * 12 for _ in range(7)]
    max_heat = 0
    for b in all_bookings:
        if b.date < d30 or b.date > today or b.status not in done_like:
            continue
        try:
            wd = datetime.strptime(b.date, "%Y-%m-%d").weekday()
            h0 = int(b.start[:2])
            h1 = max(h0 + 1, int(b.end[:2]) + (1 if b.end[3:] > "00" else 0))
        except (ValueError, IndexError):
            continue
        for h in range(max(9, h0), min(21, h1)):
            heat[wd][h - 9] += 1
            max_heat = max(max_heat, heat[wd][h - 9])

    # ── Kelgusi 7 kun pipeline ───────────────────────────────────────────
    days_uz_full = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba",
                    "Juma", "Shanba", "Yakshanba"]
    week_ahead = []
    for i in range(7):
        d = t0 + timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        h = sum(b.hours for b in Booking.query.filter_by(
            date=ds, status="active").all())
        week_ahead.append({
            "date": ds,
            "label": ("Bugun" if i == 0 else
                      "Ertaga" if i == 1 else days_uz_full[d.weekday()][:4]),
            "hours": round(h, 1),
            "pct": min(round(h / (n_studios * 12) * 100), 100)})

    # ── Mijoz segmentlari (recency bo'yicha RFM-lite) + churn ────────────
    last_by = {}
    future_by = set()
    for b in Booking.query.filter(Booking.status.in_(done_like)).all():
        if b.date > today:
            future_by.add(b.teacher_id)
        elif b.date > last_by.get(b.teacher_id, ""):
            last_by[b.teacher_id] = b.date
    seg = {"active": 0, "cooling": 0, "sleeping": 0, "lost": 0}
    churn = []
    threshold = (t0 - timedelta(days=CHURN_DAYS)).strftime("%Y-%m-%d")
    for t in Teacher.query.filter_by(is_active=True).all():
        last = last_by.get(t.id, "")
        days = ((t0 - datetime.strptime(last, "%Y-%m-%d").date()).days
                if last else None)
        if t.id in future_by or (days is not None and days <= 14):
            seg["active"] += 1
        elif days is not None and days <= 30:
            seg["cooling"] += 1
        elif days is not None and days <= 60:
            seg["sleeping"] += 1
        else:
            seg["lost"] += 1
        # Churn radar: kelgusi broni bo'lsa xavf emas
        if t.id in future_by:
            continue
        if not last or last < threshold:
            churn.append({"t": t.to_dict(), "last": last or "—",
                          "days": "hech" if days is None else days})
    churn.sort(key=lambda x: str(x["last"]))

    # ── Top mijozlar (90 kun) + kontsentratsiya ──────────────────────────
    hours_by = defaultdict(float)
    rev_by = defaultdict(float)
    for b in Booking.query.filter(Booking.date >= d90,
                                  Booking.date <= today,
                                  Booking.status.in_(done_like)).all():
        hours_by[b.teacher_id] += b.hours
    if is_admin:
        for p in Payment.query.filter(Payment.is_paid.is_(True),
                                      Payment.date >= d90).all():
            rev_by[p.teacher_id] += p.amount or 0
    tmap = {t.id: t.name for t in Teacher.query.all()}
    total_h90 = sum(hours_by.values())
    top = sorted(({"id": k, "name": tmap.get(k, "?"),
                   "hours": round(v, 1),
                   "revenue": round(rev_by.get(k, 0)),
                   "share": round(v / total_h90 * 100, 1) if total_h90 else 0}
                  for k, v in hours_by.items()),
                 key=lambda x: -x["hours"])[:10]
    top3_share = round(sum(x["share"] for x in top[:3]), 1)

    # ── Montaj SLA ───────────────────────────────────────────────────────
    jobs = EditJob.query.all()
    open_jobs = [j for j in jobs if j.status != "delivered"]
    overdue = [j for j in open_jobs if j.is_overdue()]
    dl_days = [(j.delivered_at - j.created_at).total_seconds() / 86400
               for j in jobs
               if j.delivered_at and j.created_at
               and j.delivered_at.strftime("%Y-%m-%d") >= d90]
    sla = {"open": len(open_jobs), "overdue": len(overdue),
           "avg_days": round(sum(dl_days) / len(dl_days), 1) if dl_days else None,
           "delivered_90": len(dl_days)}

    # ── Lead-time: bron necha kun oldindan qilinadi (90 kun) ────────────
    leads = []
    for b in Booking.query.filter(Booking.date >= d90).all():
        if b.created_at:
            try:
                lead = (datetime.strptime(b.date, "%Y-%m-%d").date()
                        - b.created_at.date()).days
                if 0 <= lead <= 60:
                    leads.append(lead)
            except ValueError:
                continue
    lead_avg = round(sum(leads) / len(leads), 1) if leads else None

    # ── Aqlli xulosalar (auto-insights) ──────────────────────────────────
    insights = []

    def add(icon, level, text, link=None):
        insights.append({"icon": icon, "level": level, "text": text,
                         "link": link})

    if max_heat:
        best = max(((wd, h) for wd in range(7) for h in range(12)),
                   key=lambda x: heat[x[0]][x[1]])
        add("flame", "ok",
            f"Eng band vaqt: {days_uz_full[best[0]]} {best[1] + 9}:00 — bu "
            f"oynani premium narxlash mumkin.")
        empty = min(((wd, h) for wd in range(5) for h in range(1, 9)),
                    key=lambda x: heat[x[0]][x[1]])
        if heat[empty[0]][empty[1]] == 0:
            add("moon", "info",
                f"{days_uz_full[empty[0]]} {empty[1] + 9}:00 deyarli bo'sh — "
                f"off-peak chegirma bilan to'ldirsa bo'ladi.")
    if kpi["hours_d"] is not None:
        if kpi["hours_d"] >= 10:
            add("trending-up", "ok",
                f"Yozuv soatlari o'tgan oyga nisbatan +{kpi['hours_d']}% — "
                f"o'sish barqaror.")
        elif kpi["hours_d"] <= -10:
            add("trending-down", "warn",
                f"Yozuv soatlari {kpi['hours_d']}% ga tushdi — sabab "
                f"tekshirilsin (mavsum? marketing?).")
    if cur["bad_pct"] > 10:
        add("alert-triangle", "warn",
            f"Bekor/kelmadi darajasi {cur['bad_pct']}% — 10% dan yuqori. "
            f"Eslatma va oldindan to'lovni kuchaytiring.")
    if churn:
        add("radar", "warn",
            f"{len(churn)} mijoz {CHURN_DAYS}+ kun yozilmagan — qayta "
            f"faollashtirish ro'yxati quyida.", "#churn")
    low_balance = [t for t in Teacher.query.filter_by(is_active=True).all()
                   if 0 < t.balance_hours() <= 2]
    if low_balance:
        add("package", "info",
            f"{len(low_balance)} mijozning paketi tugayapti (≤2 soat) — "
            f"qayta sotish uchun eng qulay payt.")
    if top3_share >= 40 and len(top) >= 3:
        add("pie-chart", "warn",
            f"Top-3 mijoz jami soatning {top3_share}% ini beradi — "
            f"kontsentratsiya xavfi: yangi mijozlar oqimini kengaytiring.")
    if sla["overdue"]:
        add("timer-off", "warn",
            f"Montajda {sla['overdue']} ta karta muddati o'tgan — SLA "
            f"buzilmoqda.", "/montaj")
    elif sla["avg_days"] is not None and sla["avg_days"] <= 3:
        add("check-circle", "ok",
            f"Montaj o'rtacha {sla['avg_days']} kunda topshirilyapti — "
            f"SLA (3 kun) ichida.")
    if is_admin and kpi["revenue_d"] is not None:
        if kpi["revenue_d"] >= 10:
            add("banknote", "ok",
                f"Tushum o'tgan oyga nisbatan +{kpi['revenue_d']}%.")
        elif kpi["revenue_d"] <= -10:
            add("banknote", "warn",
                f"Tushum {kpi['revenue_d']}% ga kamaydi — moliya panelida "
                f"tafsilot.", "/finance")
    if lead_avg is not None and lead_avg < 1.5:
        add("clock", "info",
            f"Bronlar o'rtacha {lead_avg} kun oldin qilinadi — jadval "
            f"«bugunga» bog'liq. Oldindan bron aksiyasini o'ylang.")
    if not insights:
        add("sparkles", "ok", "Hammasi me'yorida — kritik signal yo'q.")

    return render_template(
        "analytics.html",
        is_admin=is_admin, kpi=kpi, trend=trend,
        heat=heat, max_heat=max_heat,
        days=["Dush", "Sesh", "Chor", "Pay", "Jum", "Shan", "Yak"],
        hours=list(range(9, 21)),
        week_ahead=week_ahead, seg=seg,
        churn=churn, churn_days=CHURN_DAYS,
        top=top, top3_share=top3_share,
        sla=sla, lead_avg=lead_avg, insights=insights,
        month_label=f"{MONTH_UZ[t0.month]} {t0.year}")
