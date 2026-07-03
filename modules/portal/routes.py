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
        db.session.add(Payment(
            teacher_id=t.id, booking_id=b.id, kind="hourly",
            amount=round(b.hours * (studio.hourly_rate or 0)), hours=0,
            date=day, is_paid=False,
            note=f"{studio.name} · {day} {start}–{end} (portal)",
            created_by=f"portal:{t.name}"))
    db.session.commit()

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
    Payment.query.filter_by(booking_id=b.id, is_paid=False).delete(
        synchronize_session=False)
    db.session.commit()
    flash("✅ Bron bekor qilindi" +
          (" — paket soatlaringiz qaytdi" if b.pay_type == "package" else ""),
          "success")
    return redirect(url_for("portal.home", token=token))
