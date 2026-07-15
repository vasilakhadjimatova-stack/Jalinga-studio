"""Ochiq online bron — mijoz o'zi band qiladi (login/parolsiz).

Havola hammaga ochiq: /book. Mijoz studiya + sana + vaqtni tanlaydi,
ism/telefon qoldiradi — bron avtomatik yaratiladi (soatbay), operator
kalendarда ko'radi. Spam-himoya: telefon bo'yicha faol bron chegarasi +
honeypot maydon. Konflikt/ish-vaqti/o'tgan-vaqt tekshiruvlari studiya
kalendari bilan bir xil.
"""
import time
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, jsonify)

from config import Config
from core.timeutils import now_tashkent, today_iso
from database import db
from models.studio import Studio, Booking
from models.billing import Teacher, Payment

bp = Blueprint("book", __name__)

MAX_UPCOMING = 5      # bitta telefon uchun faol kelgusi bron chegarasi
MAX_DAYS_AHEAD = 60   # necha kun oldin bron qilsa bo'ladi

# Spam himoyasi (login-siz ochiq endpoint): har IP soatiga cheklov + kunlik
# global cap. Har yangi telefon yangi Teacher yaratgani uchun (MAX_UPCOMING
# yordam bermaydi) — IP darajasida cheklaymiz. ProxyFix real IP beradi.
_IP_HITS = {}                 # ip -> [timestamp, ...]
_IP_WINDOW = 3600             # 1 soat
_IP_MAX = 8                   # bir IP soatiga 8 ta bron URINISHI (nafaqat muvaffaqiyat)
_DAILY = {"day": "", "n": 0}  # global kunlik hisoblagich
_DAILY_MAX = 300              # butun tizim uchun kuniga 300 bron urinishi
# ESLATMA: hisoblagichlar process xotirasida — gunicorn ko'p-worker'да har
# worker alohida sanaydi (haqiqiy chegara ×worker) va restartда nollanadi.
# To'liq mustahkam cheklov uchun umumiy do'kon (Redis/DB) kerak — keyingi bosqich.


def _spam_blocked(ip):
    from flask import current_app
    if current_app.config.get("TESTING"):
        return False   # testда global hisoblagich xalaqit bermasin
    now = time.time()
    hits = [t for t in _IP_HITS.get(ip, []) if now - t < _IP_WINDOW]
    _IP_HITS[ip] = hits
    if len(hits) >= _IP_MAX:
        return True
    today = today_iso()
    if _DAILY["day"] != today:
        _DAILY["day"], _DAILY["n"] = today, 0
    return _DAILY["n"] >= _DAILY_MAX


def _spam_note(ip):
    _IP_HITS.setdefault(ip, []).append(time.time())
    _DAILY["n"] = _DAILY.get("n", 0) + 1


def _min(hhmm):
    try:
        h, m = str(hhmm).split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return 0


def _digits(s):
    return "".join(c for c in (s or "") if c.isdigit())


def _find_teacher_by_phone(full):
    """Telefon (faqat raqamlar) bo'yicha mavjud mijozni topadi.

    To'liq mos yoki (ikkalasi milliy 9-raqamli) oxirgi 9 raqam mos — bitta
    odam. Aks holda None (yangi mijoz yaratiladi)."""
    if len(full) < 7:
        return None
    d9 = full[-9:]
    for ex in Teacher.query.filter_by(is_active=True).all():
        exf = _digits(ex.phone)
        if exf and (exf == full or
                    (len(exf) >= 9 and len(full) >= 9 and exf[-9:] == d9)):
            return ex
    return None


