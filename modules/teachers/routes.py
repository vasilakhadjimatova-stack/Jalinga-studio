"""Mijozlar CRM: profil, LTV, segment, tashriflar, o'zaro aloqa tarixi."""
from collections import defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash

from core.auth import login_required, current_user
from core.timeutils import today_iso, now_tashkent
from database import db
from models.billing import (Teacher, Payment, ClientNote, PAY_METHODS,
                            CRM_SEGMENTS, NOTE_KINDS)
from models.studio import Booking, Studio

bp = Blueprint("teachers", __name__)


def _segment_of(last, nxt, created, today):
    """RFM-lite segment: recency (oxirgi tashrif) bo'yicha."""
    if nxt:                       # kelgusi broni bor → faol
        return "active"
    if not last:                  # hech tashrif yo'q
        if created and (today - created).days <= 30:
            return "new"
        return "lost"
    days = (today - last).days
    if days <= 14:
        return "active"
    if days <= 30:
        return "cooling"
    if days <= 60:
        return "sleeping"
    return "lost"


def _crm_metrics():
    """Barcha mijozlar uchun batch metrika (N+1 yo'q): LTV, tashriflar,
    oxirgi/kelgusi tashrif, ishlatilgan/sotib olingan soat, segment."""
    today_s = today_iso()
    today_d = now_tashkent().date()
    m = defaultdict(lambda: {"ltv": 0.0, "purchased": 0.0, "used": 0.0,
                             "sessions": 0, "last": "", "next": ""})
    for p in Payment.query.all():
        d = m[p.teacher_id]
        if p.is_paid:
            d["ltv"] += p.amount or 0
        if p.kind == "package":
            d["purchased"] += p.hours or 0
    for b in Booking.query.all():
        d = m[b.teacher_id]
        if b.status in ("active", "done", "noshow") and b.pay_type == "package":
            d["used"] += b.hours
        if b.status in ("active", "done"):
            d["sessions"] += 1
            if b.date <= today_s:
                if b.date > d["last"]:
                    d["last"] = b.date
            elif not d["next"] or b.date < d["next"]:
                d["next"] = b.date
    # Segment + balans + recency har mijoz uchun
    created_map = dict(db.session.query(Teacher.id, Teacher.created_at).all())
    for tid, d in m.items():
        d["balance"] = round(d["purchased"] - d["used"], 2)
        last_dt = (datetime.strptime(d["last"], "%Y-%m-%d").date()
                   if d["last"] else None)
        cr = created_map.get(tid)
        cr = cr.date() if cr else None
        d["segment"] = _segment_of(last_dt, d["next"], cr, today_d)
        d["days_since"] = (today_d - last_dt).days if last_dt else None
    return m


@bp.route("/teachers")
@login_required
def index():
    q = (request.args.get("q") or "").strip()
    show = (request.args.get("show") or "active").strip()   # active|all|archive
    seg = (request.args.get("seg") or "").strip()           # segment filtri
    sort = (request.args.get("sort") or "recent").strip()   # recent|ltv|balance|name
    query = Teacher.query
    if show == "active":
        query = query.filter_by(is_active=True)
    elif show == "archive":
        query = query.filter_by(is_active=False)
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(
            Teacher.name.ilike(like), Teacher.phone.ilike(like),
            Teacher.telegram.ilike(like), Teacher.subject.ilike(like),
            Teacher.tags.ilike(like)))
    rows = query.all()

    metrics = _crm_metrics()
    items = []
    seg_counts = defaultdict(int)
    for t in rows:
        met = metrics.get(t.id, {"ltv": 0, "balance": 0, "sessions": 0,
                                 "last": "", "next": "", "segment": "new",
                                 "days_since": None})
        seg_counts[met["segment"]] += 1
        if seg and met["segment"] != seg:
            continue
        d = t.to_dict()
        d.update(met)
        items.append(d)

    # Saralash
    if sort == "ltv":
        items.sort(key=lambda x: -x["ltv"])
    elif sort == "balance":
        items.sort(key=lambda x: -x["balance"])
    elif sort == "name":
        items.sort(key=lambda x: x["name"].lower())
    else:  # recent — oxirgi tashrif (bo'sh — oxirida)
        items.sort(key=lambda x: (x["last"] or "0000"), reverse=True)

    # Muddati kelgan/o'tgan follow-up'lar (barcha mijozlar bo'yicha)
    tmap = {t.id: t.name for t in rows}
    due = []
    for n in ClientNote.query.filter_by(kind="followup", done=False).filter(
            ClientNote.due_date != "").order_by(ClientNote.due_date).all():
        if n.teacher_id in tmap:
            due.append({**n.to_dict(), "teacher": tmap[n.teacher_id]})

    return render_template(
        "teachers.html", teachers=items, q=q, show=show, seg=seg, sort=sort,
        total=len(items), segments=CRM_SEGMENTS, seg_counts=seg_counts,
        followups=due, today=today_iso())


