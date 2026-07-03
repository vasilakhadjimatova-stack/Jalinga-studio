"""Bronlar — oylik kalendar (Impulse uslubi) + yaratish/holat/tahrirlash.

Kalendar: oylik grid, studiya tablari, bron chipi bosilsa detal-popup.
Yangi bron bir nechta kunga birdan yozilishi mumkin (har kun alohida
konflikt/balans tekshiruvidan o'tadi).

Paket bron: ustoz balansidan yechiladi (balans yetmasa bloklanadi).
Soatbay bron: yaratilganda Payment (kutilmoqda) yoziladi — Moliya sahifasida
"to'landi" qilinadi. Bekor bo'lsa to'lov ham bekor bo'ladi.
"""
import calendar as pycal
from datetime import datetime

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
UZ_WD_FULL = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba",
              "Juma", "Shanba", "Yakshanba"]
UZ_MO_FULL = ["yanvar", "fevral", "mart", "aprel", "may", "iyun",
              "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]


def _human_date(ds):
    """'2026-07-06' → ('6 iyul 2026', 'Dushanba')."""
    try:
        dt = datetime.strptime(ds, "%Y-%m-%d")
        return (f"{dt.day} {UZ_MO_FULL[dt.month - 1]} {dt.year}",
                UZ_WD_FULL[dt.weekday()])
    except (ValueError, IndexError):
        return ds, ""


@bp.route("/calendar")
@login_required
def calendar():
    """Oylik kalendar — yagona kalendar ko'rinishi.

    ?year=&month= yoki ?date=YYYY-MM-DD (eski havolalar) qabul qilinadi;
    ?studio=ID — bitta studiya bo'yicha filtr.
    """
    today = datetime.strptime(today_iso(), "%Y-%m-%d").date()
    year = request.args.get("year", type=int, default=0)
    month = request.args.get("month", type=int, default=0)
    dparam = (request.args.get("date") or "").strip()
    if dparam and not (year and month):
        try:
            dd = datetime.strptime(dparam, "%Y-%m-%d").date()
            year, month = dd.year, dd.month
        except ValueError:
            pass
    year, month = year or today.year, month or today.month
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
    buckets, bk, n_book, total_hours = {}, {}, 0, 0.0
    for b in q.order_by(Booking.date.asc(), Booking.start.asc()).all():
        st = smap.get(b.studio_id)
        scolor = st.color if st else "#6098F2"
        buckets.setdefault(b.date, []).append({
            "id": b.id,
            "title": f"{b.start} {tmap.get(b.teacher_id, '?')}",
            "color": b.status_color(), "scolor": scolor,
            "studio": (st.name if st else "?"),
        })
        dh, wd = _human_date(b.date)
        bk[b.id] = {
            "id": b.id, "studio_id": b.studio_id,
            "studio": (st.name if st else "?"), "scolor": scolor,
            "teacher": tmap.get(b.teacher_id, "?"),
            "date": b.date, "date_human": dh, "weekday": wd,
            "start": b.start, "end": b.end, "hours": b.hours,
            "status": b.status, "status_label": b.status_label(),
            "status_color": b.status_color(), "pay_type": b.pay_type,
            "amount": (round(b.hours * (st.hourly_rate or 0))
                       if (st and b.pay_type == "hourly") else 0),
            "operator": b.operator or "", "note": b.note or "",
            "created_by": b.created_by or "",
        }
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
        weekdays=WEEKDAYS, weeks=weeks, agenda=agenda, bk=bk,
        studios=[s.to_dict() for s in studios],
        teachers=[t.to_dict() for t in teachers],
        sel=(sel.to_dict() if sel else None),
        n_book=n_book, total_hours=total_hours,
        prev_m=month - 1, prev_y=year, next_m=month + 1, next_y=year,
        today_iso=today.strftime("%Y-%m-%d"))


@bp.route("/calendar/month")
@login_required
def month_view():
    """Eski havolalar uchun — /calendar'ga yo'naltiradi."""
    return redirect(url_for("bookings.calendar", **request.args))


