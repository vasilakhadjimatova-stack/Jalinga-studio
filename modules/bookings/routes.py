"""Bronlar — kunlik kalendar + yaratish/holat (konflikt tekshiruvi bilan).

Paket bron: ustoz balansidan yechiladi (balans yetmasa bloklanadi).
Soatbay bron: yaratilganda Payment (kutilmoqda) yoziladi — Moliya sahifasida
"to'landi" qilinadi. Bekor bo'lsa to'lov ham bekor bo'ladi.
"""
import calendar as pycal
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash

from core.auth import login_required, current_user
from core.timeutils import today_iso
from database import db
from models.studio import Studio, Booking
from models.billing import Teacher, Payment

bp = Blueprint("bookings", __name__)

MONTHS_UZ = ["", "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
             "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"]
WEEKDAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]


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


@bp.route("/calendar/month")
@login_required
def month_view():
    """Oylik kalendar (Impulse uslubi) — studiya bo'yicha filtrlash mumkin.

    Studiyalar sahifasida yoki kunlik kalendarda studiya bosilsa shu sahifa
    ochiladi. Kun katakchasi bosilsa — shu sana bilan bron oynasi ochiladi.
    """
    today = datetime.strptime(today_iso(), "%Y-%m-%d").date()
    year = request.args.get("year", type=int, default=today.year)
    month = request.args.get("month", type=int, default=today.month)
    if month < 1:
        month, year = 12, year - 1
    if month > 12:
        month, year = 1, year + 1

    studios = Studio.query.filter_by(is_active=True).order_by(
        Studio.sort.asc(), Studio.id.asc()).all()
    sel_id = request.args.get("studio", type=int)
    sel = next((s for s in studios if s.id == sel_id), None)

    teachers = Teacher.query.filter_by(is_active=True).order_by(
        Teacher.name.asc()).all()
    tmap = {t.id: t.name for t in teachers}
    smap = {s.id: s for s in studios}

    prefix = f"{year:04d}-{month:02d}"
    q = Booking.query.filter(
        Booking.date.like(prefix + "%"),
        Booking.status.in_(("active", "done", "noshow")))
    if sel:
        q = q.filter(Booking.studio_id == sel.id)
    buckets, n_book, total_hours = {}, 0, 0.0
    for b in q.order_by(Booking.date.asc(), Booking.start.asc()).all():
        st = smap.get(b.studio_id)
        buckets.setdefault(b.date, []).append({
            "title": f"{b.start} {tmap.get(b.teacher_id, '?')}",
            "color": b.status_color(),
            "scolor": (st.color if st else "#6098F2"),
            "studio": (st.name if st else "?"),
        })
        n_book += 1
        total_hours += b.hours

    cal = pycal.Calendar(firstweekday=0)  # Dushanba
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        row = []
        for d in week:
            ds = d.strftime("%Y-%m-%d")
            row.append({"day": d.day, "in_month": d.month == month,
                        "is_today": d == today, "iso": ds,
                        "evs": buckets.get(ds, [])})
        weeks.append(row)

    # Yaqin kunlar (bugundan boshlab, shu oy ichida)
    agenda = []
    for ds in sorted(buckets):
        if ds >= today.strftime("%Y-%m-%d"):
            for it in buckets[ds]:
                agenda.append({**it, "date": ds})
    agenda = agenda[:15]

    return render_template(
        "calendar_month.html",
        year=year, month=month, month_name=MONTHS_UZ[month],
        weekdays=WEEKDAYS, weeks=weeks, agenda=agenda,
        studios=[s.to_dict() for s in studios],
        teachers=[t.to_dict() for t in teachers],
        sel=(sel.to_dict() if sel else None),
        n_book=n_book, total_hours=total_hours,
        prev_m=month - 1, prev_y=year, next_m=month + 1, next_y=year,
        today_iso=today.strftime("%Y-%m-%d"))


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

    # Ish vaqti chegarasi (studiya 09:00–21:00 ishlaydi)
    from config import Config
    if not Booking.within_work_hours(start, end):
        flash(f"⛔ Studiya ish vaqti: {Config.WORK_START:02d}:00–"
              f"{Config.WORK_END:02d}:00. Shu oraliqda tanlang.", "error")
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
    from models.montaj import EditJob
    # Bekor bo'lsa — kutilayotgan soatbay to'lov + topshirilmagan montaj
    # kartasi ham bekor (yetim karta qolmaydi)
    if new == "cancelled":
        Payment.query.filter_by(booking_id=b.id, is_paid=False).delete(
            synchronize_session=False)
        EditJob.query.filter(EditJob.booking_id == b.id,
                             EditJob.status != "delivered").delete(
            synchronize_session=False)
    # Yozildi ✓ → montaj kartasi avto-yaraladi (kanbanда ko'rinadi)
    if new == "done":
        t = Teacher.query.get(b.teacher_id)
        EditJob.for_booking(b, teacher_name=(t.name if t else ""))
    db.session.commit()
    extra = ""
    if new == "noshow" and b.pay_type == "package":
        extra = f" — {b.hours:g} soat balansdan kuydi (24 soat qoidasi)"
    elif new == "noshow":
        extra = " — soatbay to'lov qarz sifatida qoladi"
    flash(f"Holat: {b.status_label()}{extra}", "success")
    return redirect(url_for("bookings.calendar", date=b.date))


