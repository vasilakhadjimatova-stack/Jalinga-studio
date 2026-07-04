"""Moliya ERP — snapshot import, ДДС hisoboti, jurnal CRUD, sahifalar."""
import pytest

from database import db
from models.finance import FinTransaction, FinWallet, FinCategory


@pytest.fixture(autouse=True)
def _ctx(app):
    with app.app_context():
        yield


def test_snapshot_imported(app):
    """App startida repo'dagi Sheets snapshoti yuklanadi."""
    assert FinTransaction.query.count() >= 200
    assert FinWallet.query.count() >= 5
    assert FinCategory.query.count() >= 30
    # Sheet yozuvlari sheet manbali
    assert FinTransaction.query.filter_by(source="sheet").count() >= 200


def test_dds_matches_google_sheet(app):
    """ДДС hisoboti Sheets'dagi ДДС_2026 bilan 1:1 mos kelishi shart."""
    from modules.finance.routes import build_dds
    r = build_dds(2026)
    assert r["opening"][1] == pytest.approx(39509626.20, abs=0.02)
    assert r["closing"][1] == pytest.approx(44080957.39, abs=0.02)
    assert r["closing"][2] == pytest.approx(121797855.23, abs=0.02)
    ops = r["sections"][0]
    assert ops["key"] == "operating"
    assert ops["in"][1] == pytest.approx(50150000.00, abs=0.02)
    assert ops["out"][3] == pytest.approx(97480419.47, abs=0.02)
    # Moliyaviy faoliyat: yanvar dividend 10 mln chiqim
    fin = r["sections"][2]
    assert fin["out"][1] == pytest.approx(10000000.00, abs=0.02)


def test_wallet_balances(app):
    """Sheets manbali balans = ochilish + Sheets harakatlari; iyun oxiri
    qoldig'iga teng. (Studiya/qo'lda yozuvlar alohida — bu yerda hisobga
    olinmaydi, chunki test bazasi boshqa testlar bilan bo'lishiladi.)"""
    opening = sum(w.opening_balance or 0 for w in FinWallet.query.all())
    flow = sum(t.signed for t in
               FinTransaction.query.filter_by(source="sheet").all())
    # ДДС_2026 iyun: Чистый денежный поток = 19 162 414.52
    assert opening + flow == pytest.approx(19162414.52, abs=0.05)


def test_finance_pages_load(admin_client):
    for url in ("/finance", "/finance/transactions", "/finance/dds",
                "/finance/debts", "/finance/dividends", "/finance/payments"):
        r = admin_client.get(url)
        assert r.status_code == 200, url


def test_txn_add_and_delete(admin_client, post):
    cat = FinCategory.query.filter_by(direction="out",
                                      activity="operating").first()
    wallet = FinWallet.query.first()
    r = post(admin_client, "/finance/transactions/add",
             date="2026-06-15", amount="125000", wallet=wallet.name,
             category=cat.name, purpose="pytest xarajat")
    assert r.status_code in (302, 303)
    t = FinTransaction.query.filter_by(purpose="pytest xarajat").first()
    assert t is not None and t.source == "manual"
    assert t.direction == "out" and t.activity == "operating"
    # o'chirish
    post(admin_client, f"/finance/transactions/{t.id}/delete")
    assert FinTransaction.query.filter_by(purpose="pytest xarajat").first() is None


def test_sheet_txn_delete_blocked(admin_client, post):
    """Sheets'dan kelgan yozuv o'chirilmaydi — sync'da baribir qaytadi."""
    t = FinTransaction.query.filter_by(source="sheet").first()
    post(admin_client, f"/finance/transactions/{t.id}/delete")
    assert FinTransaction.query.get(t.id) is not None


def test_txn_add_validation(admin_client, post):
    """Noto'g'ri forma yozuv yaratmasligi kerak."""
    before = FinTransaction.query.count()
    post(admin_client, "/finance/transactions/add",
         date="2026-06-15", amount="-5",
         wallet="yo'q hamyon", category="yo'q statya")
    assert FinTransaction.query.count() == before


