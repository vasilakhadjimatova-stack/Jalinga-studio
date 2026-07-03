"""Studiya to'lovlari ↔ moliya jurnali ko'prigi.

Mijoz to'lovi (Payment) tasdiqlanганда (is_paid=True) moliya jurnalida
avtomatik «Поступление от клиента (запись)» kirim tranzaksiyasi paydo bo'ladi;
to'lov «kutilmoqda»ga qaytsa yoki o'chirilsa — tranzaksiya ham yo'qoladi.

Shu tarzda studiya operatsiyalari va moliya bitta ДДС manzarasida birlashadi.
Idempotent: har chaqiruvда Payment holatiga qarab bog'langan tranzaksiya
yaratiladi / yangilanadi / o'chiriladi. Chaqiruvchi commit qiladi.
"""
import logging

from database import db
from models.finance import FinTransaction, FinWallet, FinCategory

logger = logging.getLogger(__name__)

# Studiya tushumi tushadigan ДДС statyasi (Справочники'да mavjud)
STUDIO_INCOME_CATEGORY = "Поступление от клиента (запись)"

# To'lov usuli → hisob (hamyon). Sheets'даги nomlar bilan bir xil.
METHOD_WALLET = {
    "naqd": "Наличные",
    "karta": "карта 9933",
    "o'tkazma": "РС Jalinga",
    "click/payme": "карта 9933",
}
DEFAULT_WALLET = "карта 9933"
# Bu usullar moliyaga tushmaydi (bepul/bonus paket — real pul kirmaydi)
SKIP_METHODS = {"bonus"}


def _resolve_wallet(method):
    name = METHOD_WALLET.get((method or "").strip(), DEFAULT_WALLET)
    if FinWallet.query.filter_by(name=name).first():
        return name
    w = FinWallet.query.order_by(FinWallet.sort).first()
    return w.name if w else name


def _should_book(payment):
    """To'lov moliyaga kirim yozishi kerakmi?"""
    return bool(payment.is_paid
                and (payment.amount or 0) > 0
                and (payment.method or "") not in SKIP_METHODS)


def sync_payment_to_finance(payment, teacher_name=None):
    """Payment holatiga qarab bog'langan moliya tranzaksiyasini moslaydi.

    Commit QILMAYDI — chaqiruvchi zimmasida. Category yo'q bo'lsa jim
    (moliya bazasi hali seed bo'lmagan bo'lishi mumkin) — o'tkazib yuboradi.
    """
    existing = FinTransaction.query.filter_by(
        payment_id=payment.id, source="studio").first()

    if not _should_book(payment):
        if existing:
            db.session.delete(existing)
        return None

    cat = FinCategory.query.filter_by(name=STUDIO_INCOME_CATEGORY).first()
    if cat is None:
        logger.warning("Studiya statyasi topilmadi (%s) — moliyaga "
                       "bog'lanmadi", STUDIO_INCOME_CATEGORY)
        return None

    date = (payment.date or "")[:10]
    if len(date) != 10:
        return None
    wallet = _resolve_wallet(payment.method)
    who = (teacher_name or "").strip()
    kind_label = "paket" if payment.kind == "package" else "soatbay"
    purpose = f"Studiya to'lovi ({kind_label})"
    if payment.note:
        purpose = f"{purpose} — {payment.note}"

    if existing is None:
        existing = FinTransaction(payment_id=payment.id, source="studio")
        db.session.add(existing)
    existing.date = date
    existing.year = int(date[:4])
    existing.month = int(date[5:7])
    existing.amount = float(payment.amount or 0)
    existing.wallet = wallet
    existing.counterparty = who[:200]
    existing.purpose = purpose[:400]
    existing.category = cat.name
    existing.direction = cat.direction     # in
    existing.activity = cat.activity       # operating
    return existing


def unlink_payment_finance(payment_id):
    """Payment o'chirilganда bog'langan moliya yozuvини ham olib tashlaydi.
    Commit QILMAYDI."""
    FinTransaction.query.filter_by(
        payment_id=payment_id, source="studio").delete()