@bp.route("/bookings/<int:bid>/edit", methods=["POST"])
@login_required
def edit(bid):
    """Bronni ko'chirish/tahrirlash — konflikt, ish vaqti va balans qayta
    tekshiriladi; kutilayotgan soatbay to'lov summasi yangilanadi."""
    from config import Config
    u = current_user()
    b = Booking.query.get_or_404(bid)
    if b.status not in ("active",):
        flash("Faqat rejalashtirilgan bronni tahrirlash mumkin", "error")
        return redirect(url_for("bookings.calendar", date=b.date))
    f = request.form
    try:
        studio = Studio.query.get(int(f.get("studio_id") or b.studio_id))
    except (ValueError, TypeError):
        studio = Studio.query.get(b.studio_id)
    day = (f.get("date") or b.date).strip()[:10]
    start = (f.get("start") or b.start).strip()[:5]
    end = (f.get("end") or b.end).strip()[:5]

    old_hours = b.hours
    old_desc = f"{b.date} {b.start}–{b.end}"

    # Validatsiyalar (yaratishdagi bilan bir xil qat'iylik)
    from models.studio import _to_minutes
    if _to_minutes(end) <= _to_minutes(start):
        flash("⛔ Tugash vaqti boshlanishdan keyin bo'lishi kerak", "error")
        return redirect(url_for("bookings.calendar", date=b.date))
    if not Booking.within_work_hours(start, end):
        flash(f"⛔ Studiya ish vaqti: {Config.WORK_START:02d}:00–"
              f"{Config.WORK_END:02d}:00.", "error")
        return redirect(url_for("bookings.calendar", date=b.date))
    c = Booking.conflict(studio.id, day, start, end, exclude_id=b.id)
    if c:
        flash(f"⛔ VAQT BAND: {day} «{studio.name}» {c.start}–{c.end}. "
              f"Boshqa vaqt tanlang.", "error")
        return redirect(url_for("bookings.calendar", date=b.date))

    # Yangi davomiylik
    new_hours = (_to_minutes(end) - _to_minutes(start)) / 60
    teacher = Teacher.query.get(b.teacher_id)
    # Paket: balans qayta tekshiruvi (shu bronning eski soatini chiqarib)
    if b.pay_type == "package" and teacher:
        available = teacher.balance_hours() + old_hours
        if available < new_hours:
            flash(f"⛔ Balans yetarli emas: {available:g} soat mavjud, "
                  f"{new_hours:g} kerak.", "error")
            return redirect(url_for("bookings.calendar", date=b.date))

    b.studio_id, b.date, b.start, b.end = studio.id, day, start, end
    b.operator = (f.get("operator") or b.operator or "").strip()[:120]
    b.reminded = False   # vaqt o'zgardi — eslatma qayta yuborilsin
    # Soatbay: kutilayotgan to'lov summasi/izohi yangilanadi
    if b.pay_type == "hourly":
        p = Payment.query.filter_by(booking_id=b.id, is_paid=False).first()
        if p:
            p.amount = round(new_hours * (studio.hourly_rate or 0))
            p.date = day
            p.note = f"{studio.name} · {day} {start}–{end} ({new_hours:g} soat)"
    db.session.commit()

    try:
        from core.telegram import notify_teacher_booking
        notify_teacher_booking(b, studio, teacher, created=False)
    except Exception:
        pass
    flash(f"✏️ Bron ko'chirildi: {old_desc} → {day} {start}–{end}", "success")
    return redirect(url_for("bookings.calendar", date=day))
