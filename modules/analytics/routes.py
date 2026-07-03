"""Analitika — boshliq uchun strategik ko'rinish.

• Bandlik heatmap: hafta kuni × soat — qaysi vaqtlar to'la/bo'sh
  (off-peak chegirma kiritish uchun asos).
• Churn radar: 30+ kun yozilmagan ustozlar — qayta faollashtirish ro'yxati.
• Top ustozlar: oxirgi 90 kunda eng ko'p soat yozganlar.
"""
from datetime import datetime, timedelta

from flask import Blueprint, render_template

from core.auth import login_required
from core.timeutils import now_tashkent, today_iso
from models.studio import Booking, Studio
from models.billing import Teacher

bp = Blueprint("analytics", __name__)

CHURN_DAYS = 30


@bp.route("/analytics")
@login_required
def index():
    today = today_iso()
    d30 = (now_tashkent().date() - timedelta(days=29)).strftime("%Y-%m-%d")
    d90 = (now_tashkent().date() - timedelta(days=89)).strftime("%Y-%m-%d")

    rows = Booking.query.filter(
        Booking.date >= d90, Booking.date <= today,
        Booking.status.in_(("active", "done"))).all()

    # ── Heatmap (oxirgi 30 kun): hafta kuni × soat → band soatlar soni ──
    heat = [[0] * 13 for _ in range(7)]   # 7 kun × soat 9..21
    max_heat = 0
    for b in rows:
        if b.date < d30:
            continue
        try:
            wd = datetime.strptime(b.date, "%Y-%m-%d").weekday()
            h0 = int(b.start[:2])
            h1 = max(h0 + 1, int(b.end[:2]) + (1 if b.end[3:] > "00" else 0))
        except (ValueError, IndexError):
            continue
        for h in range(max(9, h0), min(22, h1)):
            heat[wd][h - 9] += 1
            max_heat = max(max_heat, heat[wd][h - 9])

    # ── Churn radar: 30+ kun yozilmaganlar ──
    last_by_teacher = {}
    for b in Booking.query.filter(
            Booking.status.in_(("active", "done"))).all():
        cur = last_by_teacher.get(b.teacher_id, "")
        if b.date > cur:
            last_by_teacher[b.teacher_id] = b.date
    threshold = (now_tashkent().date() - timedelta(days=CHURN_DAYS)).strftime("%Y-%m-%d")
    churn = []
    for t in Teacher.query.filter_by(is_active=True).all():
        last = last_by_teacher.get(t.id, "")
        # kelgusi bron bo'lsa churn emas
        if last >= today:
            continue
        if not last or last < threshold:
            days = "hech" if not last else (
                now_tashkent().date() - datetime.strptime(last, "%Y-%m-%d").date()).days
            churn.append({"t": t.to_dict(), "last": last or "—", "days": days})
    churn.sort(key=lambda x: str(x["last"]))

    # ── Top ustozlar (90 kun, soat bo'yicha) ──
    hours_by = {}
    for b in rows:
        hours_by[b.teacher_id] = hours_by.get(b.teacher_id, 0) + b.hours
    tmap = {t.id: t.name for t in Teacher.query.all()}
    top = sorted(({"name": tmap.get(k, "?"), "hours": round(v, 1)}
                  for k, v in hours_by.items()),
                 key=lambda x: -x["hours"])[:10]

    days_uz = ["Dush", "Sesh", "Chor", "Pay", "Jum", "Shan", "Yak"]
    return render_template(
        "analytics.html", heat=heat, max_heat=max_heat, days=days_uz,
        hours=list(range(9, 22)), churn=churn, churn_days=CHURN_DAYS, top=top)
