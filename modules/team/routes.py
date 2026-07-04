"""Jamoa boshqaruvi — xodimlar (admin/operator/montajchi) faqat rahbar uchun.

Himoyalar: kod unikal va kamida 4 belgi; o'zini faolsizlantirib bo'lmaydi;
OXIRGI faol admin faolsizlantirilmaydi/rolini pasaytirib bo'lmaydi.
"""
import json
from datetime import date, datetime

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, Response)

from core.auth import admin_required, current_user
from database import db
from models.user import User, ROLES
from models.audit import AuditLog, record

bp = Blueprint("team", __name__)


@bp.route("/team/audit")
@admin_required
def audit():
    """Audit-log: kim, qachon, nima qilgani (moliya + jamoa amallari)."""
    action = (request.args.get("action") or "").strip()
    entity = (request.args.get("entity") or "").strip()
    q = AuditLog.query
    if action:
        q = q.filter_by(action=action)
    if entity:
        q = q.filter_by(entity=entity)
    rows = q.order_by(AuditLog.id.desc()).limit(300).all()
    return render_template("audit.html", rows=rows, action=action,
                           entity=entity)


@bp.route("/team/backup.json")
@admin_required
def backup():
    """Butun bazani JSON'ga eksport — off-platforma zaxira nusxa.

    Har deploy/baza yo'qolishiga qarshi himoya: rahbar istagan payt bir tugma
    bilan barcha ma'lumotni (mijozlar, bronlar, to'lovlar, moliya, montaj,
    jamoa) yuklab oladi. SQLite→Postgres ko'chirishда ham asqotadi.
    """
    def _val(v):
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        return v

    dump = {"_meta": {"app": "Jalinga Studio",
                      "exported_at": datetime.utcnow().isoformat() + "Z",
                      "format": 1}}
    # Barcha ro'yxatga olingan jadvallar (models/__init__ orqali) — generic
    for table in db.metadata.sorted_tables:
        rows = db.session.execute(table.select()).mappings().all()
        dump[table.name] = [{k: _val(v) for k, v in r.items()} for r in rows]

    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M")
    body = json.dumps(dump, ensure_ascii=False, indent=1)
    return Response(body, mimetype="application/json", headers={
        "Content-Disposition": f'attachment; filename="jalinga-backup-{stamp}.json"'})

ROLE_LABELS = {"admin": "👑 Rahbar", "operator": "🎥 Operator",
               "montaj": "✂️ Montajchi", "buxgalter": "🧮 Buxgalter"}


def _last_active_admin(u):
    """u — tizimdagi yagona faol adminmi."""
    return (u.role == "admin" and User.query.filter_by(
        role="admin", is_active=True).filter(User.id != u.id).count() == 0)


@bp.route("/team")
@admin_required
def index():
    rows = User.query.order_by(User.is_active.desc(), User.role.asc(),
                               User.name.asc()).all()
    return render_template("team.html", team=rows, roles=ROLES,
                           role_labels=ROLE_LABELS)


@bp.route("/team/save", methods=["POST"])
@admin_required
def save():
    me = current_user()
    f = request.form
    uid = (f.get("id") or "").strip()
    u = User.query.get(int(uid)) if uid.isdigit() else None
    is_new = u is None

    name = (f.get("name") or "").strip()[:120]
    code = (f.get("code") or "").strip()[:12]
    role = f.get("role") if f.get("role") in ROLES else "operator"
    active = bool(f.get("is_active"))

    if not name:
        flash("⛔ Ism kiritilishi shart", "error")
        return redirect(url_for("team.index"))
    if is_new or code:
        if len(code) < 6 or not code.isdigit():
            flash("⛔ Kod kamida 6 ta raqamdan iborat bo'lsin (xavfsizlik)", "error")
            return redirect(url_for("team.index"))
        dup = User.query.filter_by(code=code).first()
        if dup and (is_new or dup.id != u.id):
            flash(f"⛔ Bu kod band ({dup.name}). Boshqa kod tanlang.", "error")
            return redirect(url_for("team.index"))

    if is_new:
        u = User(name=name, code=code, role=role, is_active=True)
        db.session.add(u)
        record("create", "user", f"{name} ({role})")
        db.session.commit()
        flash(f"✅ {name} qo'shildi ({ROLE_LABELS.get(role, role)}). "
              f"Kirish kodi: {code}", "success")
        return redirect(url_for("team.index"))

    # ── Tahrirlash himoyalari ──
    if u.id == me.id and not active:
        flash("⛔ O'zingizni faolsizlantira olmaysiz", "error")
        return redirect(url_for("team.index"))
    if _last_active_admin(u) and (role != "admin" or not active):
        flash("⛔ Tizimda kamida bitta faol rahbar qolishi shart", "error")
        return redirect(url_for("team.index"))

    u.name = name
    if code:
        u.code = code
    u.role = role
    u.is_active = active
    record("update", "user",
           f"{u.name} → {role}{' (kod o‘zgardi)' if code else ''}"
           f"{'' if active else ' — nofaol'}")
    db.session.commit()
    flash(f"✅ {u.name} yangilandi", "success")
    return redirect(url_for("team.index"))
