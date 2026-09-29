"""Mijoz fikri (CSAT + NPS) — mantiq.

  • create_survey_for_booking(b) — idempotent; mijozni charchatmaslik uchun
    bitta mijozga SURVEY_COOLDOWN_DAYS ichida faqat bitta so'rovnoma
  • send_survey(s)               — Telegram ulangan mijozga havola
  • trigger_recent_surveys()     — kunlik: yaqinda «Yozildi» bo'lgan, lekin
                                   so'rovnomasi yo'q bronlar (tutib qolish)
  • apply_answers(s, form)       — javoblarni saqlash + norozi bo'lsa
                                   rahbarga shoshilinch vazifa
  • survey_stats(days)           — analitika uchun agregatlar (NPS va h.k.)
"""
import logging
from datetime import datetime, timedelta

from config import Config
from database import db
from models.feedback import (Survey, RATING_QUESTIONS, RATING_KEYS,
                             RATING_LABELS, LOW_THRESHOLD)

logger = logging.getLogger(__name__)

SURVEY_COOLDOWN_DAYS = 21   # bitta mijozga shu kun ichida bittadan ortiq emas
LOOKBACK_DAYS = 3           # kunlik tutib qolish oynasi


def survey_path(token):
    return f"/survey/{token}"


def survey_url(token):
    """Absolyut havola (Telegram uchun). Tashqi manzil noma'lum bo'lsa —
    so'rov kontekstidan; u ham bo'lmasa bo'sh (yuborib bo'lmaydi)."""
    base = Config.APP_URL
    if not base:
        try:
            from flask import request, has_request_context
            if has_request_context():
                base = request.host_url.rstrip("/")
        except Exception:
            base = ""
    return (base + survey_path(token)) if base else ""


def _recently_surveyed(teacher_id):
    cutoff = datetime.utcnow() - timedelta(days=SURVEY_COOLDOWN_DAYS)
    return db.session.query(Survey.id).filter(
        Survey.teacher_id == teacher_id,
        Survey.created_at >= cutoff).first() is not None


def create_survey_for_booking(b, send=True):
    """«Yozildi ✓» bron uchun so'rovnoma. Mavjud bo'lsa — o'shani qaytaradi;
    mijoz yaqinda so'ralgan bo'lsa — None (charchatmaymiz)."""
    if b is None or b.status != "done":
        return None
    existing = Survey.query.filter_by(booking_id=b.id).first()
    if existing:
        return existing
    if _recently_surveyed(b.teacher_id):
        return None
    s = Survey(booking_id=b.id, teacher_id=b.teacher_id,
               token=Survey.new_token(), status="pending")
    db.session.add(s)
    try:
        db.session.commit()
    except Exception:           # parallel yaratish (unikal booking_id)
        db.session.rollback()
        return Survey.query.filter_by(booking_id=b.id).first()
    if send:
        send_survey(s)
    return s


def send_survey(s):
    """Telegram ulangan mijozga iliq matn + havola. Yuborilmasa — kabinetda
    («Oxirgi yozuvni baholang») baribir ko'rinadi."""
    from core.telegram import is_configured, tg_send
    from models.billing import Teacher
    if not is_configured() or s.sent_at:
        return False
    t = Teacher.query.get(s.teacher_id)
    url = survey_url(s.token)
    if not (t and t.tg_chat_id and url):
        return False
    ok = tg_send(t.tg_chat_id,
                 "🎬 Jalinga Studio'da yozganingiz uchun rahmat!\n"
                 "Xizmatimizni yaxshilash uchun fikringiz juda muhim — "
                 f"1 daqiqada baholang:\n{url}")
    if ok:
        s.sent_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        db.session.commit()
    return ok