@bp.route("/teachers/save", methods=["POST"])
@login_required
def save():
    u = current_user()
    f = request.form
    tid = f.get("id", "").strip()
    t = Teacher.query.get(int(tid)) if tid.isdigit() else None
    is_new = t is None
    if not t:
        t = Teacher(created_by=u.name)
        db.session.add(t)
    t.name = (f.get("name") or "").strip()[:200]
    if not t.name:
        flash("⛔ Ism kiritilishi shart", "error")
        return redirect(url_for("teachers.index"))
    # Dublikat himoyasi: bir xil telefon (oxirgi 9 raqam) bilan faol ustoz
    # bor bo'lsa — yangisini yaratmaymiz, mavjud kartani ochamiz
    _digits = "".join(c for c in (f.get("phone") or "") if c.isdigit())[-9:]
    if is_new and len(_digits) == 9:
        for ex in Teacher.query.filter_by(is_active=True).all():
            ex_d = "".join(c for c in (ex.phone or "") if c.isdigit())[-9:]
            if ex_d == _digits:
                db.session.rollback()
                flash(f"ℹ️ Bu raqam bazada bor: {ex.name} — kartasi ochildi "
                      f"(takror yozilmadi)", "error")
                return redirect(url_for("teachers.detail", tid=ex.id))
    t.phone = (f.get("phone") or "").strip()[:50]
    t.telegram = (f.get("telegram") or "").strip().lstrip("@")[:64]
    t.subject = (f.get("subject") or "").strip()[:120]
    t.note = (f.get("note") or "").strip()
    t.source = (f.get("source") or "").strip()[:80]
    t.tags = ",".join(x.strip() for x in (f.get("tags") or "").split(",")
                      if x.strip())[:200]
    t.is_active = bool(f.get("is_active", "1"))
    t.ensure_token()   # portal havolasi darhol tayyor bo'lsin
    db.session.commit()
    flash(f"✅ {t.name} {'qo`shildi' if is_new else 'yangilandi'}", "success")
    return redirect(url_for("teachers.detail", tid=t.id))


@bp.route("/teachers/<int:tid>/bonus", methods=["POST"])
@login_required
def bonus_hours(tid):
    """🎁 Bonus soat (referral/aksiya) — pulisiz paket, balansga qo'shiladi."""
    from core.auth import current_user as _cu
    u = _cu()
    if not u.is_admin:
        flash("Bonus berish faqat rahbar uchun", "error")
        return redirect(url_for("teachers.detail", tid=tid))
    t = Teacher.query.get_or_404(tid)
    try:
        hours = float(request.form.get("hours") or 0)
    except (ValueError, TypeError):
        hours = 0
    if not (0 < hours <= 20):
        flash("⛔ Bonus 0 dan katta, 20 soatdan oshmasin", "error")
        return redirect(url_for("teachers.detail", tid=tid))
    reason = (request.form.get("reason") or "Bonus").strip()[:200]
    db.session.add(Payment(
        teacher_id=tid, kind="package", hours=hours, amount=0,
        method="bonus", date=today_iso(), is_paid=True,
        note=f"🎁 {reason}", created_by=u.name))
    db.session.commit()
    flash(f"🎁 {t.name}: +{hours:g} bonus soat ({reason}). "
          f"Balans: {t.balance_hours():g}", "success")
    return redirect(url_for("teachers.detail", tid=tid))


@bp.route("/teachers/<int:tid>/token", methods=["POST"])
@login_required
def regen_token(tid):
    """Portal havolasini yangilash (eski havola bekor bo'ladi)."""
    t = Teacher.query.get_or_404(tid)
    t.portal_token = ""
    t.ensure_token()
    db.session.commit()
    flash("🔗 Yangi portal havolasi yaratildi (eskisi bekor)", "success")
    return redirect(url_for("teachers.detail", tid=tid))


