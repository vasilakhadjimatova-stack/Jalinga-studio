"""Avtopilot — kuniga bir marta ishlaydigan fon ishlari.

Bot tokeniga bog'liq EMAS (vazifalar va so'rovnomalar dastur ichida ham
ishlaydi). Har ish alohida himoyalangan: bittasi yiqilsa qolganlari
bajarilaveradi.

  • so'rovnomalar  — yaqinda «Yozildi» bo'lgan bronlarni tutib qolish
  • retention      — paket/uxlagan mijoz/follow-up → operatorga vazifa
  • zaxira nusxa   — rahbarning Telegram'iga gzip JSON (off-site)
  • tozalash       — eski tugagan vazifa va o'qilgan bildirishnomalar

Kuniga bir marta kafolati BAZADA saqlanadi (restart/deploy'дан keyin
qayta yugurmaydi). Gunicorn ko'p worker'ида faqat bitta yetakchi yuradi.
"""
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# Toshkent vaqti bilan shu soatdan keyin (kechagi kun to'liq yakunlangan,
# ish kuni boshlanishidan oldin vazifalar taxtada tayyor turadi).
try:
    AUTOPILOT_HOUR = min(23, max(0, int(os.environ.get("AUTOPILOT_HOUR", "7"))))
except ValueError:
    AUTOPILOT_HOUR = 7
_MARK = "autopilot:last_day"


def run_daily():
    """Barcha kunlik ishlar (app_context ichida). Natija — hisobot dict."""
    report = {}

    def _job(name, fn):
        try:
            report[name] = fn()
        except Exception as exc:
            from database import db
            db.session.rollback()
            report[name] = f"xato: {exc}"
            logger.exception(f"avtopilot: {name} yiqildi")

    from core.feedback import trigger_recent_surveys
    from core.retention import run_retention
    from core.backup import send_backup_telegram
    from core.comms import prune_old_tasks, prune_old_notifications

    _job("surveys", trigger_recent_surveys)
    _job("retention", run_retention)
    if (os.environ.get("BACKUP_TELEGRAM", "1") or "1").strip() != "0":
        _job("backup", send_backup_telegram)
    _job("prune", lambda: (prune_old_tasks(60), prune_old_notifications(90)))
    logger.info(f"🤖 avtopilot: {report}")
    return report


def _due_today():
    """Bugun hali yurmaganmi va soat yetdimi. Yursa — belgini qo'yadi."""
    from core.timeutils import now_tashkent
    from database import db
    from models.finance import FinSetting
    now = now_tashkent()
    day = now.strftime("%Y-%m-%d")
    if now.hour < AUTOPILOT_HOUR or FinSetting.get(_MARK, "") == day:
        return False
    FinSetting.set(_MARK, day)
    db.session.commit()
    return True


def _loop(app):
    time.sleep(60)
    while True:
        try:
            with app.app_context():
                if _due_today():
                    run_daily()
        except Exception as exc:
            logger.error(f"avtopilot sikl xato: {exc}")
        time.sleep(600)


_LOCK_FH = None


def start_autopilot(app):
    """Fon thread (faqat bitta yetakchi gunicorn worker'да)."""
    global _LOCK_FH
    try:
        import fcntl
        _LOCK_FH = open("/tmp/jalinga_autopilot.lock", "w")
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except Exception:
        logger.info("avtopilot: bu worker yetakchi emas — o'tkazib yuborildi")
        return
    threading.Thread(target=_loop, args=(app,), daemon=True,
                     name="jalinga-autopilot").start()
    logger.info(f"🤖 avtopilot ishga tushdi (har kuni {AUTOPILOT_HOUR:02d}:00 dan keyin)")