def trigger_recent_surveys(today=None):
    """Kunlik: oxirgi LOOKBACK_DAYS kunda «Yozildi» bo'lgan bronlar uchun
    so'rovnoma (status-o'zgarishda yaratilmay qolganlarni tutib qoladi)."""
    from core.timeutils import now_tashkent
    from models.studio import Booking
    d0 = (today or now_tashkent().date())
    since = (d0 - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    have = {r[0] for r in db.session.query(Survey.booking_id).all()}
    n = 0
    for b in Booking.query.filter(
            Booking.status == "done", Booking.date >= since,
            Booking.date <= d0.strftime("%Y-%m-%d")).order_by(
            Booking.date.asc()).all():
        if b.id in have:
            continue
        if create_survey_for_booking(b):
            n += 1
    return n


def _int(v, lo, hi):
    try:
        x = int(v)
    except (ValueError, TypeError):
        return None
    return x if lo <= x <= hi else None


def apply_answers(s, form):
    """Formadan javoblar. Xato bo'lsa matn qaytaradi, aks holda None."""
    vals = {k: _int(form.get(k), 1, 5) for k in RATING_KEYS}
    if vals["overall"] is None:
        return "Iltimos, kamida umumiy taassurotni baholang ⭐"
    for k, v in vals.items():
        setattr(s, k, v)
    s.recommend = _int(form.get("recommend"), 0, 10)
    s.comment = (form.get("comment") or "").strip()[:2000]
    issues = {}
    for k, v in vals.items():
        if v is not None and v < LOW_THRESHOLD:
            txt = (form.get(f"issue_{k}") or "").strip()[:500]
            if txt:
                issues[k] = txt
    s.set_issues(issues)
    s.status = "done"
    s.done_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.session.commit()
    if s.is_unhappy:
        _service_recovery(s)
    return None


def _service_recovery(s):
    """Norozi mijoz → rahbarga shoshilinch vazifa (bugun bog'lanish)."""
    try:
        from core.comms import create_task
        from core.timeutils import today_iso
        from models.billing import Teacher
        from models.studio import Booking
        t = Teacher.query.get(s.teacher_id)
        b = Booking.query.get(s.booking_id)
        low = [f"{RATING_LABELS[k]}: {getattr(s, k)}/5" for k in RATING_KEYS
               if getattr(s, k) is not None and getattr(s, k) <= 3]
        lines = [f"Mijoz: {t.name if t else '?'}"
                 + (f" · ☎ {t.phone}" if t and t.phone else ""),
                 f"Yozuv: {b.date} {b.start}–{b.end}" if b else ""]
        if low:
            lines.append("Past baholar: " + ", ".join(low))
        if s.recommend is not None:
            lines.append(f"Tavsiya (NPS): {s.recommend}/10")
        for k, txt in s.issues_dict.items():
            lines.append(f"• {RATING_LABELS.get(k, k)}: {txt}")
        if s.comment:
            lines.append(f"Izoh: «{s.comment[:300]}»")
        create_task(
            title=f"😟 Norozi mijoz: {t.name if t else '?'} — bugun bog'laning",
            description="\n".join(x for x in lines if x),
            target_role="admin", priority="urgent", due_date=today_iso(),
            related_type="teacher", related_id=s.teacher_id, is_auto=True)
    except Exception as exc:
        logger.warning(f"service recovery vazifasi xato: {exc}")


def pending_for_teacher(teacher_id):
    """Mijoz kabineti uchun: baholanmagan eng yangi so'rovnoma."""
    return Survey.query.filter_by(
        teacher_id=teacher_id, status="pending").order_by(
        Survey.id.desc()).first()


def survey_stats(days=90):
    """Analitika: javob darajasi, o'rtacha baho, NPS, o'lchamlar, izohlar."""
    from models.billing import Teacher
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = Survey.query.filter(Survey.created_at >= cutoff).order_by(
        Survey.id.desc()).all()
    done = [s for s in rows if s.status == "done"]
    out = {"sent": len(rows), "done": len(done),
           "rate": round(len(done) / len(rows) * 100) if rows else 0,
           "avg": None, "nps": None, "promoters": 0, "passives": 0,
           "detractors": 0, "dims": [], "weakest": None, "comments": [],
           "unhappy": 0, "days": days}
    if not done:
        return out
    ov = [s.overall for s in done if s.overall]
    out["avg"] = round(sum(ov) / len(ov), 2) if ov else None
    rec = [s.recommend for s in done if s.recommend is not None]
    if rec:
        p = sum(1 for r in rec if r >= 9)
        d = sum(1 for r in rec if r <= 6)
        out.update(promoters=p, detractors=d, passives=len(rec) - p - d,
                   nps=round((p - d) / len(rec) * 100))
    for k, lbl, emoji, _q in RATING_QUESTIONS:
        vs = [getattr(s, k) for s in done if getattr(s, k)]
        if vs:
            out["dims"].append({"key": k, "label": lbl, "emoji": emoji,
                                "avg": round(sum(vs) / len(vs), 2),
                                "n": len(vs)})
    if out["dims"]:
        out["weakest"] = min(out["dims"], key=lambda x: x["avg"])
    out["unhappy"] = sum(1 for s in done if s.is_unhappy)
    tmap = {t.id: t.name for t in Teacher.query.all()}
    for s in done:
        if s.comment or s.issues_dict:
            out["comments"].append({
                "who": tmap.get(s.teacher_id, "?"), "at": s.done_at,
                "overall": s.overall, "recommend": s.recommend,
                "text": s.comment,
                "issues": [(RATING_LABELS.get(k, k), v)
                           for k, v in s.issues_dict.items()]})
        if len(out["comments"]) >= 8:
            break
    return out


def teacher_rating(teacher_id):
    """Mijoz kartasi uchun: (o'rtacha umumiy baho, javoblar soni)."""
    done = Survey.query.filter_by(teacher_id=teacher_id, status="done").all()
    ov = [s.overall for s in done if s.overall]
    return (round(sum(ov) / len(ov), 1) if ov else None), len(done)
