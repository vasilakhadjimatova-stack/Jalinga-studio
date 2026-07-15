"""Telegram bot — yengil (Impulse botining soddalashgani).

Vazifalari:
  • Ustozni ulash: portal havolasidagi "Telegram'ga ulash" tugmasi
    https://t.me/<bot>?start=<portal_token> ochadi → /start <token> keladi →
    Teacher.tg_chat_id saqlanadi.
  • Xabarlar: bron tasdig'i, dars oldidan ~2 soat qolganda eslatma,
    paket balansi tugayotganda ogohlantirish.

TELEGRAM_BOT_TOKEN env bo'lmasa — hammasi jim no-op (dastur ishlayveradi).
"""
import html
import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request

from database import db

logger = logging.getLogger(__name__)

TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip()
_API = f"https://api.telegram.org/bot{TOKEN}"


def is_configured():
    return bool(TOKEN)


def esc(s):
    """HTML parse_mode uchun foydalanuvchi matnini xavfsizlaydi (< > &).

    Online bron orqali mijoz kiritgan ism/telefon Telegram xabariga tushadi —
    escaping'siz <a href> kabi teg inject qilinishi yoki buzuq HTML tufayli
    xabar butunlay yuborilmay qolishi mumkin edi."""
    return html.escape(str(s or ""))


