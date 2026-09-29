"""Oy yopish (davr qulfi) — yopilgan oy moliyasi o'zgarmaydi.

Impulse ERP'dagi period_lock g'oyasi Jalinga moliyasiga moslashtirilgan.
Buxgalteriyaning asosiy qoidasi: hisobot topshirilgan (yopilgan) davr
raqamlari keyin «jimgina» o'zgarib qolmasligi kerak.

Qoida:
  • Rahbar «shu oygacha yopish» qiladi → FinSetting('closed_through') = YYYY-MM.
    Shu oy va undan oldingi hamma oylar yopiq.
  • Yopiq oydagi tranzaksiyani qo'shish/tahrirlash/o'chirish — rad etiladi.
  • Avtomatik yozuvlar (studiya to'lovi tasdig'i, to'lov kalendari) sanasi
    yopiq oyga tushsa — PUL bugungi kunga yoziladi (to'lov o'zi eski oyniki
    bo'lishi mumkin — bu qonuniy, faqat kassa harakati bugun).
  • Yopiq oydagi bog'langan yozuvga tayanuvchi amallar (to'lovni
    «kutilmoqda»ga qaytarish, o'chirish) — rad etiladi.
Qayta ochish faqat rahbar va audit-logga yoziladi.
"""
from core.timeutils import today_iso

KEY = "closed_through"


def closed_through():
    """Oxirgi yopiq oy (YYYY-MM) yoki ''."""
    try:
        from models.finance import FinSetting
        v = (FinSetting.get(KEY, "") or "").strip()
    except Exception:
        return ""
    return v if len(v) == 7 and v[4] == "-" else ""


def is_locked(value):
    """value — ISO sana (YYYY-MM-DD) yoki oy (YYYY-MM). Yopiq oydami?"""
    ym = (value or "")[:7]
    ct = closed_through()
    return bool(ct and len(ym) == 7 and ym <= ct)


def locked_msg(value):
    return (f"🔒 {(value or '')[:7]} oyi yopilgan — bu davr moliyasi "
            f"o'zgartirilmaydi. Tuzatishni joriy oyda alohida yozuv "
            f"bilan kiriting (yoki rahbar oyni qayta ochadi).")


def shift_if_locked(iso_date):
    """Avto-yozuv sanasi: yopiq oyga tushsa — bugun. (sana, surildimi)."""
    if is_locked(iso_date):
        return today_iso(), True
    return iso_date, False
