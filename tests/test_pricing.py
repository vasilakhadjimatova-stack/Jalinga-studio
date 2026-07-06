"""Vaqtga bog'liq chegirmalar — narx qoidalari kalendar/online/portalga ta'sir qiladi."""
from datetime import timedelta

import pytest

from core.timeutils import now_tashkent


@pytest.fixture(autouse=True)
def _clean_rules(app):
    """Har test oldidan narx qoidalarini tozalaydi (izolyatsiya)."""
    from models.pricing import PriceRule
    from database import db
    with app.app_context():
        PriceRule.query.delete()
        db.session.commit()
    yield


def _sid(app):
    from models.studio import Studio
    with app.app_context():
        return Studio.query.first().id


def _mk_rule(app, **kw):
    from models.pricing import PriceRule
    from database import db
    defaults = dict(studio_id=None, name="Test chegirma", days="",
                    start_hour=9, end_hour=14, discount=25, is_active=True)
    defaults.update(kw)
    with app.app_context():
        r = PriceRule(**defaults)
        db.session.add(r); db.session.commit()
        return r.id


def _next_weekday(target_wd, base_days=7):
    """Kelajakdagi target hafta-kuniga to'g'ri keladigan sana (ISO)."""
    d = now_tashkent().date() + timedelta(days=base_days)
    while d.weekday() != target_wd:
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def test_best_discount_matches_hour(app):
    _mk_rule(app, start_hour=9, end_hour=14, discount=30, days="")
    from models.pricing import best_discount
    day = _next_weekday(0)   # dushanba
    with app.app_context():
        assert best_discount(1, day, "10:00")[0] == 30   # oraliq ichida
        assert best_discount(1, day, "15:00")[0] == 0     # oraliqdan tashqari


def test_booking_price_applies_discount(app):
    _mk_rule(app, start_hour=9, end_hour=14, discount=20, days="")
    from models.studio import Studio
    from models.pricing import booking_price
    day = _next_weekday(1)
    with app.app_context():
        st = Studio.query.first()
        rate = st.hourly_rate or 0
        amount, disc, _n, base = booking_price(st, day, "10:00", 2)
        assert base == round(2 * rate)
        assert disc == 20
        assert amount == round(base * 0.8)


def test_rule_weekday_filter(app):
    # Faqat yakshanba (6) uchun chegirma
    _mk_rule(app, start_hour=9, end_hour=21, discount=15, days="6")
    from models.pricing import best_discount
    with app.app_context():
        assert best_discount(1, _next_weekday(6), "10:00")[0] == 15   # yakshanba
        assert best_discount(1, _next_weekday(2), "10:00")[0] == 0     # chorshanba


def test_rule_studio_scope(app):
    from models.studio import Studio
    with app.app_context():
        sid = Studio.query.first().id
    _mk_rule(app, studio_id=sid, start_hour=9, end_hour=21, discount=40, days="")
    from models.pricing import best_discount
    day = _next_weekday(3)
    with app.app_context():
        assert best_discount(sid, day, "12:00")[0] == 40        # o'sha studiya
        assert best_discount(sid + 999, day, "12:00")[0] == 0   # boshqa studiya


def test_online_booking_charges_discounted(app, client):
    _mk_rule(app, start_hour=9, end_hour=14, discount=50, days="")
    sid = _sid(app)
    day = _next_weekday(4, base_days=8)
    from models.studio import Studio
    with app.app_context():
        rate = Studio.query.get(sid).hourly_rate or 0
    r = client.post("/book/submit", data={
        "name": "Chegirma Mijoz", "phone": "+998907778899",
        "studio_id": sid, "date": day, "start": "10:00", "hours": "2"})
    assert "/book/done" in r.headers.get("Location", "")
    from models.studio import Booking
    from models.billing import Payment
    with app.app_context():
        b = Booking.query.filter_by(date=day, start="10:00").first()
        p = Payment.query.filter_by(booking_id=b.id).first()
        assert p.amount == round(round(2 * rate) * 0.5)   # 50% chegirma


def test_pricing_admin_crud(app, admin_client, post):
    sid = _sid(app)
    r = post(admin_client, "/pricing/save", name="Kechki",
             studio_id=0, days=["5", "6"], start_hour="18", end_hour="21",
             discount="15", is_active="1")
    assert r.status_code in (302, 303)
    from models.pricing import PriceRule
    with app.app_context():
        rule = PriceRule.query.filter_by(name="Kechki").first()
        assert rule and rule.discount == 15 and rule.start_hour == 18
        rid = rule.id
    # o'chirish
    post(admin_client, "/pricing/delete", id=str(rid))
    with app.app_context():
        assert PriceRule.query.get(rid) is None


def test_pricing_page_admin_only(app, client):
    r = client.get("/pricing")   # login yo'q
    assert r.status_code in (301, 302)


def test_manual_discount_takes_max(app):
    """Qo'lda chegirma vaqt qoidasi bilan solishtirilib kattarog'i olinadi."""
    from models.studio import Studio
    from models.pricing import booking_price
    _mk_rule(app, start_hour=9, end_hour=14, discount=10, days="")
    day = _next_weekday(2)
    with app.app_context():
        st = Studio.query.first()
        base = round(2 * (st.hourly_rate or 0))
        # qo'lda 30 > avto 10 → 30 olinadi
        amount, disc, _n, _b = booking_price(st, day, "10:00", 2, manual=30)
        assert disc == 30 and amount == round(base * 0.7)
        # qo'lda 5 < avto 10 → 10 (va'da qilingan chegirma yo'qolmaydi)
        amount2, disc2, _n2, _b2 = booking_price(st, day, "10:00", 2, manual=5)
        assert disc2 == 10 and amount2 == round(base * 0.9)


def test_staff_booking_manual_discount(app, admin_client, post):
    """Operator bron qilishда qo'lda chegirma kiritsa — to'lovga tushadi."""
    from models.studio import Studio
    from models.billing import Teacher
    from database import db
    with app.app_context():
        from models.pricing import PriceRule
        PriceRule.query.delete(); db.session.commit()
        t = Teacher(name="Disc Booking", is_active=True)
        db.session.add(t); db.session.commit()
        sid = Studio.query.first().id
        tid = t.id
        rate = Studio.query.first().hourly_rate or 0
    day = _next_weekday(3, base_days=9)
    post(admin_client, "/bookings/save", client_mode="existing",
         studio_id=sid, teacher_id=tid, date=day, start="16:00", end="18:00",
         pay_type="hourly", discount="40")
    from models.studio import Booking
    from models.billing import Payment
    with app.app_context():
        b = Booking.query.filter_by(date=day, teacher_id=tid).first()
        p = Payment.query.filter_by(booking_id=b.id).first()
        assert p.amount == round(round(2 * rate) * 0.6)   # 40% off