@bp.route("/teachers/<int:tid>")
@login_required
def detail(tid):
    t = Teacher.query.get_or_404(tid)
    if not t.portal_token:
        t.ensure_token()
        db.session.commit()
    payments = Payment.query.filter_by(teacher_id=tid).order_by(
        Payment.id.desc()).limit(50).all()
    bookings = Booking.query.filter_by(teacher_id=tid).order_by(
        Booking.date.desc(), Booking.start.desc()).limit(50).all()
    smap = {s.id: s.name for s in Studio.query.all()}
    brows = []
    for b in bookings:
        d = b.to_dict()
        d["studio_name"] = smap.get(b.studio_id, "?")
        brows.append(d)
    portal_url = request.host_url.rstrip("/") + "/my/" + t.portal_token

    # CRM metrikasi (shu mijoz)
    met = _crm_metrics().get(t.id, {})
    seg = met.get("segment", "new")
    first_visit = min((b.date for b in bookings
                       if b.status in ("active", "done")), default="")
    # O'zaro aloqa tarixi (eslatma/qo'ng'iroq/follow-up)
    notes = ClientNote.query.filter_by(teacher_id=tid).order_by(
        ClientNote.done.asc(), ClientNote.id.desc()).limit(100).all()

    return render_template(
        "teacher_detail.html", t=t.to_dict(),
        purchased=t.hours_purchased(), used=t.hours_used(),
        ltv=met.get("ltv", 0), sessions=met.get("sessions", 0),
        last_visit=met.get("last", ""), next_visit=met.get("next", ""),
        first_visit=first_visit, days_since=met.get("days_since"),
        segment=seg, segment_label=CRM_SEGMENTS.get(seg, ("?", "gray")),
        segments=CRM_SEGMENTS,
        notes=[n.to_dict() for n in notes], note_kinds=NOTE_KINDS,
        payments=[p.to_dict() for p in payments],
        bookings=brows, methods=PAY_METHODS, today=today_iso(),
        portal_url=portal_url, tg_linked=bool(t.tg_chat_id))


@bp.route("/teachers/<int:tid>/note", methods=["POST"])
@login_required
def add_note(tid):
    """O'zaro aloqa yozuvi: eslatma/qo'ng'iroq/uchrashuv/follow-up."""
    Teacher.query.get_or_404(tid)
    u = current_user()
    kind = request.form.get("kind", "note")
    if kind not in NOTE_KINDS:
        kind = "note"
    text = (request.form.get("text") or "").strip()[:1000]
    due = (request.form.get("due_date") or "").strip()[:10]
    if not text and not (kind == "followup" and due):
        flash("Matn kiritilishi shart", "error")
        return redirect(url_for("teachers.detail", tid=tid))
    db.session.add(ClientNote(
        teacher_id=tid, author=u.name, kind=kind, text=text,
        due_date=due if kind == "followup" else ""))
    db.session.commit()
    flash("✅ Yozuv qo'shildi", "success")
    return redirect(url_for("teachers.detail", tid=tid) + "#notes")


@bp.route("/teachers/<int:tid>/note/<int:nid>/done", methods=["POST"])
@login_required
def note_done(tid, nid):
    n = ClientNote.query.filter_by(id=nid, teacher_id=tid).first_or_404()
    n.done = not n.done
    db.session.commit()
    return redirect(url_for("teachers.detail", tid=tid) + "#notes")


@bp.route("/teachers/<int:tid>/note/<int:nid>/delete", methods=["POST"])
@login_required
def note_delete(tid, nid):
    n = ClientNote.query.filter_by(id=nid, teacher_id=tid).first_or_404()
    db.session.delete(n)
    db.session.commit()
    flash("🗑 Yozuv o'chirildi", "success")
    return redirect(url_for("teachers.detail", tid=tid) + "#notes")


@bp.route("/teachers/<int:tid>/package", methods=["POST"])
@login_required
def buy_package(tid):
    """Paket sotish: N soat × narx → balans oshadi, to'lov yoziladi."""
    import math
    u = current_user()
    t = Teacher.query.get_or_404(tid)
    f = request.form
    try:
        hours = float((f.get("hours") or "0").replace(" ", "").replace(",", ""))
        amount = float((f.get("amount") or "0").replace(" ", "").replace(",", ""))
    except (ValueError, TypeError):
        hours = amount = 0
    # inf/nan va haddan tashqari qiymatlarни rad etamiz (balans buzilmasin)
    if not (math.isfinite(hours) and math.isfinite(amount)):
        hours = amount = 0
    if not (0 < hours <= 1000) or not (0 < amount <= 1_000_000_000):
        flash("⛔ Soat (0–1000) va summa 0 dan katta, real qiymat bo'lsin", "error")
        return redirect(url_for("teachers.detail", tid=tid))
    pay = Payment(
        teacher_id=tid, kind="package", hours=hours, amount=amount,
        method=(f.get("method") or "naqd")[:20],
        date=(f.get("date") or today_iso())[:10], is_paid=True,
        note=(f.get("note") or f"{hours:g} soatlik paket").strip()[:300],
        created_by=u.name)
    db.session.add(pay)
    db.session.flush()   # pay.id kerak (moliyaga bog'lash uchun)
    from modules.finance.studio_link import sync_payment_to_finance
    sync_payment_to_finance(pay, teacher_name=t.name)
    db.session.commit()
    flash(f"✅ {t.name}: +{hours:g} soat paket ({amount:,.0f} so'm). "
          f"Yangi balans: {t.balance_hours():g} soat", "success")
    return redirect(url_for("teachers.detail", tid=tid))
