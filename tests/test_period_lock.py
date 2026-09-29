"""Oy yopish (davr qulfi): yopiq oy moliyasi o'zgarmaydi."""
import pytest

from database import db


@pytest.fixture(autouse=True)
def _reset_lock(app):
    """Har test toza holatdan boshlanadi va qulfni ochiq qoldiradi."""
    from models.finance import FinSetting
    with app.app_context():
        FinSetting.set("closed_through", "")
        db.session.commit()
    yield
    with app.app_context():
        FinSetting.set("closed_through", "")
        db.session.commit()


def _lock(app, ym):
    from models.finance import FinSetting
    with app.app_context():
        FinSetting.set("closed_through", ym)
        db.session.commit()


def _cat(name="аренда"):
    from models.finance import FinCategory
    return FinCategory.query.filter_by(name=name).first()


def test_is_locked_logic(app):
    from core.period_lock import is_locked, shift_if_locked
    from core.timeutils import today_iso
    _lock(app, "2025-03")
    with app.app_context():
        assert is_locked("2025-03-31") and is_locked("2024-12-01")
        assert not is_locked("2025-04-01")
        assert shift_if_locked("2025-02-10") == (today_iso(), True)
        assert shift_if_locked("2025-04-10") == ("2025-04-10", False)


def test_manual_txn_blocked_in_closed_month(app, admin_client, post):
    from models.finance import FinTransaction
    _lock(app, "2025-03")
    post(admin_client, "/finance/transactions/add", date="2025-03-15",
         category="аренда", wallet="карта 9933", amount="100000",
         purpose="yopiq oy sinovi")
    with app.app_context():
        assert FinTransaction.query.filter_by(
            purpose="yopiq oy sinovi").first() is None
    # Ochiq oyga — o'tadi
    post(admin_client, "/finance/transactions/add", date="2025-04-15",
         category="аренда", wallet="карта 9933", amount="100000",
         purpose="ochiq oy sinovi")
    with app.app_context():
        assert FinTransaction.query.filter_by(
            purpose="ochiq oy sinovi").first() is not None


def test_edit_delete_blocked_in_closed_month(app, admin_client, post):
    from models.finance import FinTransaction
    with app.app_context():
        c = _cat()
        t = FinTransaction(date="2025-02-10", year=2025, month=2,
                           amount=500000, wallet="карта 9933",
                           category=c.name, direction=c.direction,
                           activity=c.activity, source="manual",
                           purpose="muzlatilgan")
        db.session.add(t)
        db.session.commit()
        tid = t.id
    _lock(app, "2025-02")
    # Tahrir (yopiq → ochiq oyga ko'chirish ham) rad etiladi
    post(admin_client, f"/finance/transactions/{tid}/edit",
         date="2025-05-01", category="аренда", wallet="карта 9933",
         amount="1", purpose="o'zgardi")
    post(admin_client, f"/finance/transactions/{tid}/delete")
    with app.app_context():
        t = FinTransaction.query.get(tid)
        assert t is not None and t.amount == 500000 and t.date == "2025-02-10"


def test_late_payment_confirmation_goes_to_today(app, admin_client, post):
    """Yopiq oy sanali studiya to'lovi tasdiqlansa — pul bugunga yoziladi,
    so'ng uni «kutilmoqda»ga qaytarib/o'chirib bo'lmaydi (oy yopilgach)."""
    from models.billing import Teacher, Payment
    from models.finance import FinTransaction
    from core.timeutils import today_iso
    with app.app_context():
        t = Teacher(name="Kech To'lov")
        db.session.add(t)
        db.session.flush()
        p = Payment(teacher_id=t.id, kind="hourly", amount=700000,
                    date="2025-01-20", is_paid=False)
        db.session.add(p)
        db.session.commit()
        pid = p.id
    _lock(app, "2025-01")
    post(admin_client, f"/finance/{pid}/pay", wallet="Наличные")
    with app.app_context():
        tx = FinTransaction.query.filter_by(payment_id=pid,
                                            source="studio").first()
        assert tx is not None and tx.date == today_iso()
        # Endi tranzaksiya oyini yopamiz → qaytarish/o'chirish rad etiladi
        tx.date, tx.year, tx.month = "2025-01-25", 2025, 1
        db.session.commit()
    post(admin_client, f"/finance/{pid}/toggle")
    post(admin_client, f"/finance/{pid}/delete")
    with app.app_context():
        assert Payment.query.get(pid).is_paid is True
        assert FinTransaction.query.filter_by(payment_id=pid).count() == 1


def test_close_and_reopen_routes(app, admin_client, post):
    from core.period_lock import closed_through
    from core.timeutils import current_month_iso
    # Joriy oyni yopib bo'lmaydi
    post(admin_client, "/finance/period/close", month=current_month_iso())
    with app.app_context():
        assert closed_through() == ""
    post(admin_client, "/finance/period/close", month="2025-06")
    with app.app_context():
        assert closed_through() == "2025-06"
    # Orqaga «yopish» qilinmaydi
    post(admin_client, "/finance/period/close", month="2025-03")
    with app.app_context():
        assert closed_through() == "2025-06"
    post(admin_client, "/finance/period/reopen")
    with app.app_context():
        assert closed_through() == "2025-05"
    r = admin_client.get("/finance/settings")
    assert r.status_code == 200 and "Oy yopish".encode() in r.data


def test_reopen_admin_only(app, post):
    from models.user import User
    from core.period_lock import closed_through
    with app.app_context():
        u = User.query.filter_by(code="913572").first()
        if not u:
            db.session.add(User(name="Bux Test", code="913572",
                                role="buxgalter"))
            db.session.commit()
    _lock(app, "2025-06")
    c = app.test_client()
    c.post("/login", data={"code": "913572"})
    post(c, "/finance/period/reopen")
    with app.app_context():
        assert closed_through() == "2025-06"
