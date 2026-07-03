"""Moliya ERP modellari — Google Sheets («Jalinga 2026») jurnal asosida.

Manba: ДДС данные (tranzaksiyalar jurnali), Справочники (statyalar),
Касса (hisoblar ochilish qoldig'i), DOLG (qarzlar).

Pul: hamma summa SO'Mda saqlanadi (float — Sheets bilan 1:1 mos bo'lishi
uchun; hisobotlarda yaxlitlanadi). "$" hamyoni ham so'm ekvivalentida
yuritiladi (Sheets'dagi ДДС shunday).
"""
from database import db


class FinWallet(db.Model):
    """Hisob/hamyon — РС Jalinga, karta, naqd, $."""
    __tablename__ = "fin_wallets"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    # Yil boshidagi ochilish qoldig'i (so'm) — balans = opening + kirim - chiqim
    opening_balance = db.Column(db.Float, default=0.0)
    opening_year = db.Column(db.Integer, default=2026)
    currency = db.Column(db.String(8), default="UZS")   # UZS | USD (ma'lumot uchun)
    is_active = db.Column(db.Boolean, default=True)
    sort = db.Column(db.Integer, default=0)


class FinCategory(db.Model):
    """ДДС statyasi — Справочники varag'idan."""
    __tablename__ = "fin_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    direction = db.Column(db.String(8), nullable=False)   # in | out
    activity = db.Column(db.String(16), nullable=False)   # operating|investing|financing|technical
    sort = db.Column(db.Integer, default=0)


class FinTransaction(db.Model):
    """Pul harakati — jurnal qatori (Sheets'dan sinxron yoki qo'lda)."""
    __tablename__ = "fin_transactions"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False, index=True)   # YYYY-MM-DD
    year = db.Column(db.Integer, nullable=False, index=True)
    month = db.Column(db.Integer, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    wallet = db.Column(db.String(120), nullable=False, index=True)
    counterparty = db.Column(db.String(200), default="")
    purpose = db.Column(db.String(400), default="")       # naznacheniye/izoh
    subcategory = db.Column(db.String(200), default="")   # dop.statya
    category = db.Column(db.String(200), nullable=False, index=True)
    direction = db.Column(db.String(8), nullable=False)   # in | out
    activity = db.Column(db.String(16), nullable=False)   # operating|investing|financing|technical
    source = db.Column(db.String(16), default="manual")   # sheet|manual|studio|plan|recurring
    # source='studio' bo'lsa — bog'langan studiya to'lovi (Payment.id).
    # Shu to'lov tasdiqlanганда avto-yaraladi, bekor/o'chirilganда yo'qoladi.
    payment_id = db.Column(db.Integer, index=True)
    # To'lov kalendaridan yaratilgan yozuvlar uchun bog'lamalar
    plan_id = db.Column(db.Integer, index=True)        # FinPlan.id
    recurring_id = db.Column(db.Integer, index=True)   # FinRecurring.id

    @property
    def signed(self):
        return self.amount if self.direction == "in" else -self.amount

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class FinDebt(db.Model):
    """Qarz daftari — DOLG varag'i."""
    __tablename__ = "fin_debts"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(24), default="")           # sana (ba'zan matn)
    debtor = db.Column(db.String(120), default="")        # kim qarz berdi (Jalinga)
    creditor = db.Column(db.String(120), default="")      # kimga berildi
    reason = db.Column(db.String(500), default="")
    amount = db.Column(db.Float, default=0.0)
    repaid = db.Column(db.Float, default=0.0)
    repaid_date = db.Column(db.String(24), default="")
    source = db.Column(db.String(16), default="manual")   # sheet | manual

    @property
    def remainder(self):
        return round((self.amount or 0) - (self.repaid or 0), 2)


class FinRecurring(db.Model):
    """Doimiy oylik to'lov (ijara, obunalar…) — to'lov kalendari uchun."""
    __tablename__ = "fin_recurring"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, default=0.0)          # so'm
    pay_day = db.Column(db.Integer, default=1)         # oyning kuni (1–31)
    category = db.Column(db.String(200), default="")   # ДДС statyasi
    wallet = db.Column(db.String(120), default="")     # odatdagi hisob
    is_active = db.Column(db.Boolean, default=True)
    sort = db.Column(db.Integer, default=0)


class FinPlan(db.Model):
    """Rejalashtirilgan bir martalik to'lov/tushum — kalendarda ko'rinadi."""
    __tablename__ = "fin_plans"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False, index=True)   # YYYY-MM-DD
    description = db.Column(db.String(300), default="")
    amount = db.Column(db.Float, default=0.0)
    direction = db.Column(db.String(8), default="out")            # in | out
    category = db.Column(db.String(200), default="")
    wallet = db.Column(db.String(120), default="")
    is_paid = db.Column(db.Boolean, default=False)


class FinSetting(db.Model):
    """Kalit-qiymat: last_sync va h.k."""
    __tablename__ = "fin_settings"
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(400), default="")

    @staticmethod
    def get(key, default=""):
        row = FinSetting.query.get(key)
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = FinSetting.query.get(key)
        if row is None:
            row = FinSetting(key=key)
            db.session.add(row)
        row.value = str(value)