def test_txn_add_admin_only(client, post):
    """Anonim/operator qo'sha olmaydi."""
    r = client.post("/finance/transactions/add", data={"_csrf": "x"})
    assert r.status_code in (302, 303, 403)
    assert FinTransaction.query.filter_by(purpose="hack").first() is None


# ── Studiya to'lovi → moliya jurnaliga avto-ulash ──

def test_studio_payment_links_to_finance(app, admin_client, post):
    """To'lov tasdiqlanганда moliyaga kirim tushadi, bekor bo'lsa yo'qoladi."""
    from models.billing import Teacher, Payment
    t = Teacher(name="Moliya Test Mijoz")
    db.session.add(t)
    db.session.commit()
    p = Payment(teacher_id=t.id, kind="hourly", amount=333000, hours=0,
                method="karta", date="2026-06-20", is_paid=False)
    db.session.add(p)
    db.session.commit()
    pid = p.id

    # Kutilmoqda holatда — moliyaда yozuv yo'q
    assert FinTransaction.query.filter_by(payment_id=pid).first() is None

    # Tasdiqlash → kirim paydo bo'ladi
    post(admin_client, f"/finance/{pid}/toggle")
    ft = FinTransaction.query.filter_by(payment_id=pid, source="studio").first()
    assert ft is not None
    assert ft.direction == "in" and ft.activity == "operating"
    assert ft.amount == pytest.approx(333000)
    assert ft.wallet == "карта 9933"        # karta usuli → shu hisob
    assert ft.counterparty == "Moliya Test Mijoz"

    # Kutilmoqdaга qaytarish → moliyadan o'chadi
    post(admin_client, f"/finance/{pid}/toggle")
    assert FinTransaction.query.filter_by(payment_id=pid).first() is None


def test_studio_payment_delete_unlinks_finance(app, admin_client, post):
    from models.billing import Teacher, Payment
    from modules.finance.studio_link import sync_payment_to_finance
    t = Teacher(name="O'chirish Mijoz")
    db.session.add(t)
    db.session.commit()
    p = Payment(teacher_id=t.id, kind="package", amount=500000, hours=10,
                method="naqd", date="2026-06-21", is_paid=True)
    db.session.add(p)
    db.session.commit()
    sync_payment_to_finance(p, teacher_name=t.name)
    db.session.commit()
    pid = p.id
    assert FinTransaction.query.filter_by(payment_id=pid).first() is not None
    assert (FinTransaction.query.filter_by(payment_id=pid).first().wallet
            == "Наличные")   # naqd → naqd hisob
    # To'lovни o'chirish → moliya yozuvи ham ketadi
    post(admin_client, f"/finance/{pid}/delete")
    assert FinTransaction.query.filter_by(payment_id=pid).first() is None


def test_bonus_package_not_booked(app):
    """Bonus (bepul) paket moliyaga tushmaydi — real pul kirmaydi."""
    from models.billing import Teacher, Payment
    from modules.finance.studio_link import sync_payment_to_finance
    t = Teacher(name="Bonus Mijoz")
    db.session.add(t)
    db.session.commit()
    p = Payment(teacher_id=t.id, kind="package", amount=0, hours=5,
                method="bonus", date="2026-06-22", is_paid=True)
    db.session.add(p)
    db.session.commit()
    sync_payment_to_finance(p, teacher_name=t.name)
    db.session.commit()
    assert FinTransaction.query.filter_by(payment_id=p.id).first() is None


def test_studio_linked_txn_delete_blocked(app, admin_client, post):
    """Studiyaga bog'langan moliya yozuvi jurnaldan o'chirilmaydi."""
    from models.billing import Teacher, Payment
    from modules.finance.studio_link import sync_payment_to_finance
    t = Teacher(name="Bloklangan Mijoz")
    db.session.add(t)
    db.session.commit()
    p = Payment(teacher_id=t.id, kind="hourly", amount=120000, hours=0,
                method="karta", date="2026-06-23", is_paid=True)
    db.session.add(p)
    db.session.commit()
    sync_payment_to_finance(p, teacher_name=t.name)
    db.session.commit()
    ft = FinTransaction.query.filter_by(payment_id=p.id).first()
    post(admin_client, f"/finance/transactions/{ft.id}/delete")
    assert FinTransaction.query.get(ft.id) is not None