@bp.route("/book")
def index():
    """Ochiq bron sahifasi — studiyalar + sana tanlash."""
    studios = Studio.query.filter_by(is_active=True).order_by(
        Studio.sort.asc(), Studio.id.asc()).all()
    today = today_iso()
    max_date = (now_tashkent().date()
                + timedelta(days=MAX_DAYS_AHEAD)).strftime("%Y-%m-%d")
    return render_template(
        "book_public.html",
        studios=[s.to_dict() for s in studios],
        today=today, max_date=max_date,
        work_start=Config.WORK_START, work_end=Config.WORK_END,
        company=Config.COMPANY_NAME)


@bp.route("/book/slots")
def slots():
    """JSON: tanlangan studiya+sanada band oraliqlar (JS bo'sh slotni hisoblaydi)."""
    try:
        sid = int(request.args.get("studio_id") or 0)
    except (ValueError, TypeError):
        sid = 0
    day = (request.args.get("date") or "").strip()[:10]
    studio = Studio.query.get(sid) if sid else None
    if not (studio and studio.is_active and day):
        return jsonify({"ok": False, "busy": []})
    busy = []
    for b in Booking.query.filter(
            Booking.studio_id == sid, Booking.date == day,
            Booking.status.in_(("active", "done"))).all():
        busy.append([_min(b.start), _min(b.end)])
    busy.sort()
    from models.pricing import active_rules_for
    return jsonify({
        "ok": True, "busy": busy,
        "work_start": Config.WORK_START, "work_end": Config.WORK_END,
        "rate": studio.hourly_rate or 0,
        "rules": active_rules_for(sid)})


@bp.route("/book/submit", methods=["POST"])
def submit():
    f = request.form
    ip = request.remote_addr or "?"
    # Honeypot: bot to'ldiradigan yashirin maydon — to'lgan bo'lsa jim rad
    # (lekin urinishни hisoblaymiz — bot IP'sini chegaraga yaqinlashtiradi).
    if (f.get("website") or "").strip():
        _spam_note(ip)
        return redirect(url_for("book.done"))

    # Spam himoyasi: IP soatlik + global kunlik cheklov
    if _spam_blocked(ip):
        flash("⛔ Juda ko'p so'rov. Iltimos keyinroq urinib ko'ring yoki "
              "studiyaga qo'ng'iroq qiling.", "error")
        return redirect(url_for("book.index"))
    # HAR urinishни hisoblaymiz (muvaffaqiyatдан oldin) — probing/spam,
    # honeypot chetlab o'tilса ham, cheklovга kiradi. Aks holда faqat
    # muvaffaqiyatli bron sanalib, cheksiz urinish mumkin edi.
    _spam_note(ip)

    name = (f.get("name") or "").strip()[:200]
    phone = (f.get("phone") or "").strip()[:50]
    full = _digits(phone)
    try:
        studio = Studio.query.get(int(f.get("studio_id") or 0))
    except (ValueError, TypeError):
        studio = None
    day = (f.get("date") or "").strip()[:10]
    start = (f.get("start") or "").strip()[:5]
    try:
        dur = min(6.0, max(1.0, float(f.get("hours") or 1)))
    except (ValueError, TypeError):
        dur = 1.0

    def _back(msg):
        flash(msg, "error")
        return redirect(url_for("book.index"))

    if not name or len(full) < 7:
        return _back("⛔ Ism va to'g'ri telefon raqamini kiriting")
    if not (studio and studio.is_active and day and start):
        return _back("⛔ Studiya, sana va vaqtni tanlang")

    try:
        st = datetime.strptime(f"{day} {start}", "%Y-%m-%d %H:%M")
    except ValueError:
        return _back("⛔ Sana/vaqt formati xato")
    if st <= now_tashkent():
        return _back("⛔ O'tgan vaqtga bron qilib bo'lmaydi")
    if st.date() > (now_tashkent().date() + timedelta(days=MAX_DAYS_AHEAD)):
        return _back(f"⛔ {MAX_DAYS_AHEAD} kundan uzoqqa bron qilib bo'lmaydi")
    end = (st + timedelta(hours=dur)).strftime("%H:%M")

    if not Booking.within_work_hours(start, end):
        return _back(f"⛔ Ish vaqti {Config.WORK_START:02d}:00–"
                     f"{Config.WORK_END:02d}:00. Shu oraliqda tanlang.")
    # Poyga himoyasi: studiya qatorini qulflab konflikt-tekshiruv↔insert
    # oralig'ini serializatsiya qilamiz (ikki mijoz bir slotni bir vaqtда
    # olsa — biri rad etiladi). Postgres row-lock; SQLite yozuv-qulf.
    Studio.lock_for_booking(studio.id)
    if Booking.conflict(studio.id, day, start, end):
        return _back(f"⛔ {start}–{end} band bo'lib qoldi. Boshqa vaqt tanlang.")

    # Spam-himoya: telefon bo'yicha ochiq bronlar chegarasi
    today = today_iso()
    tphone = _find_teacher_by_phone(full)
    if tphone:
        active_upcoming = Booking.query.filter(
            Booking.teacher_id == tphone.id, Booking.status == "active",
            Booking.date >= today).count()
        if active_upcoming >= MAX_UPCOMING:
            return _back(f"⛔ Sizda {MAX_UPCOMING} ta faol bron bor. Yangisi "
                         f"uchun studiyaga qo'ng'iroq qiling.")
        t = tphone
    else:
        t = Teacher(name=name, phone=phone, created_by="online")
        t.ensure_token()
        db.session.add(t)
        db.session.flush()

    b = Booking(studio_id=studio.id, teacher_id=t.id, date=day,
                start=start, end=end, pay_type="hourly",
                note=(f.get("note") or "").strip()[:300],
                created_by=f"online:{name}")
    db.session.add(b)
    db.session.flush()
    from models.pricing import booking_price
    amount, disc, rule_name, _base = booking_price(studio, day, start, b.hours)
    note = f"{studio.name} · {day} {start}–{end} (online bron)"
    if disc:
        note += f" · −{disc}% {rule_name or ''}".rstrip()
    db.session.add(Payment(
        teacher_id=t.id, booking_id=b.id, kind="hourly",
        amount=amount, hours=0, date=day, is_paid=False,
        note=note, created_by="online"))
    from sqlalchemy.exc import IntegrityError
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _back(f"⛔ {start}–{end} endigina band bo'ldi. Boshqa vaqt tanlang.")

    _notify_staff(studio, t, b)
    return redirect(url_for("book.done", s=studio.id, d=day, t=start, e=end))


