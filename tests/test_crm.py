"""Mijozlar CRM — segment, LTV, o'zaro aloqa (notes/follow-up)."""
import pytest

from database import db
from models.billing import Teacher, Payment, ClientNote


@pytest.fixture(autouse=True)
def _ctx(app):
    with app.app_context():
        yield


def _mk_client(name="CRM Mijoz"):
    t = Teacher(name=name)
    db.session.add(t)
    db.session.commit()
    return t.id


def test_crm_list_loads(admin_client):
    r = admin_client.get("/teachers")
    assert r.status_code == 200
    assert "Mijozlar CRM".encode() in r.data
    assert "LTV" in r.data.decode()


def test_ltv_computed(app, admin_client):
    tid = _mk_client("LTV Test")
    db.session.add_all([
        Payment(teacher_id=tid, kind="package", amount=2000000, hours=10,
                date="2026-06-01", is_paid=True),
        Payment(teacher_id=tid, kind="hourly", amount=500000, hours=0,
                date="2026-06-05", is_paid=True),
        Payment(teacher_id=tid, kind="hourly", amount=999, hours=0,
                date="2026-06-06", is_paid=False),  # kutilmoqda — LTV'ga kirmaydi
    ])
    db.session.commit()
    assert Teacher.query.get(tid).ltv() == 2500000


def test_source_and_tags_saved(app, admin_client, post):
    post(admin_client, "/teachers/save", name="Teg Mijoz",
         source="Instagram", tags="VIP, korporativ")
    t = Teacher.query.filter_by(name="Teg Mijoz").first()
    assert t.source == "Instagram"
    assert t.tag_list() == ["VIP", "korporativ"]


def test_add_and_delete_note(app, admin_client, post):
    tid = _mk_client("Note Mijoz")
    post(admin_client, f"/teachers/{tid}/note", kind="call",
         text="Qo'ng'iroq qilindi, kelishildi")
    n = ClientNote.query.filter_by(teacher_id=tid).first()
    assert n is not None and n.kind == "call" and n.author  # muallif yozilgan
    post(admin_client, f"/teachers/{tid}/note/{n.id}/delete")
    assert ClientNote.query.get(n.id) is None


def test_followup_flow(app, admin_client, post):
    tid = _mk_client("Followup Mijoz")
    post(admin_client, f"/teachers/{tid}/note", kind="followup",
         text="Qayta qo'ng'iroq", due_date="2026-07-20")
    n = ClientNote.query.filter_by(teacher_id=tid, kind="followup").first()
    assert n.due_date == "2026-07-20" and n.done is False
    # follow-up ro'yxatда ko'rinadi
    assert "Followup Mijoz".encode() in admin_client.get("/teachers").data
    # bajarildi deb belgilash
    post(admin_client, f"/teachers/{tid}/note/{n.id}/done")
    assert ClientNote.query.get(n.id).done is True


def test_segment_filter(app, admin_client):
    _mk_client("Segment Yangi")  # tashrifsiz, yaqinda → 'new'
    r = admin_client.get("/teachers?seg=new")
    assert r.status_code == 200
    assert "Segment Yangi".encode() in r.data
