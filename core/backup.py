"""Zaxira nusxa — butun baza JSON'ga (qo'lda yuklab olish + kunlik avto).

Impulse ERP'dagi «kunlik off-site zaxira» g'oyasi: har kuni avtopilot
bazani gzip'langan JSON qilib, Telegram ulagan RAHBARLARGA fayl sifatida
yuboradi. Railway'да falokat bo'lsa ham oxirgi kunlik nusxa Telegram'да
qoladi — hech kimning kompyuteri yoqiq bo'lishi shart emas.

Format — /team/backup.json bilan bir xil (format: 1), ya'ni qo'lda va
avtomatik zaxira bir xil usulda tiklanadi.
"""
import gzip
import json
import logging
from datetime import date, datetime

from database import db

logger = logging.getLogger(__name__)


def _val(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def build_backup():
    """Barcha ro'yxatga olingan jadvallar → dict (generic, model qo'shilsa
    avtomatik kiradi). Qaytaradi: (dump, jami_qatorlar)."""
    dump = {"_meta": {"app": "Jalinga Studio",
                      "exported_at": datetime.utcnow().isoformat() + "Z",
                      "format": 1}}
    total = 0
    for table in db.metadata.sorted_tables:
        rows = db.session.execute(table.select()).mappings().all()
        dump[table.name] = [{k: _val(v) for k, v in r.items()} for r in rows]
        total += len(rows)
    return dump, total


def backup_json_bytes():
    dump, total = build_backup()
    return json.dumps(dump, ensure_ascii=False, indent=1).encode("utf-8"), total


def send_backup_telegram():
    """Gzip'langan zaxirani Telegram ulagan faol rahbarlarga yuboradi.
    Qaytaradi: nechta rahbarga yetdi (bot o'chiq bo'lsa 0)."""
    from core.telegram import is_configured, tg_send_document
    from core.timeutils import now_tashkent
    from models.user import User
    if not is_configured():
        return 0
    admins = User.query.filter(User.is_active.is_(True), User.role == "admin",
                               User.tg_chat_id != "").all()
    if not admins:
        return 0
    raw, total = backup_json_bytes()
    gz = gzip.compress(raw, compresslevel=6)
    now = now_tashkent()
    fname = f"jalinga-backup-{now.strftime('%Y%m%d-%H%M')}.json.gz"
    caption = (f"💾 <b>Kunlik zaxira</b> · {now.strftime('%d.%m.%Y %H:%M')}\n"
               f"{total} ta yozuv · {len(gz) / 1024:.0f} KB\n"
               f"Faylni saqlab qo'ying — falokatда baza shundan tiklanadi.")
    n = 0
    for u in admins:
        if tg_send_document(u.tg_chat_id, fname, gz, caption,
                            content_type="application/gzip"):
            n += 1
    logger.info(f"💾 kunlik zaxira: {total} yozuv, {n} rahbarga yuborildi")
    return n
