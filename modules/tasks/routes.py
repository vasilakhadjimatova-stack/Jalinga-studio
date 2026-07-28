"""Vazifalar — rolelararo topshiriq va so'rovlar (Impulse ERP'dan moslashtirilgan).

4 bosqichli Kanban: Yangi → Qabul qildim → Jarayonda → Tugallandi.
Har bir xodim vazifa bera oladi; rahbar (admin) butun jamoani boshqaradi va
istalgan xodimga tayinlaydi. Bildirishnomalar inbox + Telegram orqali keladi.
"""
import hashlib
import logging
import re
from datetime import date, datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, jsonify)

from core.auth import login_required, current_user
from database import db
from models.user import User, ROLES, ROLE_LABELS
from models.communication import Task, TaskComment, TaskActivity
from core.comms import (create_task, advance_task, tasks_for, log_event, notify,
                        get_notifications_for, unread_count, mark_all_read,
                        mark_read)

logger = logging.getLogger(__name__)

bp = Blueprint("tasks", __name__)

_PALETTE = ["#F0A831", "#60A5FA", "#7CBFA0", "#FB7185", "#FBBF24",
            "#A78BFA", "#22D3EE", "#F472B6", "#4ADE80", "#FB923C"]

OPEN_STATUSES = ("new", "accepted", "in_progress")
VALID_STATUS = ("new", "accepted", "in_progress", "done", "cancelled")
VALID_PRIORITY = ("low", "normal", "high", "urgent")


# ── Yordamchilar ──────────────────────────────────────────────────
def _color_for(name):
    h = int(hashlib.md5((name or "?").encode("utf-8")).hexdigest(), 16)
    return _PALETTE[h % len(_PALETTE)]


