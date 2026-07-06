"""«Bugun e'tibor» markazi + Telegram kunlik digest matni.

Bot tokeni kerak emas — faqat matn quruvchi mantiq sinaladi (jonli yuborish
alohida; tokensiz muhitda no-op).
"""


def _mk_teacher(app, name="Digest Ustoz", **kw):
    from models.billing import Teacher
    from database import db
    with app.app_context():
        t = Teacher(name=name, is_active=True, **kw)
        db.session.add(t); db.session.commit()
        return t.id


# ── attention_items ──
def test_attention_returns_list(app):
    from modules.dashboard.attention import attention_items
    with app.app_context():
        items = attention_items()
    assert isinstance(items, list)
    # Har element to'liq shaklda
    for a in items:
        assert {"level", "icon", "title", "count", "detail", "link"} <= set(a)
        assert a["level"] in ("danger", "warn", "info")


def test_attention_sorted_danger_first(app):
    from modules.dashboard.attention import attention_items
    order = {"danger": 0, "warn": 1, "info": 2}
    with app.app_context():
        items = attention_items()
    levels = [order[a["level"]] for a in items]
    assert levels == sorted(levels)   # danger → warn → info


def test_attention_surfaces_overdue_followup(app):
    """Muddati o'tgan follow-up eslatmasi e'tibor ro'yxatida chiqishi kerak."""
    from database import db
    from models.billing import ClientNote
    tid = _mk_teacher(app, "Followup Mijoz")
    with app.app_context():
        db.session.add(ClientNote(
            teacher_id=tid, kind="followup", done=False,
            due_date="2020-01-01", text="qo'ng'iroq qilish"))
        db.session.commit()
    from modules.dashboard.attention import attention_items
    with app.app_context():
        items = attention_items()
    fu = [a for a in items if a["title"] == "Follow-up eslatmalar"]
    assert fu and fu[0]["count"] >= 1


# ── Telegram digest matni ──
def test_digest_text_has_core_sections(app):
    from core.telegram import build_digest_text
    with app.app_context():
        text = build_digest_text()
    assert "Kunlik hisobot" in text
    assert "Shu oy tushum" in text
    assert "Bugun yozuvlar" in text


def test_digest_text_lists_attention(app):
    """Follow-up bo'lsa digest matnida ko'rinishi kerak."""
    from database import db
    from models.billing import ClientNote
    tid = _mk_teacher(app, "Digest Followup")
    with app.app_context():
        db.session.add(ClientNote(
            teacher_id=tid, kind="followup", done=False,
            due_date="2020-01-01", text="digest test"))
        db.session.commit()
        from core.telegram import build_digest_text
        text = build_digest_text()
    assert "Follow-up" in text
