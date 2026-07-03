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
    """Balans = ochilish + kirim - chiqim; jami iyun oxiri qoldig'iga teng."""
    from modules.finance.routes import _wallet_balances
    total = sum(b["balance"] for b in _wallet_balances())
    # ДДС_2026 iyun: Чистый денежный поток = 19 162 414.52
    assert total == pytest.approx(19162414.52, abs=0.05)


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