@bp.route("/bookings/save", methods=["POST"])
@login_required
def save():
    """Bron yaratish — bir yoki BIR NECHTA kunga (har biri alohida
    konflikt/balans tekshiruvidan o'tadi; xatolar kun-kun ko'rsatiladi)."""
    from config import Config
    u = current_user()
    f = request.form
    try:
        studio = Studio.query.get(int(f.get("studio_id") or 0))
        teacher = Teacher.query.get(int(f.get("teacher_id") or 0))
    except (ValueError, TypeError):
        studio = teacher = None
    dates = []
    for d in f.getlist("date"):
        d = (d or "").strip()[:10]
        if d and d not in dates:
            dates.append(d)
    dates.sort()
    start = (f.get("start") or "").strip()
    end = (f.get("end") or "").strip()
    pay_type = "package" if f.get("pay_type") == "package" else "hourly"
    first = dates[0] if dates else None
    if not (studio and teacher and dates and start and end):
        flash("⛔ Studiya, ustoz, sana va vaqt to'ldirilishi shart", "error")
        return redirect(url_for("bookings.calendar", date=first))

    probe = Booking(studio_id=studio.id, teacher_id=teacher.id,
                    date=first, start=start, end=end)
    if probe.hours <= 0:
        flash("⛔ Tugash vaqti boshlanishdan keyin bo'lishi kerak", "error")
        return redirect(url_for("bookings.calendar", date=first))

    # Ish vaqti chegarasi (hamma kun uchun bir xil vaqt)
    if not Booking.within_work_hours(start, end):
        flash(f"⛔ Studiya ish vaqti: {Config.WORK_START:02d}:00–"
              f"{Config.WORK_END:02d}:00. Shu oraliqda tanlang.", "error")
        return redirect(url_for("bookings.calendar", date=first))

    per_hours = probe.hours
    operator = (f.get("operator") or "").strip()[:120]
    note = (f.get("note") or "").strip()[:300]
    made, errs = [], []
    for day in dates:
        # Konflikt — bir studiyada bir vaqtda bitta yozuv
        c = Booking.conflict(studio.id, day, start, end)
        if c:
            errs.append(f"{day} — band ({c.start}–{c.end})")
            continue
        # Paket: balans (flush qilingan yangi bronlar ham hisobga kiradi)
        if pay_type == "package":
            bal = teacher.balance_hours()
            if bal < per_hours:
                errs.append(f"{day} — balans yetmadi ({bal:g} soat qoldi)")
                continue
        b = Booking(studio_id=studio.id, teacher_id=teacher.id, date=day,
                    start=start, end=end, pay_type=pay_type,
                    operator=operator, note=note, created_by=u.name)
        db.session.add(b)
        db.session.flush()
        # Soatbay: kutilayotgan to'lov (Moliya sahifasida tasdiqlanadi)
        if pay_type == "hourly":
            amount = round(per_hours * (studio.hourly_rate or 0))
            db.session.add(Payment(
                teacher_id=teacher.id, booking_id=b.id, kind="hourly",
                amount=amount, hours=0, date=day, is_paid=False,
                note=f"{studio.name} · {day} {start}–{end} ({per_hours:g} soat)",
                created_by=u.name))
        made.append(b)
    db.session.commit()

    for b in made:
        try:
            from core.telegram import notify_teacher_booking
            notify_teacher_booking(b, studio, teacher, created=True)
        except Exception:
            pass

    if made:
        days_txt = ", ".join(b.date for b in made[:5])
        if len(made) > 5:
            days_txt += f" +{len(made) - 5}"
        extra = (f" · balansdan {per_hours * len(made):g} soat"
                 if pay_type == "package" else
                 f" · to'lov {round(per_hours * (studio.hourly_rate or 0)) * len(made):,.0f} so'm (kutilmoqda)")
        flash(f"✅ {teacher.name} — {studio.name} {start}–{end}: "
              f"{len(made)} kun bron qilindi ({days_txt}){extra}", "success")
    if errs:
        flash("⛔ Bron bo'lmadi: " + " · ".join(errs), "error")
    return redirect(url_for("bookings.calendar",
                            date=(made[0].date if made else first)))


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
    # Yozildi ✓ → montaj kartasi avto-yaraladi (kanbanda ko'rinadi)
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
