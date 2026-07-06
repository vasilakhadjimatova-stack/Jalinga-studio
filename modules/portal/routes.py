"""Ustoz shaxsiy portali — maxfiy havola (token) bilan, parolsiz.

Havola = kalit: /my/<token>. Token bilmagan odam kira olmaydi (404).
Ustoz: balansini, kelgusi yozuvlarini ko'radi; bo'sh vaqtga O'ZI bron
qiladi; 24 soatdan ko'p qolgan bronni bekor qila oladi (kech bo'lsa —
studiyaga qo'ng'iroq).
"""
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect,
                    url_for, flash, abort)

from core.timeutils import now_tashkent, today_iso
from database import db
from models.studio import Studio, Booking
from models.billing import Teacher, Payment

bp = Blueprint("portal", __name__)

CANCEL_HOURS = 24   # bekor qilish siyosati: kamida 24 soat oldin
MAX_UPCOMING = 8    # portaldan spam-bandlikni cheklash (faol kelgusi bronlar)


def _teacher_or_404(token):
    token = (token or "").strip()
    if len(token) < 16:
        abort(404)
    t = Teacher.query.filter_by(portal_token=token, is_active=True).first()
    if not t:
        abort(404)
    return t


def _starts_at(b):
    try:
        return datetime.strptime(f"{b.date} {b.start}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


@bp.route("/my/<token>")
def home(token):
    t = _teacher_or_404(token)
    today = today_iso()
    now = now_tashkent()

    upcoming, history = [], []
    smap = {s.id: s for s in Studio.query.all()}
    rows = Booking.query.filter_by(teacher_id=t.id).order_by(
        Booking.date.desc(), Booking.start.desc()).limit(60).all()
    for b in rows:
        d = b.to_dict()
        s = smap.get(b.studio_id)
        d["studio_name"] = s.name if s else "?"
        st = _starts_at(b)
        if b.status == "active" and st and st >= now:
            d["can_cancel"] = (st - now) >= timedelta(hours=CANCEL_HOURS)
            upcoming.append(d)
        else:
            history.append(d)
    upcoming.sort(key=lambda x: (x["date"], x["start"]))

    # Bron formasi uchun: faol studiyalar + tanlangan kun bandligi
    day = (request.args.get("date") or today).strip()[:10]
    studios = Studio.query.filter_by(is_active=True).order_by(
        Studio.sort.asc()).all()
    busy = {}
    for b in Booking.query.filter(
            Booking.date == day,
            Booking.status.in_(("active", "done"))).all():
        busy.setdefault(b.studio_id, []).append(f"{b.start}–{b.end}")

    from core.telegram import is_configured, bot_username
    return render_template(
        "portal.html", t=t.to_dict(), token=token,
        upcoming=upcoming, history=history[:20],
        studios=[s.to_dict() for s in studios], busy=busy, day=day,
        today=today, cancel_hours=CANCEL_HOURS,
        tg_ready=is_configured(), tg_bot=bot_username() if is_configured() else "",
        tg_linked=bool(t.tg_chat_id))


@bp.route("/my/<token>/book", methods=["POST"])
def book(token):
    t = _teacher_or_404(token)
    f = request.form
    try:
        studio = Studio.query.get(int(f.get("studio_id") or 0))
    except (ValueError, TypeError):
        studio = None
    day = (f.get("date") or "").strip()[:10]
    start = (f.get("start") or "").strip()[:5]
    try:
        dur = min(6.0, max(0.5, float(f.get("hours") or 1)))
    except (ValueError, TypeError):
        dur = 1.0
    pay_type = "package" if f.get("pay_type") == "package" else "hourly"

    if not (studio and studio.is_active and day and start):
        flash("⛔ Studiya, sana va vaqtni to'ldiring", "error")
        return redirect(url_for("portal.home", token=token, date=day or None))

    # end = start + dur
    try:
        st = datetime.strptime(f"{day} {start}", "%Y-%m-%d %H:%M")
    except ValueError:
        flash("⛔ Sana/vaqt formati xato", "error")
        return redirect(url_for("portal.home", token=token))
    if st <= now_tashkent():
        flash("⛔ O'tgan vaqtga bron qilib bo'lmaydi", "error")
        return redirect(url_for("portal.home", token=token, date=day))
    end = (st + timedelta(hours=dur)).strftime("%H:%M")

    # Ish vaqti chegarasi (studiya jadvali)
    from config import Config
    if not Booking.within_work_hours(start, end):
        flash(f"⛔ Studiya ish vaqti: {Config.WORK_START:02d}:00–"
              f"{Config.WORK_END:02d}:00. Shu oraliqda tanlang.", "error")
        return redirect(url_for("portal.home", token=token, date=day))

    if Booking.conflict(studio.id, day, start, end):
        flash(f"⛔ {start}–{end} band. Boshqa vaqt tanlang "
              f"(bandlik ro'yxati pastda).", "error")
        return redirect(url_for("portal.home", token=token, date=day))

    # Spam-bandlik cheklovi: juda ko'p faol kelgusi bron bo'lsa — bloklaymiz
    today = today_iso()
    active_upcoming = Booking.query.filter(
        Booking.teacher_id == t.id, Booking.status == "active",
        Booking.date >= today).count()
    if active_upcoming >= MAX_UPCOMING:
        flash(f"⛔ Sizда {MAX_UPCOMING} ta faol bron bor. Yangi bron uchun "
              f"avvalgilaridan birini yakunlang yoki studiyaga murojaat qiling.",
              "error")
        return redirect(url_for("portal.home", token=token, date=day))

    b = Booking(studio_id=studio.id, teacher_id=t.id, date=day,
                start=start, end=end, pay_type=pay_type,
                note=(f.get("note") or "").strip()[:300],
                created_by=f"portal:{t.name}")
    if pay_type == "package":
        if t.balance_hours() < b.hours:
            flash(f"⛔ Balans yetarli emas ({t.balance_hours():g} soat). "
                  f"Soatbay tanlang yoki studiyadan paket sotib oling.", "error")
            return redirect(url_for("portal.home", token=token, date=day))
    db.session.add(b)
    db.session.flush()
    if pay_type == "hourly":
        from models.pricing import booking_price
        pamount, pdisc, _rn, _bs = booking_price(studio, day, start, b.hours)
        db.session.add(Payment(
            teacher_id=t.id, booking_id=b.id, kind="hourly",
            amount=pamount, hours=0,
            date=day, is_paid=False,
            note=(f"{studio.name} · {day} {start}–{end} (portal)"
                  + (f" · −{pdisc}%" if pdisc else "")),
            created_by=f"portal:{t.name}"))
    from sqlalchemy.exc import IntegrityError
    try:
        db.session.commit()
    except IntegrityError:   # poyga: shu vaqt endigina band bo'ldi
        db.session.rollback()
        flash(f"⛔ {start}–{end} endigina band bo'ldi. Boshqa vaqt tanlang.",
              "error")
        return redirect(url_for("portal.home", token=token, date=day))

    try:
        from core.telegram import notify_teacher_booking
        notify_teacher_booking(b, studio, t, created=True)
    except Exception:
        pass
    flash(f"✅ Bron qabul qilindi: {studio.name} · {day} {start}–{end}", "success")
    return redirect(url_for("portal.home", token=token, date=day))


@bp.route("/my/<token>/cancel/<int:bid>", methods=["POST"])
def cancel(token, bid):
    t = _teacher_or_404(token)
    b = Booking.query.get_or_404(bid)
    if b.teacher_id != t.id or b.status != "active":
        abort(404)
    st = _starts_at(b)
    if not st or (st - now_tashkent()) < timedelta(hours=CANCEL_HOURS):
        flash(f"⛔ {CANCEL_HOURS} soatdan kam qoldi — bekor qilish uchun "
              f"studiyaga qo'ng'iroq qiling.", "error")
        return redirect(url_for("portal.home", token=token))
    b.status = "cancelled"
    # To'langan to'lovga tegmaymiz (haqiqiy pul); faqat kutilayotganini o'chiramiz
    Payment.query.filter_by(booking_id=b.id, is_paid=False).delete(
        synchronize_session=False)
    db.session.commit()
    flash("✅ Bron bekor qilindi" +
          (" — paket soatlaringiz qaytdi" if b.pay_type == "package" else ""),
          "success")
    return redirect(url_for("portal.home", token=token))


@bp.route("/my/<token>/reschedule/<int:bid>", methods=["POST"])
def reschedule(token, bid):
    """Mijoz o'zi bronni boshqa vaqtga ko'chiradi (kamida 24 soat oldin).

    Ish vaqti, konflikt va (paket bo'lsa) balans qayta tekshiriladi.
    To'lov turi va studiya o'zgarmaydi — faqat sana/vaqt."""
    from config import Config
    t = _teacher_or_404(token)
    b = Booking.query.get_or_404(bid)
    if b.teacher_id != t.id or b.status != "active":
        abort(404)
    st0 = _starts_at(b)
    if not st0 or (st0 - now_tashkent()) < timedelta(hours=CANCEL_HOURS):
        flash(f"⛔ {CANCEL_HOURS} soatdan kam qoldi — ko'chirish uchun "
              f"studiyaga qo'ng'iroq qiling.", "error")
        return redirect(url_for("portal.home", token=token))

    f = request.form
    day = (f.get("date") or b.date).strip()[:10]
    start = (f.get("start") or b.start).strip()[:5]
    studio = Studio.query.get(b.studio_id)
    try:
        dur = min(6.0, max(0.5, float(f.get("hours") or b.hours)))
    except (ValueError, TypeError):
        dur = b.hours
    try:
        new_st = datetime.strptime(f"{day} {start}", "%Y-%m-%d %H:%M")
    except ValueError:
        flash("⛔ Sana/vaqt formati xato", "error")
        return redirect(url_for("portal.home", token=token))
    if new_st <= now_tashkent():
        flash("⛔ O'tgan vaqtga ko'chirib bo'lmaydi", "error")
        return redirect(url_for("portal.home", token=token))
    end = (new_st + timedelta(hours=dur)).strftime("%H:%M")

    if not Booking.within_work_hours(start, end):
        flash(f"⛔ Studiya ish vaqti: {Config.WORK_START:02d}:00–"
              f"{Config.WORK_END:02d}:00.", "error")
        return redirect(url_for("portal.home", token=token))
    if Booking.conflict(studio.id, day, start, end, exclude_id=b.id):
        flash(f"⛔ {start}–{end} band. Boshqa vaqt tanlang.", "error")
        return redirect(url_for("portal.home", token=token))
    # Paket: balans qayta tekshiruvi (shu bronning eski soatini chiqarib)
    new_hours = dur
    if b.pay_type == "package":
        if t.balance_hours() + b.hours < new_hours:
            flash(f"⛔ Balans yetarli emas ({t.balance_hours():g} soat).", "error")
            return redirect(url_for("portal.home", token=token))

    old = f"{b.date} {b.start}"
    b.date, b.start, b.end, b.reminded = day, start, end, False
    if b.pay_type == "hourly":
        p = Payment.query.filter_by(booking_id=b.id, is_paid=False).first()
        if p:
            from models.pricing import booking_price
            p.amount, _rd, _rr, _rb = booking_price(
                studio, day, start, new_hours)
            p.date = day
            p.note = (f"{studio.name} · {day} {start}–{end} (portal ko'chirish)"
                      + (f" · −{_rd}%" if _rd else ""))
    db.session.commit()
    try:
        from core.telegram import notify_teacher_booking
        notify_teacher_booking(b, studio, t, created=False)
    except Exception:
        pass
    flash(f"✅ Bron ko'chirildi: {old} → {day} {start}", "success")
    return redirect(url_for("portal.home", token=token, date=day))
