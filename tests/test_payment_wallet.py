"""To'lovni «to'landi» qilganda hisob (hamyon) so'raladi va moliyaga bog'lanadi."""


def _mk_pending_payment(app, amount=1500000, method="naqd"):
    from database import db
    from models.billing import Teacher, Payment
    with app.app_context():
        t = Teacher(name="Wallet Test", is_active=True)
        db.session.add(t); db.session.commit()
        p = Payment(teacher_id=t.id, kind="hourly", amount=amount,
                    date="2026-07-25", is_paid=False, method=method,
                    note="test to'lov")
        db.session.add(p); db.session.commit()
        return p.id


def test_payments_page_lists_wallets(app, admin_client):
    _mk_pending_payment(app)
    r = admin_client.get("/finance/payments?month=2026-07")
    assert r.status_code == 200
    # Modal hisob (hamyon) tanlash bilan chiqadi
    assert "Qaysi hisobga".encode() in r.data
    assert "РС Jalinga".encode() in r.data


def test_pay_stores_wallet_and_links_finance(app, admin_client, post):
    pid = _mk_pending_payment(app, amount=2000000)
    post(admin_client, f"/finance/{pid}/pay",
         wallet="РС Jalinga", method="o'tkazma")
    from models.billing import Payment
    from models.finance import FinTransaction
    with app.app_context():
        p = Payment.query.get(pid)
        assert p.is_paid is True
        assert p.wallet == "РС Jalinga"
        assert p.method == "o'tkazma"
        tx = FinTransaction.query.filter_by(
            payment_id=pid, source="studio").first()
        assert tx is not None
        assert tx.wallet == "РС Jalinga"
        assert tx.amount == 2000000
        assert tx.direction == "in"


def test_pay_wallet_choice_overrides_method_default(app, admin_client, post):
    """Tanlangan hisob to'lov usulidan ustun — mijoz naqd desa ham, tanlangan
    hisobga tushadi."""
    pid = _mk_pending_payment(app, method="naqd")
    post(admin_client, f"/finance/{pid}/pay", wallet="карта 9933", method="naqd")
    from models.finance import FinTransaction
    with app.app_context():
        tx = FinTransaction.query.filter_by(
            payment_id=pid, source="studio").first()
        assert tx.wallet == "карта 9933"   # usul emas, tanlangan hisob


def test_booking_paid_now_links_finance(app, admin_client, post):
    """Bron paytida «Darhol to'landi» + hisob → to'lov to'langan va moliyaga
    bog'langan bo'ladi."""
    from models.studio import Studio
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name="Darhol Bron", is_active=True)
        db.session.add(t); db.session.commit()
        sid = Studio.query.first().id
        tid = t.id
    post(admin_client, "/bookings/save", client_mode="existing",
         studio_id=sid, teacher_id=tid, date="2026-08-11",
         start="10:00", end="12:00", pay_type="hourly",
         paid_now="1", pay_wallet="Наличные", pay_method="naqd")
    from models.studio import Booking
    from models.billing import Payment
    from models.finance import FinTransaction
    with app.app_context():
        b = Booking.query.filter_by(teacher_id=tid, date="2026-08-11").first()
        p = Payment.query.filter_by(booking_id=b.id).first()
        assert p.is_paid is True and p.wallet == "Наличные"
        tx = FinTransaction.query.filter_by(
            payment_id=p.id, source="studio").first()
        assert tx is not None and tx.wallet == "Наличные"


def test_booking_without_paid_now_stays_pending(app, admin_client, post):
    from models.studio import Studio
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name="Kutilmoqda Bron", is_active=True)
        db.session.add(t); db.session.commit()
        sid = Studio.query.first().id
        tid = t.id
    post(admin_client, "/bookings/save", client_mode="existing",
         studio_id=sid, teacher_id=tid, date="2026-08-12",
         start="10:00", end="12:00", pay_type="hourly")
    from models.studio import Booking
    from models.billing import Payment
    with app.app_context():
        b = Booking.query.filter_by(teacher_id=tid, date="2026-08-12").first()
        p = Payment.query.filter_by(booking_id=b.id).first()
        assert p.is_paid is False and p.wallet == ""


def test_revert_unlinks_finance_and_clears_wallet(app, admin_client, post):
    pid = _mk_pending_payment(app)
    post(admin_client, f"/finance/{pid}/pay", wallet="Наличные", method="naqd")
    post(admin_client, f"/finance/{pid}/toggle")   # kutilmoqda'ga qaytarish
    from models.billing import Payment
    from models.finance import FinTransaction
    with app.app_context():
        p = Payment.query.get(pid)
        assert p.is_paid is False
        assert p.wallet == ""
        assert FinTransaction.query.filter_by(
            payment_id=pid, source="studio").first() is None