# ── Moliya bo'limi faqat rahbarga ──

def test_finance_pages_operator_blocked(app):
    """Operator moliyani ko'ra olmaydi — dashboardга yo'naltiriladi."""
    from models.user import User
    u = User.query.filter_by(role="operator").first()
    if u is None:
        u = User(name="Op", code="222222", role="operator")
        db.session.add(u)
        db.session.commit()
    c = app.test_client()
    c.post("/login", data={"code": u.code})
    for url in ("/finance", "/finance/transactions", "/finance/dds",
                "/finance/debts", "/finance/dividends",
                "/finance/calendar", "/finance/analysis"):
        r = c.get(url)
        assert r.status_code in (302, 303), url
        assert "/finance" not in r.headers.get("Location", ""), url


# ── To'lov kalendari ──

def test_calendar_and_analysis_load(admin_client):
    for url in ("/finance/calendar", "/finance/calendar?year=2026&month=7",
                "/finance/analysis", "/finance/analysis?year=2026"):
        r = admin_client.get(url)
        assert r.status_code == 200, url


def test_default_recurring_seeded(app):
    """Kalendar bo'sh bo'lmasin — ijara/obuna seed qilinadi."""
    from models.finance import FinRecurring
    assert FinRecurring.query.count() >= 2


def test_plan_add_pay_creates_txn(app, admin_client, post):
    """Reja qo'shish → to'lash → jurnalda tranzaksiya paydo bo'ladi."""
    from models.finance import FinPlan, FinTransaction
    post(admin_client, "/finance/calendar/plan/add",
         date="2026-07-15", direction="out", description="Test uskuna",
         amount="1500000", category="прочие расходы", wallet="РС Jalinga")
    f = FinPlan.query.filter_by(description="Test uskuna").first()
    assert f is not None and f.is_paid is False
    post(admin_client, "/finance/calendar/pay",
         kind="plan", item_id=str(f.id), date="2026-07-15", wallet="РС Jalinga")
    assert FinPlan.query.get(f.id).is_paid is True
    ft = FinTransaction.query.filter_by(plan_id=f.id, source="plan").first()
    assert ft is not None and ft.amount == pytest.approx(1500000)
    assert ft.direction == "out"


def test_recurring_pay_and_double_block(app, admin_client, post):
    """Doimiy to'lov — to'lash jurnalga tushadi, ikkinchi marta bloklanadi."""
    from models.finance import FinRecurring, FinTransaction
    r = FinRecurring.query.first()
    post(admin_client, "/finance/calendar/pay",
         kind="recurring", item_id=str(r.id), date="2026-08-05",
         wallet="РС Jalinga")
    n = FinTransaction.query.filter_by(recurring_id=r.id, year=2026,
                                       month=8).count()
    assert n == 1
    # ikkinchi urinish — yangi yozuv yaratmaydi
    post(admin_client, "/finance/calendar/pay",
         kind="recurring", item_id=str(r.id), date="2026-08-20",
         wallet="РС Jalinga")
    n2 = FinTransaction.query.filter_by(recurring_id=r.id, year=2026,
                                        month=8).count()
    assert n2 == 1


def test_recurring_reconciled_by_category(app):
    """Shu oyда shu statyada haqiqiy chiqim bo'lsa, recurring qoplangan
    hisoblanadi (ikki marta sanamaslik)."""
    from models.finance import FinRecurring, FinTransaction
    from modules.finance.routes import _recurring_paid
    r = FinRecurring.query.filter_by(category="аренда").first()
    assert r is not None
    # Sheets'да 2026 mart oyида «аренда» chiqimi bor → qoplangan
    covered = _recurring_paid(r.id, 2026, 3, r.category)
    assert covered is True
    # Uzoq kelajak oyида hech narsa yo'q → qoplanmagan
    assert _recurring_paid(r.id, 2026, 11, r.category) is False