def _initials(name):
    parts = [p for p in (name or "").replace("(jamoa)", "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _parse_due(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _due_state(s, status):
    d = _parse_due(s)
    if not d or status == "done":
        return ""
    today = date.today()
    if d < today:
        return "overdue"
    if d == today:
        return "today"
    if (d - today).days <= 3:
        return "soon"
    return "ok"


def _is_responsible(u, t):
    """Vazifa shu foydalanuvchi bajaradigan (mas'ul)mi?
    • Asosiy/qo'shimcha mas'ul — ha
    • Rahbar (o'z rolega yoki jamoaga kelgan) — boshqara oladi"""
    if not (u and t):
        return False
    if t.is_assignee(u.id):
        return True
    if t.target_role and t.target_role == u.role and not t.assignee_id:
        return True
    if u.is_boss:
        return True
    return False


def _can_assign(u, t):
    """Vazifani xodimga tayinlay oladimi? — topshirgan, rahbar yoki admin."""
    if not (u and t):
        return False
    if u.is_admin or u.is_boss:
        return True
    if t.assigner_id == u.id:
        return True
    return False


def _can_edit(u, t):
    return bool(u and t and (u.is_admin or u.is_boss or t.assigner_id == u.id))


# ── VAZIFALAR TAXTASI ─────────────────────────────────────────────
@bp.route("/tasks")
@login_required
def board():
    u = current_user()
    if u.is_boss:
        base = (Task.query.order_by(Task.created_at.desc()).limit(1500).all())
    else:
        base = tasks_for(u)

    # Tugatilganlar tepada yaqinda tugatilgani bo'yicha
    done_rows = [t for t in base if t.status == "done"]
    rest_rows = [t for t in base if t.status != "done"]
    done_rows.sort(key=lambda t: t.updated_at or t.created_at, reverse=True)
    base = rest_rows + done_rows

    umap = {usr.id: usr for usr in User.query.all()}

    def enrich(t):
        d = t.to_dict()
        d["is_mine"] = t.is_assignee(u.id)
        d["assignee_id"] = t.assignee_id
        d["assignee_key"] = str(t.assignee_id) if t.assignee_id else ""
        if t.assignee_id and t.assignee_id in umap:
            usr = umap[t.assignee_id]
            d["owner"] = usr.name
            d["owner_kind"] = "person"
            d["owner_color"] = _color_for(usr.name)
            d["owner_initials"] = _initials(usr.name)
            d["filter_role"] = usr.role
        elif t.assignee_name:
            d["owner"] = t.assignee_name
            d["owner_kind"] = "person"
            d["owner_color"] = _color_for(t.assignee_name)
            d["owner_initials"] = _initials(t.assignee_name)
            d["filter_role"] = ""
        elif t.target_role:
            d["owner"] = f"{ROLE_LABELS.get(t.target_role, t.target_role)} (jamoa)"
            d["owner_kind"] = "role"
            d["owner_color"] = _color_for(t.target_role)
            d["owner_initials"] = _initials(ROLE_LABELS.get(t.target_role, t.target_role))
            d["filter_role"] = t.target_role
        else:
            d["owner"] = "—"
            d["owner_kind"] = "none"
            d["owner_color"] = "#8A93A8"
            d["owner_initials"] = "?"
            d["filter_role"] = ""
        d["due_state"] = _due_state(t.due_date, t.status)
        d["can_act"] = _is_responsible(u, t)
        d["can_assign"] = _can_assign(u, t)
        d["can_edit"] = _can_edit(u, t)
        d["awaits_assignment"] = bool(
            t.target_role and not t.assignee_id
            and t.status in OPEN_STATUSES)
        return d

    enriched = [enrich(t) for t in base]

    by_status = {
        "new": [d for d in enriched if d["status"] == "new"],
        "accepted": [d for d in enriched if d["status"] == "accepted"],
        "in_progress": [d for d in enriched if d["status"] == "in_progress"],
        "done": [d for d in enriched if d["status"] == "done"][:40],
    }

    # Filtr: rollar (band vazifalar soni bilan)
    from collections import Counter
    role_open = Counter()
    for d in enriched:
        if d["status"] in OPEN_STATUSES and d["filter_role"]:
            role_open[d["filter_role"]] += 1
    role_list = []
    for i, r in enumerate(ROLES):
        role_list.append({
            "role": r, "label": ROLE_LABELS.get(r, r),
            "initials": _initials(ROLE_LABELS.get(r, r)),
            "color": _PALETTE[i % len(_PALETTE)],
            "open": role_open.get(r, 0)})

    # Vazifa berish uchun xodimlar ro'yxati
    people = [{
        "id": usr.id, "name": usr.name, "role": usr.role,
        "role_label": ROLE_LABELS.get(usr.role, usr.role),
        "color": _color_for(usr.name), "initials": _initials(usr.name),
    } for usr in User.staff()]

    counts = {
        "open_total": sum(1 for d in enriched if d["status"] in OPEN_STATUSES),
        "done_total": sum(1 for d in enriched if d["status"] == "done"),
        "my": sum(1 for d in enriched
                  if d["status"] in OPEN_STATUSES and d["is_mine"]),
        "overdue": sum(1 for d in enriched
                       if d["status"] in OPEN_STATUSES
                       and d["due_state"] == "overdue"),
        "urgent": sum(1 for d in enriched
                      if d["status"] in OPEN_STATUSES
                      and d["priority"] == "urgent"),
        "awaiting": sum(1 for d in enriched if d["awaits_assignment"]),
    }

    return render_template(
        "tasks.html", by_status=by_status, roles=role_list, people=people,
        role_labels=ROLE_LABELS, counts=counts,
        is_admin=u.is_admin, is_boss=u.is_boss, me_id=u.id,
        today_iso=date.today().strftime("%Y-%m-%d"))


# ── DETAIL + CHAT ─────────────────────────────────────────────────
def _detail_ctx(t, u):
    from core.timeutils import now_tashkent
    d = t.to_dict()
    d["due_state"] = _due_state(t.due_date, t.status)
    d["can_act"] = _is_responsible(u, t)
    d["can_assign"] = _can_assign(u, t)
    d["can_edit"] = _can_edit(u, t)
    acts = [a.to_dict() for a in TaskActivity.query.filter_by(
        task_id=t.id).order_by(TaskActivity.created_at.desc()).all()]
    _dt = now_tashkent().date()
    comments = [c.to_dict() for c in TaskComment.query.filter_by(
        task_id=t.id).order_by(TaskComment.created_at.asc()).all()]
    return {"t": d, "activities": acts, "comments": comments, "me_id": u.id}


@bp.route("/tasks/<int:tid>/detail")
@login_required
def detail(tid):
    t = Task.query.get_or_404(tid)
    return render_template("partials/task_detail.html", **_detail_ctx(t, current_user()))


@bp.route("/tasks/<int:tid>/chat")
@login_required
def chat(tid):
    Task.query.get_or_404(tid)
    comments = [c.to_dict() for c in TaskComment.query.filter_by(
        task_id=tid).order_by(TaskComment.created_at.asc()).all()]
    return render_template("partials/task_chat.html", comments=comments,
                           me_id=current_user().id)


# ── YANGI VAZIFA ──────────────────────────────────────────────────
@bp.route("/tasks/new", methods=["POST"])
@login_required
def new():
    u = current_user()
    f = request.form
    title = (f.get("title") or "").strip()
    if not title:
        flash("Vazifa nomini kiriting", "error")
        return redirect(url_for("tasks.board"))

    desc = (f.get("description") or "").strip()
    pr = f.get("priority") if f.get("priority") in VALID_PRIORITY else "normal"
    due = (f.get("due_date") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", due):
        flash("⛔ Muddatni tanlang — muddatsiz vazifa qabul qilinmaydi", "error")
        return redirect(url_for("tasks.board"))

    assign = (f.get("assign_to") or "").strip()   # "user:5" yoki "role:operator"
    assignee_id, target_role, who = None, None, ""
    if assign.startswith("user:"):
        try:
            uid = int(assign.split(":", 1)[1])
        except (ValueError, IndexError):
            uid = None
        usr = User.query.get(uid) if uid else None
        if not usr:
            flash("Xodim tanlanmadi", "error")
            return redirect(url_for("tasks.board"))
        assignee_id, who = usr.id, usr.name
    elif assign.startswith("role:"):
        target_role = assign.split(":", 1)[1]
        if target_role not in ROLES:
            flash("Rol noto'g'ri", "error")
            return redirect(url_for("tasks.board"))
        who = f"{ROLE_LABELS.get(target_role, target_role)} (jamoa)"
    else:
        flash("Kimga topshirilishini tanlang", "error")
        return redirect(url_for("tasks.board"))

    t = create_task(title=title, description=desc, assigner=u,
                    assignee_id=assignee_id, target_role=target_role,
                    priority=pr, due_date=due, is_auto=False)
    if t:
        log_event(u, "Yangi vazifa berildi", entity="task", entity_id=t.id,
                  summary=f"{title} → {who}")
        flash(f"✅ Vazifa «{who}»ga yuborildi — xabar bordi.", "success")
    else:
        flash("Vazifa yaratilmadi, qayta urinib ko'ring", "error")
    return redirect(url_for("tasks.board"))


# ── HOLATNI OLDINGA SURISH ────────────────────────────────────────
@bp.route("/tasks/<int:tid>/advance", methods=["POST"])
@login_required
def advance(tid):
    u = current_user()
    t = Task.query.get(tid)
    if not t:
        return redirect(url_for("tasks.board"))
    if not _is_responsible(u, t):
        flash("Bu vazifa sizga tegishli emas — faqat mas'ul xodim "
              "holatini o'zgartira oladi.", "error")
        return redirect(url_for("tasks.board"))
    new_status = request.form.get("status", "in_progress")
    if new_status not in VALID_STATUS:
        return redirect(url_for("tasks.board"))
    advance_task(tid, new_status, by_user=u)
    return redirect(request.referrer or url_for("tasks.board"))


@bp.route("/tasks/<int:tid>/move", methods=["POST"])
@login_required
def move(tid):
    """Drag & drop orqali ustun o'zgartirish (AJAX)."""
    u = current_user()
    t = Task.query.get(tid)
    if not t:
        return jsonify({"ok": False, "error": "Vazifa topilmadi"}), 404
    if not _is_responsible(u, t):
        return jsonify({"ok": False, "error": "Sizga tegishli emas"}), 403
    new_status = (request.form.get("status") or "").strip()
    if new_status not in ("new", "accepted", "in_progress", "done"):
        return jsonify({"ok": False, "error": "Noto'g'ri status"}), 400
    advance_task(tid, new_status, by_user=u)
    return jsonify({"ok": True, "status": new_status})


# ── TAYINLASH ─────────────────────────────────────────────────────
@bp.route("/tasks/<int:tid>/assign", methods=["POST"])
@login_required
def assign(tid):
    u = current_user()
    t = Task.query.get(tid)
    if not t:
        flash("Vazifa topilmadi", "error")
        return redirect(url_for("tasks.board"))
    if not _can_assign(u, t):
        flash("Bu vazifani tayinlash uchun ruxsat yo'q "
              "(faqat rahbar yoki topshiruvchi)", "error")
        return redirect(url_for("tasks.board"))

    raw_ids = request.form.getlist("assignee_id")
    if len(raw_ids) == 1 and "," in raw_ids[0]:
        raw_ids = raw_ids[0].split(",")
    new_ids = list(dict.fromkeys(
        int(x) for x in (s.strip() for s in raw_ids) if x.isdigit()))
    if not new_ids:
        flash("Xodim tanlanmadi", "error")
        return redirect(url_for("tasks.board"))

    by_id = {usr.id: usr for usr in User.query.filter(User.id.in_(new_ids)).all()}
    ordered = [by_id[i] for i in new_ids if i in by_id]
    if not ordered:
        flash("Xodimlar topilmadi", "error")
        return redirect(url_for("tasks.board"))
    primary, co = ordered[0], ordered[1:]

    old_name = t.assignee_name or "—"
    t.assignee_id = primary.id
    t.assignee_name = primary.name
    t.co_assignee_ids = ",".join(str(x.id) for x in co) if co else ""
    t.co_assignee_names = ", ".join(x.name for x in co) if co else ""
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error(f"task_assign commit xato (tid={tid}): {exc}")
        flash("Tayinlashда xato — qayta urinib ko'ring", "error")
        return redirect(url_for("tasks.board"))

    new_names = ", ".join(x.name for x in ordered)
    try:
        db.session.add(TaskActivity(
            task_id=t.id, user_id=u.id, user_name=u.name, kind="assignee",
            old_value=old_name, new_value=new_names,
            note=f"{u.name} tayinladi"
                 + (f" — {len(ordered)} ta xodim" if len(ordered) > 1 else "")))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning(f"TaskActivity assignee xato: {exc}")

    log_event(u, f"Vazifa tayinlandi → {new_names}", entity="task",
              entity_id=t.id, summary=t.title)

    co_note = f" + {len(co)} ta hamkor" if co else ""
    for usr in ordered:
        notify(user_id=usr.id, title=f"📌 Yangi vazifa: {t.title}",
               body=f"{u.name} sizni mas'ul qildi{co_note}"
                    + (f"\n🗓 Muddat: {t.due_date}" if t.due_date else ""),
               level="urgent", link=f"/tasks#task-{t.id}")

    if len(ordered) > 1:
        flash(f"✅ Vazifa {len(ordered)} ta xodimga tayinlandi: {new_names}",
              "success")
    else:
        flash(f"✅ Vazifa {primary.name}ga tayinlandi", "success")
    return redirect(url_for("tasks.board"))


# ── TAHRIRLASH ────────────────────────────────────────────────────
@bp.route("/tasks/<int:tid>/edit", methods=["POST"])
@login_required
def edit(tid):
    u = current_user()
    t = Task.query.get(tid)
    if not t:
        flash("Vazifa topilmadi", "error")
        return redirect(url_for("tasks.board"))
    if not _can_edit(u, t):
        flash("Bu vazifani tahrirlash uchun ruxsatingiz yo'q", "error")
        return redirect(url_for("tasks.board"))

    f = request.form
    changes = []
    new_title = (f.get("title") or "").strip()
    if new_title and new_title != t.title:
        changes.append(("title", t.title[:80], new_title[:80]))
        t.title = new_title[:200]
    new_desc = (f.get("description") or "").strip()
    if new_desc != (t.description or ""):
        changes.append(("description", (t.description or "")[:80], new_desc[:80]))
        t.description = new_desc
    new_due = (f.get("due_date") or "").strip()
    if new_due != (t.due_date or ""):
        changes.append(("due_date", t.due_date or "—", new_due or "—"))
        t.due_date = new_due
    new_pri = (f.get("priority") or "").strip()
    if new_pri in VALID_PRIORITY and new_pri != t.priority:
        changes.append(("priority", Task.PRIORITY_LABELS.get(t.priority, t.priority),
                        Task.PRIORITY_LABELS.get(new_pri, new_pri)))
        t.priority = new_pri
    try:
        new_prog = max(0, min(100, int(f.get("progress", t.progress or 0))))
        if new_prog != (t.progress or 0):
            changes.append(("progress", f"{t.progress or 0}%", f"{new_prog}%"))
            t.progress = new_prog
    except (ValueError, TypeError):
        pass

    if not changes:
        flash("Hech narsa o'zgartirilmadi", "info")
        return redirect(url_for("tasks.board"))
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error(f"task_edit commit xato (tid={tid}): {exc}")
        flash("Saqlashда xato — qayta urinib ko'ring", "error")
        return redirect(url_for("tasks.board"))

    try:
        for kind, old_v, new_v in changes:
            db.session.add(TaskActivity(
                task_id=t.id, user_id=u.id, user_name=u.name, kind=kind,
                old_value=str(old_v), new_value=str(new_v)))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning(f"TaskActivity edit log xato: {exc}")

    log_event(u, f"Vazifa tahrirlandi ({len(changes)} o'zgarish)", entity="task",
              entity_id=t.id, summary=t.title)
    if t.assignee_id and t.assignee_id != u.id:
        notify(user_id=t.assignee_id, title=f"✏️ Vazifa yangilandi: {t.title}",
               body=f"{u.name} {len(changes)} ta maydonni o'zgartirdi",
               level="info", link=f"/tasks#task-{t.id}")
    flash(f"✅ Vazifa yangilandi ({len(changes)} o'zgarish)", "success")
    return redirect(url_for("tasks.board"))


# ── IZOH (CHAT) ───────────────────────────────────────────────────
@bp.route("/tasks/<int:tid>/comment", methods=["POST"])
@login_required
def comment(tid):
    u = current_user()
    t = Task.query.get_or_404(tid)
    is_chat = request.headers.get("X-Requested-With") == "fetch"

    is_involved = (t.assigner_id == u.id or t.is_assignee(u.id)
                   or (t.target_role and u.role == t.target_role) or u.is_boss)
    if not is_involved:
        if is_chat:
            return "Bu vazifaga yozish ruxsati yo'q", 403
        flash("Bu vazifaga izoh yozish ruxsati yo'q", "error")
        return redirect(url_for("tasks.board"))

    body = (request.form.get("body") or "").strip()
    if not body:
        if is_chat:
            return _chat_partial(tid, u)
        flash("Izoh bo'sh bo'lmasin", "error")
        return redirect(url_for("tasks.board"))

    try:
        db.session.add(TaskComment(task_id=tid, user_id=u.id, user_name=u.name,
                                   user_role=u.role, body=body[:1000]))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error(f"TaskComment xato (tid={tid}): {exc}")
        if is_chat:
            return "Xabar saqlanmadi", 500
        flash("Izoh saqlanmadi", "error")
        return redirect(url_for("tasks.board"))

    # Barcha qiziquvchilarga signal (yozgan odam o'zidan tashqari)
    recipients = set()
    if t.assigner_id:
        recipients.add(t.assigner_id)
    recipients.update(t.all_assignee_ids())
    recipients.discard(u.id)

    title = f"💬 Izoh: {t.title}"
    short = f"{u.name}: {body[:120]}{'...' if len(body) > 120 else ''}"
    if recipients:
        for uid in recipients:
            notify(user_id=uid, title=title, body=short, level="info",
                   link=f"/tasks#task-{tid}", dedup=False)
    elif t.target_role and u.role != t.target_role:
        notify(role=t.target_role, title=title, body=short, level="info",
               link=f"/tasks#task-{tid}", dedup=False)

    if is_chat:
        return _chat_partial(tid, u)
    flash("Izoh yuborildi", "success")
    return redirect(url_for("tasks.board"))


def _chat_partial(tid, u):
    comments = [c.to_dict() for c in TaskComment.query.filter_by(
        task_id=tid).order_by(TaskComment.created_at.asc()).all()]
    return render_template("partials/task_chat.html", comments=comments,
                           me_id=u.id)


# ── O'CHIRISH / TOZALASH (admin) ──────────────────────────────────
@bp.route("/tasks/<int:tid>/delete", methods=["POST"])
@login_required
def delete(tid):
    u = current_user()
    if not (u and u.is_admin):
        flash("Vazifani o'chirish faqat rahbar huquqida", "error")
        return redirect(url_for("tasks.board"))
    t = Task.query.get(tid)
    if not t:
        flash("Vazifa topilmadi", "error")
        return redirect(url_for("tasks.board"))
    title = t.title
    TaskComment.query.filter_by(task_id=tid).delete()
    TaskActivity.query.filter_by(task_id=tid).delete()
    db.session.delete(t)
    db.session.commit()
    log_event(u, "Vazifa o'chirildi", entity="task", entity_id=tid, summary=title)
    flash(f"🗑 Vazifa o'chirildi: {title}", "success")
    return redirect(url_for("tasks.board"))


@bp.route("/tasks/clear-all", methods=["POST"])
@login_required
def clear_all():
    u = current_user()
    if not (u and u.is_admin):
        flash("Bu amal faqat rahbar uchun", "error")
        return redirect(url_for("tasks.board"))
    from models.communication import TaskWatcher
    n = Task.query.count()
    TaskComment.query.delete()
    TaskActivity.query.delete()
    TaskWatcher.query.delete()
    Task.query.delete()
    db.session.commit()
    log_event(u, f"Vazifalar to'liq tozalandi: {n} ta", entity="task")
    flash(f"🧹 Vazifalar tozalandi — {n} ta o'chirildi.", "success")
    return redirect(url_for("tasks.board"))


# ══════════════════════════════════════════════════════════════════
#  BILDIRISHNOMALAR — inbox + o'qildi belgilash
# ══════════════════════════════════════════════════════════════════
@bp.route("/notifications")
@login_required
def notifications():
    u = current_user()
    items = [n.to_dict() for n in get_notifications_for(u, limit=60)]
    return render_template("notifications.html", items=items,
                           unread=unread_count(u))


@bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notif_read_all():
    mark_all_read(current_user())
    return redirect(request.referrer or url_for("tasks.notifications"))


@bp.route("/notifications/<int:nid>/read", methods=["POST"])
@login_required
def notif_read(nid):
    mark_read(nid)
    if request.headers.get("X-Requested-With") == "fetch":
        return "", 204
    return redirect(request.referrer or url_for("tasks.notifications"))


@bp.route("/api/badge/notifications")
@login_required
def api_notif_badge():
    return jsonify({"count": unread_count(current_user())})
