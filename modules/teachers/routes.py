"""Ustozlar — mini-CRM: profil, paket sotish, balans, yozuvlar tarixi."""
from flask import Blueprint, render_template, request, redirect, url_for, flash

from core.auth import login_required, current_user
from core.timeutils import today_iso
from database import db
from models.billing import Teacher, Payment, PAY_METHODS
from models.studio import Booking, Studio

bp = Blueprint("teachers", __name__)


@bp.route("/teachers")
@login_required
def index():
    rows = Teacher.query.order_by(Teacher.is_active.desc(),
                                  Teacher.name.asc()).all()
    return render_template("teachers.html",
                           teachers=[t.to_dict() for t in rows])


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
    t.phone = (f.get("phone") or "").strip()[:50]
    t.telegram = (f.get("telegram") or "").strip().lstrip("@")[:64]
    t.subject = (f.get("subject") or "").strip()[:120]
    t.note = (f.get("note") or "").strip()
    t.is_active = bool(f.get("is_active", "1"))
    t.ensure_token()   # portal havolasi darhol tayyor bo'lsin
    db.session.commit()
    flash(f"✅ {t.name} {'qo`shildi' if is_new else 'yangilandi'}", "success")
    return redirect(url_for("teachers.detail", tid=t.id))


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
    return render_template(
        "teacher_detail.html", t=t.to_dict(),
        purchased=t.hours_purchased(), used=t.hours_used(),
        payments=[p.to_dict() for p in payments],
        bookings=brows, methods=PAY_METHODS, today=today_iso(),
        portal_url=portal_url, tg_linked=bool(t.tg_chat_id))


@bp.route("/teachers/<int:tid>/package", methods=["POST"])
@login_required
def buy_package(tid):
    """Paket sotish: N soat × narx → balans oshadi, to'lov yoziladi."""
    u = current_user()
    t = Teacher.query.get_or_404(tid)
    f = request.form
    try:
        hours = float(f.get("hours") or 0)
        amount = float((f.get("amount") or "0").replace(" ", ""))
    except (ValueError, TypeError):
        hours = amount = 0
    if hours <= 0 or amount <= 0:
        flash("⛔ Soat va summa 0 dan katta bo'lsin", "error")
        return redirect(url_for("teachers.detail", tid=tid))
    db.session.add(Payment(
        teacher_id=tid, kind="package", hours=hours, amount=amount,
        method=(f.get("method") or "naqd")[:20],
        date=(f.get("date") or today_iso())[:10], is_paid=True,
        note=(f.get("note") or f"{hours:g} soatlik paket").strip()[:300],
        created_by=u.name))
    db.session.commit()
    flash(f"✅ {t.name}: +{hours:g} soat paket ({amount:,.0f} so'm). "
          f"Yangi balans: {t.balance_hours():g} soat", "success")
    return redirect(url_for("teachers.detail", tid=tid))
