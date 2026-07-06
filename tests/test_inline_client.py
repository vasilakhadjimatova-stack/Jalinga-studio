"""Bronda inline yangi mijoz qo'shish + relabel (Ustoz→Mijoz) tekshiruvi."""


def _sid(app):
    from models.studio import Studio
    with app.app_context():
        return Studio.query.first().id


def test_booking_creates_new_client_inline(app, admin_client, post):
    """client_mode=new → mijoz yaratiladi va bron qilinadi (bir qadamda)."""
    from models.studio import Booking
    from models.billing import Teacher
    sid = _sid(app)
    r = post(admin_client, "/bookings/save", studio_id=sid,
             client_mode="new", new_name="Yangi Bloger",
             new_phone="+998901234567", date="2028-01-10",
             start="10:00", end="12:00", pay_type="hourly")
    assert r.status_code == 302
    with app.app_context():
        t = Teacher.query.filter_by(name="Yangi Bloger").first()
        assert t is not None
        assert t.portal_token                       # portal darhol tayyor
        assert Booking.query.filter_by(teacher_id=t.id).count() == 1


def test_inline_new_client_dedup_by_phone(app, admin_client, post):
    """Bir xil telefon (oxirgi 9 raqam) → mavjud mijoz ishlatiladi."""
    from models.billing import Teacher
    from models.studio import Booking
    from database import db
    with app.app_context():
        ex = Teacher(name="Mavjud Mijoz", phone="+998907776655")
        db.session.add(ex); db.session.commit()
        exid = ex.id
    sid = _sid(app)
    post(admin_client, "/bookings/save", studio_id=sid, client_mode="new",
         new_name="Boshqa Ism", new_phone="90 777 66 55",
         date="2028-02-15", start="10:00", end="12:00", pay_type="hourly")
    with app.app_context():
        # Yangi Teacher yaratilmadi — mavjudiga bron biriktirildi
        assert Teacher.query.filter_by(name="Boshqa Ism").count() == 0
        assert Booking.query.filter_by(teacher_id=exid).count() == 1


def test_inline_new_client_requires_name(app, admin_client, post):
    from models.studio import Booking
    sid = _sid(app)
    before = None
    with app.app_context():
        before = Booking.query.count()
    post(admin_client, "/bookings/save", studio_id=sid, client_mode="new",
         new_name="", new_phone="+998900000000", date="2028-03-01",
         start="10:00", end="12:00", pay_type="hourly")
    with app.app_context():
        assert Booking.query.count() == before       # hech nima yaratilmadi


def test_existing_mode_still_works(app, admin_client, post):
    from models.billing import Teacher
    from models.studio import Booking
    from database import db
    with app.app_context():
        t = Teacher(name="Tanlangan Mijoz")
        db.session.add(t); db.session.commit()
        tid = t.id
    sid = _sid(app)
    post(admin_client, "/bookings/save", studio_id=sid,
         client_mode="existing", teacher_id=tid, date="2028-04-01",
         start="10:00", end="12:00", pay_type="hourly")
    with app.app_context():
        assert Booking.query.filter_by(teacher_id=tid).count() == 1


def test_labels_say_mijoz_not_ustoz(app, admin_client):
    """UI relabel: sahifalarda «Mijoz» ko'rinadi, «Ustoz» label yo'q.

    (Eslatma: mijoz ISMIda 'Ustoz' bo'lishi mumkin — shuning uchun aniq
    label matnlarini tekshiramiz, umumiy 'Ustoz' so'zini emas.)"""
    html = admin_client.get("/teachers").data.decode()
    assert '<div class="ph-title">Mijozlar' in html   # «Mijozlar» / «Mijozlar CRM»
    assert "Yangi mijoz" in html
    assert "Yangi ustoz" not in html
    assert ">Ustozlar<" not in html                  # sidebar/nav label emas

    cal = admin_client.get("/calendar").data.decode()
    assert "Yangi mijoz" in cal                       # inline qo'shish tugmasi
    assert "<label>Ustoz</label>" not in cal


def test_client_card_package_purchase(app, admin_client, post):
    """Mijoz kartasi: paket sotib olish → balans oshadi."""
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name="Paket Mijoz")
        db.session.add(t); db.session.commit()
        tid = t.id
    post(admin_client, f"/teachers/{tid}/package", hours=10,
         amount=2500000, method="naqd")
    with app.app_context():
        assert Teacher.query.get(tid).balance_hours() == 10