def tg_send(chat_id, text):
    """Xabar yuborish — xatoda jim (asosiy oqim to'xtamaydi)."""
    if not TOKEN or not chat_id:
        return False
    try:
        data = urllib.parse.urlencode({
            "chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(f"{_API}/sendMessage", data=data, timeout=10)
        return True
    except Exception as exc:
        logger.warning(f"tg_send xato: {exc}")
        return False


def notify_teacher_booking(b, studio, teacher, created=True):
    """Ustozga bron tasdig'i/o'zgarishi (TG ulangan bo'lsa)."""
    if not (teacher and teacher.tg_chat_id):
        return
    head = "✅ Yozuv tasdiqlandi" if created else "ℹ️ Yozuv yangilandi"
    pay = "📦 paket balansidan" if b.pay_type == "package" else "💵 soatbay"
    tg_send(teacher.tg_chat_id,
            f"<b>{head}</b>\n🎬 {esc(studio.name)}\n"
            f"📅 {b.date} · {b.start}–{b.end} ({b.hours:g} soat)\n{pay}")


_CHAT_HITS = {}   # chat_id -> [timestamp, ...] — per-chat throttle


def _chat_throttled(chat_id):
    """Bitta chat 1 daqiqada 10 tadan ko'p /start yuborsa — o'tkazib yuboramiz
    (token enumeratsiyasiga qarshi qo'shimcha to'siq)."""
    now = time.time()
    hits = [t for t in _CHAT_HITS.get(chat_id, []) if now - t < 60]
    hits.append(now)
    _CHAT_HITS[chat_id] = hits
    return len(hits) > 10


def _handle_update(app, upd):
    msg = upd.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = str((msg.get("chat") or {}).get("id") or "")
    if not chat_id:
        return
    if _chat_throttled(chat_id):
        return
    if text.startswith("/start"):
        token = text[6:].strip()
        if token:
            with app.app_context():
                from database import db
                from models.billing import Teacher
                from models.user import User
                t = Teacher.query.filter_by(portal_token=token).first()
                if t:
                    t.tg_chat_id = chat_id
                    db.session.commit()
                    tg_send(chat_id,
                            f"👋 Salom, <b>{esc(t.name)}</b>!\nJalinga Studio botiga "
                            f"ulandingiz. Endi bron tasdig'i va dars oldidan "
                            f"eslatmalar shu yerga keladi. 🎬")
                    return
                # Rahbar/xodim ALOHIDA tg_token bilan ulanadi (login kodi EMAS
                # — bot orqali login kodini brute-force qilishni oldini olish).
                # Token uzun bo'lsagina qidiramiz (login kodi 6 xonali).
                if len(token) >= 16:
                    u = User.query.filter_by(
                        tg_token=token, is_active=True).first()
                    if u and u.role in ("admin", "buxgalter"):
                        u.tg_chat_id = chat_id
                        db.session.commit()
                        tg_send(chat_id,
                                f"👋 Salom, <b>{esc(u.name)}</b>!\nRahbar sifatida "
                                f"ulandingiz. Endi har ertalab kunlik hisobot "
                                f"(digest) va e'tibor talab qiladigan ishlar "
                                f"shu yerga keladi. 📊")
                        return
        tg_send(chat_id, "👋 Jalinga Studio boti. Ulash uchun shaxsiy portal "
                         "havolangizdagi «Telegram'ga ulash» tugmasini bosing.")


def _poll_loop(app):
    offset = 0
    while True:
        try:
            with urllib.request.urlopen(
                    f"{_API}/getUpdates?timeout=25&offset={offset}",
                    timeout=35) as r:
                data = json.loads(r.read().decode())
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    _handle_update(app, upd)
                except Exception as exc:
                    logger.error(f"tg update xato: {exc}")
        except Exception:
            time.sleep(5)


def build_digest_text():
    """Rahbar uchun ertalabki kunlik hisobot matni (app_context ichida).

    E'tibor markazi (attention_items) + bugungi yozuvlar soni + shu oy tushumi.
    Bir joyda barcha muhim raqamlar — Telegram digest ham, kelajakda boshqa
    kanallar ham shu funksiyadan foydalanadi.
    """
    from sqlalchemy import func
    from core.timeutils import now_tashkent, today_iso, current_month_iso
    from models.studio import Booking
    from models.billing import Payment
    from modules.dashboard.attention import attention_items

    today = today_iso()
    month = current_month_iso()
    n_today = Booking.query.filter(
        Booking.date == today,
        Booking.status.in_(("active", "done"))).count()
    revenue = float(db.session.query(
        func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.date.like(month + "%"), Payment.is_paid.is_(True)).scalar() or 0)
    pending = float(db.session.query(
        func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.date.like(month + "%"), Payment.is_paid.is_(False)).scalar() or 0)

    def _som(x):
        return f"{x:,.0f}".replace(",", " ")

    lines = [
        f"📊 <b>Kunlik hisobot</b> · {now_tashkent().strftime('%d.%m.%Y')}",
        "",
        f"📅 Bugun yozuvlar: <b>{n_today}</b> ta",
        f"💵 Shu oy tushum: <b>{_som(revenue)}</b> so'm",
    ]
    if pending:
        lines.append(f"⏳ Kutilmoqda: {_som(pending)} so'm")

    items = attention_items()
    lines.append("")
    if items:
        icon = {"danger": "🔴", "warn": "🟡", "info": "🔵"}
        lines.append(f"<b>E'tibor talab qiladi ({len(items)}):</b>")
        for a in items:
            lines.append(
                f"{icon.get(a['level'], '•')} {a['title']} — "
                f"<b>{a['count']}</b> ({a['detail']})")
    else:
        lines.append("✅ E'tibor talab qiladigan ish yo'q — hammasi joyida!")

    return "\n".join(lines)


def _digest_loop(app, hour=9):
    """Har kuni belgilangan soatda (Toshkent) rahbarlarga digest yuboradi.

    Har 10 daqiqada tekshiradi; soat mos kelsa va bugun hali yuborilmagan
    bo'lsa — tg_chat_id ulagan admin/buxgalterlarga jo'natadi. Kunni eslab
    qoladi (takror yubormaydi).
    """
    from core.timeutils import now_tashkent
    last_sent_day = ""
    time.sleep(45)
    while True:
        try:
            now = now_tashkent()
            if now.hour == hour and now.strftime("%Y-%m-%d") != last_sent_day:
                with app.app_context():
                    from models.user import User
                    text = build_digest_text()
                    admins = User.query.filter(
                        User.is_active.is_(True),
                        User.tg_chat_id != "",
                        User.role.in_(("admin", "buxgalter"))).all()
                    for u in admins:
                        tg_send(u.tg_chat_id, text)
                last_sent_day = now.strftime("%Y-%m-%d")
        except Exception as exc:
            logger.error(f"tg digest xato: {exc}")
        time.sleep(600)


def _reminder_loop(app):
    """Har 5 daqiqada: 2 soat ichida boshlanadigan bronlarga eslatma."""
    from datetime import datetime, timedelta
    time.sleep(30)
    while True:
        try:
            with app.app_context():
                from database import db
                from models.studio import Booking, Studio
                from models.billing import Teacher
                from core.timeutils import now_tashkent
                now = now_tashkent()
                horizon = now + timedelta(hours=2)
                for b in Booking.query.filter(
                        Booking.status == "active",
                        Booking.reminded.is_(False),
                        Booking.date == now.strftime("%Y-%m-%d")).all():
                    try:
                        starts = datetime.strptime(
                            f"{b.date} {b.start}", "%Y-%m-%d %H:%M")
                    except ValueError:
                        continue
                    if now <= starts <= horizon:
                        t = Teacher.query.get(b.teacher_id)
                        s = Studio.query.get(b.studio_id)
                        if t and t.tg_chat_id:
                            left = int((starts - now).total_seconds() // 60)
                            tg_send(t.tg_chat_id,
                                    f"⏰ <b>Eslatma:</b> {left} daqiqadan so'ng "
                                    f"yozuv!\n🎬 {s.name if s else ''}\n"
                                    f"📅 {b.date} · {b.start}–{b.end}")
                        b.reminded = True
                db.session.commit()
        except Exception as exc:
            logger.error(f"tg eslatma xato: {exc}")
        time.sleep(300)


# Leader-lock: gunicorn bir necha worker ishga tushiradi. Bot polling/eslatma
# faqat BITTA workerда yurishi kerak (aks holda getUpdates poyga qiladi va
# eslatmalar takrorlanadi). OS fayl-qulfi bilan bitta «yetakchi» tanlanadi.
_LOCK_FH = None


def _acquire_leader():
    """Faqat birinchi worker True oladi (fayl-qulfi konteyner ichида umumiy)."""
    global _LOCK_FH
    try:
        import fcntl
        _LOCK_FH = open("/tmp/jalinga_bot.lock", "w")
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except Exception:
        return False


def start_bot(app):
    """Polling + eslatma threadlari (token bo'lsa, faqat yetakchi workerда)."""
    if not TOKEN:
        logger.info("Telegram bot o'chiq (TELEGRAM_BOT_TOKEN yo'q)")
        return
    if not _acquire_leader():
        logger.info("Telegram bot: bu worker yetakchi emas — o'tkazib yuborildi")
        return
    threading.Thread(target=_poll_loop, args=(app,), daemon=True,
                     name="jalinga-tg-poll").start()
    threading.Thread(target=_reminder_loop, args=(app,), daemon=True,
                     name="jalinga-tg-remind").start()
    threading.Thread(target=_digest_loop, args=(app,), daemon=True,
                     name="jalinga-tg-digest").start()
    logger.info("🤖 Telegram bot ishga tushdi (yetakchi worker)")


def bot_username():
    """Deep-link uchun bot nomi (kesh bilan)."""
    global _BOT_NAME
    try:
        return _BOT_NAME
    except NameError:
        pass
    if not TOKEN:
        return ""
    try:
        with urllib.request.urlopen(f"{_API}/getMe", timeout=10) as r:
            _BOT_NAME = json.loads(r.read().decode())["result"]["username"]
    except Exception:
        _BOT_NAME = ""
    return _BOT_NAME
