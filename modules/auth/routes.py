from flask import Blueprint, render_template, request, redirect, url_for, flash

from core.auth import login_by_code, logout_user, current_user

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        u, err = login_by_code(request.form.get("code"))
        if err:
            flash(err, "error")
            return render_template("login.html")
        nxt = request.form.get("next") or url_for("dashboard.index")
        return redirect(nxt)
    return render_template("login.html")


@bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
