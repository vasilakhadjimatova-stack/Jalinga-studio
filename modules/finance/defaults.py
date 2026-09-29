"""Moliya — boshlang'ich ma'lumot (hisoblar, ДДС statyalari, doimiy to'lovlar).

Moliya to'liq dastur ichida yuritiladi. Bu modul faqat BO'SH bazada bir marta
ishlaydi: tranzaksiya qo'shish uchun kerakli hisob va statyalarni yaratadi.
Keyin hammasi «Moliya → Sozlamalar»dan boshqariladi.
"""
import logging
from datetime import datetime

from database import db
from models.finance import (FinWallet, FinCategory, FinRecurring,
                            FinTransaction)

logger = logging.getLogger(__name__)

ACTIVITY_LABELS = {
    "operating": "Operatsion faoliyat",
    "investing": "Investitsion faoliyat",
    "financing": "Moliyaviy faoliyat",
    "technical": "Texnik (hisoblar aro o'tkazma)",
}


# Yangi o'rnatmada boshlang'ich seed — hisoblar va ДДС statyalari. Shusiz foydalanuvchi tranzaksiya qo'sha olmaydi
# (statya kerak). Admin keyin Sozlamalarда o'zgartiradi.
# Nomlar studiya-ulash (studio_link.METHOD_WALLET) bilan mos — mijoz to'lovi
# to'g'ri hisobga tushishi uchun.
DEFAULT_WALLETS = [
    ("РС Jalinga", "UZS"), ("карта 9933", "UZS"), ("Наличные", "UZS"),
    ("$", "USD"),
]
DEFAULT_CATEGORIES = [
    ("Поступление от клиента (запись)", "in", "operating"),
    ("Поступление от клиента (Вебинар)", "in", "operating"),
    ("Поступление от монтажа", "in", "operating"),
    ("Прочие поступления", "in", "operating"),
    ("зарплата", "out", "operating"),
    ("премия", "out", "operating"),
    ("аренда", "out", "operating"),
    ("аренда студии", "out", "operating"),
    ("налог АОС/дивиденд/Зп", "out", "operating"),
    ("Комиссия Банк/ комиссия плат. систем", "out", "operating"),
    ("Комунальные услуги", "out", "operating"),
    ("Ремонт", "out", "operating"),
    ("Абонентские подписки", "out", "operating"),
    ("организационные расходы", "out", "operating"),
    ("прочие расходы", "out", "operating"),
    ("Продажа ОС", "in", "investing"),
    ("Покупка ОС", "out", "investing"),
    ("Займ от собственника", "in", "financing"),
    ("Погашение тела кредита, займа", "out", "financing"),
    ("Дивиденды", "out", "financing"),
    ("Доход — Перевод между счетами", "in", "technical"),
    ("Расход — Перевод между счетами", "out", "technical"),
]


def seed_default_finance():
    """Bo'sh bazada boshlang'ich hisoblar + statyalar."""
    # Jurnal allaqachon yuritilayotgan bo'lsa — foydalanuvchi sozlamasiga
    # tegmaymiz (ataylab o'chirilgan statya qayta paydo bo'lmasin).
    if FinTransaction.query.first() is not None:
        return
    if FinCategory.query.first() is None:
        for i, (name, d, act) in enumerate(DEFAULT_CATEGORIES):
            db.session.add(FinCategory(name=name, direction=d, activity=act,
                                       sort=i))
    if FinWallet.query.first() is None:
        for i, (name, cur) in enumerate(DEFAULT_WALLETS):
            db.session.add(FinWallet(name=name, currency=cur, sort=i,
                                     opening_year=datetime.now().year))
    db.session.commit()
    logger.info("Moliya: boshlang'ich hisoblar va statyalar seed qilindi")


def seed_default_recurring():
    """Kalendar bo'sh bo'lmasin: Jalinga'ning ma'lum oylik to'lovlari
    (jadval tarixidan olingan tipik qiymatlar). Faqat hech qanday doimiy
    to'lov bo'lmaganда bir marta seed qilinadi — admin keyin tahrirlaydi."""
    if FinRecurring.query.first() is not None:
        return
    defaults = [
        ("Ofis ijarasi", 6100000, 2, "аренда"),
        ("Abonent obunalar", 800000, 1, "Абонентские подписки"),
    ]
    for i, (name, amount, day, cat) in enumerate(defaults):
        db.session.add(FinRecurring(name=name, amount=amount, pay_day=day,
                                    category=cat, wallet="РС Jalinga", sort=i))
    db.session.commit()
    logger.info("Kalendar: %d ta doimiy to'lov seed qilindi", len(defaults))


def ensure_finance_seed():
    """Startда chaqiriladi — idempotent (to'la bazaga tegmaydi)."""
    seed_default_finance()
    seed_default_recurring()
