"""Bronlar — kunlik kalendar + yaratish/holat (konflikt tekshiruvi bilan).

Paket bron: ustoz balansidan yechiladi (balans yetmasa bloklanadi).
Soatbay bron: yaratilganda Payment (kutilmoqda) yoziladi — Moliya sahifasida
"to'landi" qilinadi. Bekor bo'lsa to'lov ham bekor bo'ladi.
"""
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash

from core.auth import login_required, current_user
from core.timeutils import today_iso
from database import db
from models.studio import Studio, Booking
from models.billing import Teacher, Payment

bp = Blueprint("bookings", __name__)


@bp.route("/calendar")
@login_required
def calendar():
    day = (request.args.get("date") or today_iso()).strip()
    try:
        d0 = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        d0 = datetime.strptime(today_iso(), "%Y-%m-%d").date()
        day = d0.strftime("%Y-%m-%d")
    prev_day = (d0 - timedelta(days=1)).strftime("%Y-%m-%d")
    next_day = (d0 + timedelta(days=1)).strftime("%Y-%m-%d")

    studios = Studio.query.filter_by(is_active=True).order_by(
        Studio.sort.asc(), Studio.id.asc()).all()
    teachers = Teacher.query.filter_by(is_active=True).order_by(
        Teacher.name.asc()).all()
    tmap = {t.id: t.name for t in teachers}

    bookings = Booking.query.filter(
        Booking.date == day,
        Booking.status.in_(("active", "done", "noshow"))).order_by(
        Booking.start.asc()).all()
    by_studio = {}
    for b in bookings:
        d = b.to_dict()
        d["teacher_name"] = tmap.get(b.teacher_id, "?")
        by_studio.setdefault(b.studio_id, []).append(d)

    return render_template(
        "calendar.html", day=day, prev_day=prev_day, next_day=next_day,
        is_today=(day == today_iso()),
        studios=[s.to_dict() for s in studios],
        teachers=[t.to_dict() for t in teachers],
        by_studio=by_studio)


@bp.route("/bookings/save", methods=["POST"])
@login_required
def save():
    u = current_user()
    f = request.form
    try:
        studio = Studio.query.get(int(f.get("studio_id") or 0))
        teacher = Teacher.query.get(int(f.get("teacher_id") or 0))
    except (ValueError, TypeError):
        studio = teacher = None
    day = (f.get("date") or "").strip()
    start = (f.get("start") or "").strip()
    end = (f.get("end") or "").strip()
    pay_type = "package" if f.get("pay_type") == "package" else "hourly"
    if not (studio and teacher and day and start and end):
        flash("⛔ Studiya, ustoz, sana va vaqt to'ldirilishi shart", "error")
        return redirect(url_for("bookings.calendar", date=day or None))

    b = Booking(studio_id=studio.id, teacher_id=teacher.id, date=day,
                start=start, end=end, pay_type=pay_type,
                operator=(f.get("operator") or "").strip()[:120],
                note=(f.get("note") or "").strip()[:300],
                created_by=u.name)
    if b.hours <= 0:
        flash("⛔ Tugash vaqti boshlanishdan keyin bo'lishi kerak", "error")
        return redirect(url_for("bookings.calendar", date=day))

    # Konflikt — bir studiyada bir vaqtda bitta yozuv
    c = Booking.conflict(studio.id, day, start, end)
    if c:
        flash(f"⛔ VAQT BAND: {day} «{studio.name}» {c.start}–{c.end} "
              f"allaqachon bron qilingan. Boshqa vaqt tanlang.", "error")
        return redirect(url_for("bookings.calendar", date=day))

    # Paket: balans yetarlimi (shu bron hisobga kirmasidan avval)
    if pay_type == "package":
        bal = teacher.balance_hours()
        if bal < b.hours:
            flash(f"⛔ {teacher.name} balansi yetarli emas: {bal} soat bor, "
                  f"{b.hours:g} soat kerak. Avval paket sotib oling.", "error")
            return redirect(url_for("bookings.calendar", date=day))

    db.session.add(b)
    db.session.flush()

    # Soatbay: kutilayotgan to'lov yoziladi (Moliya sahifasida tasdiqlanadi)
    if pay_type == "hourly":
        amount = round(b.hours * (studio.hourly_rate or 0))
        db.session.add(Payment(
            teacher_id=teacher.id, booking_id=b.id, kind="hourly",
            amount=amount, hours=0, date=day, is_paid=False,
            note=f"{studio.name} · {day} {start}–{end} ({b.hours:g} soat)",
            created_by=u.name))
    db.session.commit()

    try:
        from core.telegram import notify_teacher_booking
        notify_teacher_booking(b, studio, teacher, created=True)
    except Exception:
        pass

    extra = (f" · balansdan {b.hours:g} soat" if pay_type == "package"
             else f" · to'lov {round(b.hours * (studio.hourly_rate or 0)):,.0f} so'm (kutilmoqda)")
    flash(f"✅ Bron: {teacher.name} — {studio.name} {day} {start}–{end}{extra}",
          "success")
    return redirect(url_for("bookings.calendar", date=day))


@bp.route("/bookings/<int:bid>/status", methods=["POST"])
@login_required
def set_status(bid):
    b = Booking.query.get_or_404(bid)
    new = (request.form.get("status") or "").strip()
    if new not in ("active", "done", "cancelled", "noshow"):
        flash("Holat noto'g'ri", "error")
        return redirect(url_for("bookings.calendar", date=b.date))
    b.status = new
    # Bekor bo'lsa — bog'liq kutilayotgan soatbay to'lov ham bekor
    if new == "cancelled":
        Payment.query.filter_by(booking_id=b.id, is_paid=False).delete(
            synchronize_session=False)
    db.session.commit()
    flash(f"Holat: {b.status_label()}", "success")
    return redirect(url_for("bookings.calendar", date=b.date))