@bp.route("/book/done")
def done():
    """Bron qabul qilindi — minnatdorchilik sahifasi."""
    info = None
    sid = request.args.get("s")
    if sid:
        studio = Studio.query.get(sid) if str(sid).isdigit() else None
        info = {"studio": studio.name if studio else "",
                "date": request.args.get("d", ""),
                "start": request.args.get("t", ""),
                "end": request.args.get("e", "")}
    return render_template("book_done.html", info=info,
                           company=Config.COMPANY_NAME)


def _notify_staff(studio, teacher, b):
    """Yangi online bron haqida rahbar/buxgalterga Telegram xabar."""
    try:
        from core.telegram import tg_send, esc
        from models.user import User
        admins = User.query.filter(
            User.is_active.is_(True), User.tg_chat_id != "",
            User.role.in_(("admin", "operator"))).all()
        if not admins:
            return
        # Mijoz kiritgan ism/telefon — HTML parse_mode uchun escape (inject
        # yoki buzuq HTML tufayli xabar yo'qolmasin).
        text = (f"🆕 <b>Online bron</b>\n👤 {esc(teacher.name)} · "
                f"{esc(teacher.phone)}\n🎬 {esc(studio.name)}\n"
                f"📅 {b.date} · {b.start}–{b.end} ({b.hours:g} soat)")
        for u in admins:
            tg_send(u.tg_chat_id, text)
    except Exception:
        pass
