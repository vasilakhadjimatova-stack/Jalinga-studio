"""Vaqtga bog'liq narx qoidalari — bo'sh soatlarni chegirma bilan to'ldirish.

Fikr: eng band («peak») soatlar to'liq narx, tinch («off-peak») soatlar
chegirma bilan — shunда mijoz arzon vaqtga siljiydi, studiya bo'sh turmaydi.

Qoida bronning BOSHLANISH soatiga qarab qo'llanadi (oddiy va oldindan
tushunarli). Bir nechta qoida mos kelsa — eng KATTA chegirma olinadi.
Faqat SOATBAY (hourly) bronlarga ta'sir qiladi; paket balansiga tegmaydi.
"""
from datetime import datetime

from database import db

WEEKDAYS_UZ = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]


class PriceRule(db.Model):
    __tablename__ = "price_rules"
    id         = db.Column(db.Integer, primary_key=True)
    # Qaysi studiya uchun — bo'sh (0/None) bo'lsa BARCHA studiyalarga
    studio_id  = db.Column(db.Integer, index=True)
    name       = db.Column(db.String(80), nullable=False, default="Chegirma")
    # Hafta kunlari: "0,1,2" (Du–Ch); bo'sh bo'lsa — har kuni
    days       = db.Column(db.String(20), default="")
    start_hour = db.Column(db.Integer, nullable=False, default=9)   # 9 → 09:00
    end_hour   = db.Column(db.Integer, nullable=False, default=14)  # 14 → 14:00
    discount   = db.Column(db.Integer, nullable=False, default=0)   # foiz 0..90
    is_active  = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def day_list(self):
        out = []
        for p in (self.days or "").split(","):
            p = p.strip()
            if p.isdigit() and 0 <= int(p) <= 6:
                out.append(int(p))
        return out

    def days_label(self):
        dl = self.day_list()
        if not dl:
            return "Har kuni"
        return ", ".join(WEEKDAYS_UZ[d] for d in sorted(dl))

    def to_dict(self):
        return {"id": self.id, "studio_id": self.studio_id or 0,
                "name": self.name, "days": self.days or "",
                "start_hour": self.start_hour, "end_hour": self.end_hour,
                "discount": self.discount, "is_active": self.is_active}


def _hh(start):
    try:
        return int(str(start).split(":")[0])
    except (ValueError, AttributeError, IndexError):
        return -1


def best_discount(studio_id, date, start):
    """Shu studiya+sana+boshlanish-soati uchun eng katta chegirma (%).

    Qaytaradi: (discount_pct:int, rule_name:str|None).
    """
    hh = _hh(start)
    if hh < 0:
        return 0, None
    try:
        wd = datetime.strptime(date, "%Y-%m-%d").weekday()
    except (ValueError, TypeError):
        wd = -1
    best, name = 0, None
    for r in PriceRule.query.filter_by(is_active=True).all():
        if r.studio_id and r.studio_id != studio_id:
            continue
        dl = r.day_list()
        if dl and wd not in dl:
            continue
        if not (r.start_hour <= hh < r.end_hour):
            continue
        d = max(0, min(90, r.discount or 0))
        if d > best:
            best, name = d, r.name
    return best, name


def booking_price(studio, date, start, hours, manual=0):
    """Soatbay bron narxi (chegirma qo'llangan).

    manual — operator qo'lda kiritган chegirma (%). Vaqt qoidasi bilan
    solishtirilib KATTAROG'I olinadi (va'da qilingan off-peak chegirma
    yo'qolmaydi, operator esa kerak bo'lsa ko'proq bera oladi).
    Qaytaradi: (amount:int, discount_pct:int, rule_name:str|None, base:int).
    """
    rate = (studio.hourly_rate or 0) if studio else 0
    base = round(hours * rate)
    auto, name = best_discount(studio.id if studio else 0, date, start)
    try:
        manual = max(0, min(90, int(manual or 0)))
    except (ValueError, TypeError):
        manual = 0
    if manual >= auto:
        disc, name = manual, ("Qo'lda" if manual > auto else (name or "Qo'lda"))
    else:
        disc = auto
    amount = round(base * (1 - disc / 100.0))
    return amount, disc, name, base


def active_rules_for(studio_id):
    """Studiyaga tegishli faol qoidalar (JS/online sahifa uchun)."""
    out = []
    for r in PriceRule.query.filter_by(is_active=True).order_by(
            PriceRule.start_hour.asc()).all():
        if r.studio_id and r.studio_id != studio_id:
            continue
        out.append({"days": r.day_list(), "start_hour": r.start_hour,
                    "end_hour": r.end_hour, "discount": r.discount,
                    "name": r.name})
    return out
