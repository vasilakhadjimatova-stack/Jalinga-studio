"""Bronlar — oylik kalendar (Impulse uslubi) + yaratish/holat/tahrirlash.

Kalendar: oylik grid, studiya tablari, bron chipi bosilsa detal-popup.
Yangi bron bir nechta kunga birdan yozilishi mumkin (har kun alohida
konflikt/balans tekshiruvidan o'tadi).

Paket bron: ustoz balansidan yechiladi (balans yetmasa bloklanadi).
Soatbay bron: yaratilganda Payment (kutilmoqda) yoziladi — Moliya sahifasida
"to'landi" qilinadi. Bekor bo'lsa to'lov ham bekor bo'ladi.
"""
import calendar as pycal
import json
from datetime import datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify)

from core.auth import login_required, current_user
from core.timeutils import today_iso
from database import db
from models.studio import Studio, Booking
from models.billing import Teacher, Payment
from models.pricing import booking_price

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


def _resolve_client(f, created_by):
    """Bron formasidan mijozni aniqlaydi.

    'mavjud' rejim → teacher_id bo'yicha; 'yangi' rejim → ism/telefon bilan
    yaratadi. Dublikat himoyasi: to'liq raqamlar bir xil (mamlakat kodi bilan)
    bo'lsa yoki telefon 9 raqamli milliy formatда oxirgi 9 mos bo'lsa —
    mavjud mijozни qaytaradi (yangi yaratmaydi).
    Qaytaradi: (client|None, created(bool), xato_matni|None)."""
    mode = (f.get("client_mode") or "existing").strip()
    if mode == "new":
        name = (f.get("new_name") or "").strip()[:200]
        if not name:
            return None, False, "Yangi mijoz ismi kiritilmadi"
        phone = (f.get("new_phone") or "").strip()[:50]
        full = "".join(c for c in phone if c.isdigit())
        d9 = full[-9:]
        if len(full) >= 7:  # telefon bo'yicha dublikat tekshiruvi
            for ex in Teacher.query.filter_by(is_active=True).all():
                exf = "".join(c for c in (ex.phone or "") if c.isdigit())
                # to'liq mos yoki (ikkalasi ham 9-raqamli milliy) oxirgi 9 mos
                if exf and (exf == full or
                            (len(exf) >= 7 and len(full) >= 9 and len(exf) >= 9
                             and exf[-9:] == d9)):
                    return ex, False, None
        t = Teacher(name=name, phone=phone,
                    subject=(f.get("new_subject") or "").strip()[:120],
                    telegram=(f.get("new_telegram") or "").strip().lstrip("@")[:64],
                    created_by=created_by)
        t.ensure_token()
        db.session.add(t)
        db.session.flush()
        return t, True, None
    try:
        t = Teacher.query.get(int(f.get("teacher_id") or 0))
    except (ValueError, TypeError):
        t = None
    return t, False, (None if t else "Mijoz tanlanmadi")


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
            "teacher_id": b.teacher_id,
            "teacher": tmap.get(b.teacher_id, "?"),
            "date": b.date, "date_human": dh, "weekday": wd,
            "start": b.start, "end": b.end, "hours": b.hours,
            "status": b.status, "status_label": b.status_label(),
            "status_color": b.status_color(), "pay_type": b.pay_type,
            "amount": (booking_price(st, b.date, b.start, b.hours)[0]
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


@bp.route("/bookings/busy")
@login_required
def busy():
    """Bandlik kalendari uchun JSON: studiya+oy bo'yicha kunma-kun bronlar.

    ?studio_id=<id>&ym=YYYY-MM → {"YYYY-MM-DD": [{start,end,teacher,status}]}.
    """
    sid = request.args.get("studio_id", type=int)
    ym = (request.args.get("ym") or "").strip()[:7]
    if not (sid and len(ym) == 7):
        return jsonify({})
    tmap = {t.id: t.name for t in Teacher.query.all()}
    out = {}
    for b in Booking.query.filter(
            Booking.date.like(ym + "%"), Booking.studio_id == sid,
            Booking.status.in_(("active", "done", "noshow"))).order_by(
            Booking.start.asc()).all():
        out.setdefault(b.date, []).append({
            "start": b.start, "end": b.end,
            "teacher": tmap.get(b.teacher_id, "?"),
            "status": b.status_label()})
    return jsonify(out)


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
    except (ValueError, TypeError):
        studio = None
    start = (f.get("start") or "").strip()
    end = (f.get("end") or "").strip()
    pay_type = "package" if f.get("pay_type") == "package" else "hourly"

    # Reja: (sana, boshlanish, tugash) uchligi ro'yxati.
    #  • Har kunga alohida vaqt → slots_json = [{date,start,end},...]
    #  • Bo'lmasa → tanlangan barcha kunlar bitta start/end bilan
    plan = []
    raw = (f.get("slots_json") or "").strip()
    if raw:
        try:
            for it in json.loads(raw):
                d = str(it.get("date") or "").strip()[:10]
                s = str(it.get("start") or "").strip()[:5]
                e = str(it.get("end") or "").strip()[:5]
                if d and s and e:
                    plan.append({"date": d, "start": s, "end": e})
        except (ValueError, TypeError, AttributeError):
            plan = []
    if not plan:
        dates = []
        for d in f.getlist("date"):
            d = (d or "").strip()[:10]
            if d and d not in dates:
                dates.append(d)
        plan = [{"date": d, "start": start, "end": end} for d in dates]
    # Dublikat (sana+boshlanish) olib tashlash + sana/vaqt bo'yicha tartib
    seen, uniq = set(), []
    for it in plan:
        k = (it["date"], it["start"])
        if k not in seen and it["start"] and it["end"]:
            seen.add(k)
            uniq.append(it)
    plan = sorted(uniq, key=lambda x: (x["date"], x["start"]))

    first = plan[0]["date"] if plan else None
    if not (studio and plan):
        flash("⛔ Studiya, sana va vaqt to'ldirilishi shart", "error")
        return redirect(url_for("bookings.calendar", date=first))

    # Mijoz: mavjudini tanlash yoki shu yerda yangisini qo'shish
    teacher, was_new_client, cerr = _resolve_client(f, u.name)
    if not teacher:
        flash(f"⛔ {cerr}", "error")
        return redirect(url_for("bookings.calendar", date=first))

    from sqlalchemy.exc import IntegrityError
    operator = (f.get("operator") or "").strip()[:120]
    note = (f.get("note") or "").strip()[:300]
    try:
        manual_disc = max(0, min(90, int(f.get("discount") or 0)))
    except (ValueError, TypeError):
        manual_disc = 0
    made, errs = [], []
    for it in plan:
        day, s_, e_ = it["date"], it["start"], it["end"]
        probe = Booking(studio_id=studio.id, teacher_id=teacher.id,
                        date=day, start=s_, end=e_)
        hrs = probe.hours
        if hrs <= 0:
            errs.append(f"{day} {s_}–{e_} — vaqt xato")
            continue
        if not Booking.within_work_hours(s_, e_):
            errs.append(f"{day} {s_}–{e_} — ish vaqtidan tashqari "
                        f"({Config.WORK_START:02d}:00–{Config.WORK_END:02d}:00)")
            continue
        # Konflikt — bir studiyada bir vaqtda bitta yozuv
        c = Booking.conflict(studio.id, day, s_, e_)
        if c:
            errs.append(f"{day} {s_}–{e_} — band ({c.start}–{c.end})")
            continue
        # Paket: balans (flush qilingan yangi bronlar ham hisobga kiradi)
        if pay_type == "package":
            bal = teacher.balance_hours()
            if bal < hrs:
                errs.append(f"{day} — balans yetmadi ({bal:g} soat qoldi)")
                continue
        # Savepoint: shu kun poyga tufayli DB'да rad etilsa (unikal slot
        # indeksi), faqat shu kun tushib qoladi — qolganlari saqlanadi.
        try:
            with db.session.begin_nested():
                b = Booking(studio_id=studio.id, teacher_id=teacher.id,
                            date=day, start=s_, end=e_, pay_type=pay_type,
                            operator=operator, note=note, created_by=u.name)
                db.session.add(b)
                db.session.flush()
                if pay_type == "hourly":
                    amount, disc, rname, _b = booking_price(
                        studio, day, s_, hrs, manual=manual_disc)
                    pnote = (f"{studio.name} · {day} {s_}–{e_} "
                             f"({hrs:g} soat)")
                    if disc:
                        pnote += f" · −{disc}%"
                    db.session.add(Payment(
                        teacher_id=teacher.id, booking_id=b.id, kind="hourly",
                        amount=amount, hours=0, date=day, is_paid=False,
                        note=pnote, created_by=u.name))
        except IntegrityError:
            errs.append(f"{day} {s_}–{e_} — endigina band bo'ldi")
            continue
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
        total_hours_made = sum(b.hours for b in made)
        if pay_type == "package":
            extra = f" · balansdan {total_hours_made:g} soat"
        else:
            total_amt = sum(
                booking_price(studio, b.date, b.start, b.hours,
                              manual=manual_disc)[0] for b in made)
            extra = f" · to'lov {total_amt:,.0f} so'm (kutilmoqda)".replace(
                ",", " ")
        newc = " · 🆕 yangi mijoz qo'shildi" if was_new_client else ""
        flash(f"✅ {teacher.name} — {studio.name}: "
              f"{len(made)} kun bron qilindi ({days_txt}){extra}{newc}",
              "success")
    elif was_new_client:
        # Bron bo'lmadi-yu, lekin mijoz yaratildi — foydali qoladi
        flash(f"🆕 Yangi mijoz qo'shildi: {teacher.name} "
              f"(karta: /teachers/{teacher.id})", "success")
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
    warn = ""
    # Bekor bo'lsa — kutilayotgan soatbay to'lov o'chadi. Agar to'lov ALLAQACHON
    # "to'landi" bo'lsa — u haqiqiy pul, o'chirmaymiz, lekin ogohlantiramiz
    # (kerak bo'lsa Moliyada qaytariladi) — arvoh daromad oldini olish.
    if new == "cancelled":
        paid_left = Payment.query.filter_by(
            booking_id=b.id, is_paid=True).count()
        Payment.query.filter_by(booking_id=b.id, is_paid=False).delete(
            synchronize_session=False)
        if paid_left:
            warn = (" · ⚠️ bu bronда to'langan to'lov bor — kerak bo'lsa "
                    "Moliyada qaytaring")
    # «done» dan boshqa holatga o'tsa — montaj kartasi endi keraksiz
    # (yetim karta kanbanда qolib ketmasin: cancel/noshow/active hammasi).
    if new == "done":
        t = Teacher.query.get(b.teacher_id)
        EditJob.for_booking(b, teacher_name=(t.name if t else ""))
    else:
        EditJob.query.filter(EditJob.booking_id == b.id,
                             EditJob.status != "delivered").delete(
            synchronize_session=False)
    db.session.commit()
    extra = ""
    if new == "noshow" and b.pay_type == "package":
        extra = f" — {b.hours:g} soat balansdan kuydi (24 soat qoidasi)"
    elif new == "noshow":
        extra = " — soatbay to'lov qarz sifatida qoladi"
    flash(f"Holat: {b.status_label()}{extra}{warn}", "success")
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
    # Soatbay: to'lov summasi/izohi yangilanadi — ALLAQACHON to'langan bo'lsa
    # ham (aks holda 2 soatlik to'langan bron 4 soatga o'zgarsa, daromad eski
    # summada qolib kam hisoblanardi).
    pay_note = ""
    if b.pay_type == "hourly":
        p = Payment.query.filter_by(booking_id=b.id).order_by(
            Payment.is_paid.asc(), Payment.id.desc()).first()
        if p:
            was_paid = p.is_paid
            from models.pricing import booking_price
            p.amount, _d, _r, _b = booking_price(
                studio, day, start, new_hours)
            p.date = day
            p.note = (f"{studio.name} · {day} {start}–{end} ({new_hours:g} soat)"
                      + (f" · −{_d}%" if _d else ""))
            if was_paid:
                pay_note = " · 💵 to'langan summa qayta hisoblandi"
                # Moliya jurnalidagi bog'langan kirim ham yangilansin
                from modules.finance.studio_link import sync_payment_to_finance
                sync_payment_to_finance(p, teacher_name=teacher.name
                                        if teacher else None)
    db.session.commit()

    try:
        from core.telegram import notify_teacher_booking
        notify_teacher_booking(b, studio, teacher, created=False)
    except Exception:
        pass
    flash(f"✏️ Bron ko'chirildi: {old_desc} → {day} {start}–{end}{pay_note}",
          "success")
    return redirect(url_for("bookings.calendar", date=day))
