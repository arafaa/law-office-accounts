# -*- coding: utf-8 -*-
"""تطبيق ويب محلي: شغّله ثم افتح http://127.0.0.1:8765 (يفتح المتصفح تلقائياً)."""
import io, os, sys, socket, tempfile, threading, traceback, webbrowser, time
from datetime import timedelta
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    from flask import Flask, jsonify, request, send_file, send_from_directory, abort, session, redirect, g
except ImportError:
    print("Flask is not installed. Run install.bat first.  /  مكتبة Flask غير مثبتة، شغّل install.bat أولاً")
    sys.exit(1)
import core

from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__, static_folder="static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # للعمل خلف نفق HTTPS
PORT = 8765
core.init_db()
app.secret_key = core.secret_key()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("CT_HTTPS") == "1",
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30), MAX_CONTENT_LENGTH=60 * 1024 * 1024)
PUBLIC = {"/login", "/api/login", "/api/auth-state", "/api/setup", "/manifest.webmanifest", "/sw.js"}
FAILS = {}


def _throttled(key, limit):
    now = time.time()
    FAILS[key] = [t for t in FAILS.get(key, []) if now - t < 600]
    return len(FAILS[key]) >= limit


def _is_local():
    return request.remote_addr in ("127.0.0.1", "::1") and not any(
        h in request.headers for h in ("X-Forwarded-For", "CF-Connecting-IP", "Forwarded"))


def _can(u):
    a = u["role"] == "admin"
    return {"admin": a, "write": a or u["role"] == "editor", "del": a, "acc": a or u["see_acc"]}


@app.before_request
def guard():
    p, m = request.path, request.method
    # يمنع أي موقع آخر مفتوح في المتصفح من تعديل بياناتك
    if m != "GET" and request.headers.get("X-Requested-With") != "law":
        abort(403)
    if p in PUBLIC or p.startswith("/icons/"):
        return
    uid = session.get("uid")
    u = core.user_get(uid) if uid else None
    if not u or not u["active"]:
        if p.startswith("/api/"):
            return jsonify(error="يلزم تسجيل الدخول"), 401
        return redirect("/login")
    g.user = u
    core.set_actor(u["username"])
    k = _can(u)
    if p.startswith("/api/acc/"):
        ok = (k["admin"] if p in ("/api/acc/totals", "/api/acc/report-unpaid") else k["acc"]) if m == "GET" else k["admin"]   # الإجماليات للمدير فقط
    elif p.startswith(("/api/users", "/api/backup", "/api/restore")) or p in ("/api/import", "/api/export"):
        ok = k["admin"]
    elif p.startswith("/api/push") or p in ("/api/me", "/api/logout"):
        ok = True
    elif m != "GET":
        ok = k["del"] if m == "DELETE" else k["write"]
    else:
        ok = True
    if not ok:
        return jsonify(error="ليست لديك صلاحية لهذا الإجراء"), 403


ACC_TXT = "عملاء مستوردون: %(clients)d | قضايا جديدة: %(cases_new)d | دفعات: %(payments)d | مصروفات: %(expenses)d | متجاهَل (موجود مسبقاً): %(skipped)d"


@app.errorhandler(ValueError)
def bad(e):
    return jsonify(error=str(e)), 400


@app.get("/login")
def login_page():
    return send_from_directory("static", "login.html")


@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest", mimetype="application/manifest+json")


@app.get("/sw.js")
def sw():
    r = send_from_directory("static", "sw.js", mimetype="application/javascript")
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.get("/icons/<path:f>")
def icons(f):
    return send_from_directory("static/icons", f)


@app.get("/api/auth-state")
def auth_state():
    return jsonify(need_setup=core.users_count() == 0, can_setup=_is_local())


def _login(u):
    session.clear()
    session.permanent = True
    session["uid"] = u["id"]


@app.post("/api/setup")
def setup():
    if core.users_count() or not _is_local():
        abort(403)
    d = request.json or {}
    core.user_create(d.get("username"), d.get("password"), "admin")
    _login(core.user_login(d.get("username"), d.get("password")))
    return jsonify(ok=True)


@app.post("/api/login")
def login():
    d = request.json or {}
    name = (d.get("username") or "").strip().lower()
    kn, ki = ("u", name), ("ip", request.remote_addr)
    if _throttled(kn, 5) or _throttled(ki, 20):
        return jsonify(error="محاولات كثيرة خاطئة. انتظر 10 دقائق ثم حاول مجدداً."), 429
    u = core.user_login(d.get("username"), d.get("password"))
    if not u:
        FAILS[kn].append(time.time())
        FAILS[ki].append(time.time())
        return jsonify(error="اسم المستخدم أو كلمة المرور غير صحيحة"), 401
    FAILS.pop(kn, None)
    _login(u)
    return jsonify(ok=True)


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/me")
def me():
    return jsonify(dict(g.user, can=_can(g.user)))


@app.get("/api/users")
def users_list():
    return jsonify(core.user_list())


@app.post("/api/users")
def users_add():
    d = request.json or {}
    return jsonify(id=core.user_create(d.get("username"), d.get("password"), d.get("role"), d.get("see_acc")))


@app.put("/api/users/<int:uid>")
def users_edit(uid):
    core.user_update(uid, request.json or {})
    return jsonify(ok=True)


@app.delete("/api/users/<int:uid>")
def users_del(uid):
    if uid == g.user["id"]:
        raise ValueError("لا يمكنك حذف حسابك الحالي")
    core.user_delete(uid)
    return jsonify(ok=True)


@app.get("/api/push/key")
def push_key():
    try:
        return jsonify(key=core.vapid_keys()[1], available=core.push_available())
    except Exception:
        return jsonify(key=None, available=False)


@app.post("/api/push/subscribe")
def push_sub():
    core.push_subscribe(g.user["id"], request.json)
    return jsonify(ok=True)


@app.post("/api/push/unsubscribe")
def push_unsub():
    core.push_unsubscribe((request.json or {}).get("endpoint"))
    return jsonify(ok=True)


@app.post("/api/push/test")
def push_test():
    core.push_all("🔔 إشعار تجريبي", "الإشعارات تعمل على هذا الجهاز ✔", "/", only_user=g.user["id"])
    return jsonify(ok=True)


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/api/schema")
def schema():
    return jsonify(core.get_schema())


@app.get("/api/cases-list")
def cases_list():
    return jsonify(core.case_choices())


@app.get("/api/dashboard")
def dashboard():
    return jsonify(core.dashboard())


@app.post("/api/import")
def do_import():
    f = request.files.get("file")
    if not f:
        raise ValueError("لم يتم اختيار ملف")
    fd, tmp = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        f.save(tmp)
        core.backup()
        st = core.import_any(tmp)
        return jsonify(dict(st, text=core.summary_text(st)))
    finally:
        os.unlink(tmp)


@app.get("/api/export")
def do_export():
    fd, tmp = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        core.export_excel(tmp)
        with open(tmp, "rb") as fh:
            data = io.BytesIO(fh.read())
    finally:
        os.unlink(tmp)
    return send_file(data, as_attachment=True, download_name="القضايا_تصدير.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/backup")
def do_backup():
    return jsonify(path=str(core.backup()))


@app.post("/api/tasks/<int:rid>/done")
def task_done(rid):
    core.set_done(rid, bool((request.json or {}).get("done", True)))
    return jsonify(ok=True)


@app.get("/api/acc/list")
def acc_list():
    return jsonify(core.acc_list())


@app.get("/api/acc/totals")
def acc_totals():
    return jsonify(core.acc_totals())


@app.get("/api/acc/report-unpaid")
def acc_report_unpaid():
    return jsonify(core.acc_unpaid_report())


@app.get("/api/acc/case/<int:cid>")
def acc_case(cid):
    return jsonify(core.acc_case(cid))


@app.route("/api/acc/settings", methods=["GET", "PUT"])
def acc_settings():
    return jsonify(core.acc_settings(request.json if request.method == "PUT" else None))


@app.post("/api/acc/contract-new/<int:cid>")
def acc_contract_new(cid):
    return jsonify(id=core.acc_save_contract(cid, request.json or {}))


@app.put("/api/acc/contract/<int:kid>")
def acc_contract_edit(kid):
    core.acc_save_contract(None, request.json or {}, kid)
    return jsonify(ok=True)


@app.post("/api/acc/payment/<int:cid>")
def acc_payment(cid):
    return jsonify(core.acc_add_payment(cid, request.json or {}))


@app.post("/api/acc/expense/<int:cid>")
def acc_expense(cid):
    core.acc_add_expense(cid, request.json or {})
    return jsonify(ok=True)


@app.post("/api/acc/expense-pay/<int:eid>")
def acc_expense_pay(eid):
    core.acc_pay_expense(eid, (request.json or {}).get("amt"))
    return jsonify(ok=True)


@app.post("/api/acc/expense-lawyer-pay/<int:eid>")
def acc_expense_lawyer_pay(eid):
    core.acc_lawyer_pay_expense(eid, (request.json or {}).get("amt"))
    return jsonify(ok=True)


@app.post("/api/acc/remit")
def acc_remit():
    return jsonify(core.acc_remit(request.json or {}))


@app.delete("/api/acc/<kind>/<int:rid>")
def acc_del(kind, rid):
    if kind not in ("payment", "expense", "contract"):
        abort(404)
    core.acc_delete(kind, rid)
    return jsonify(ok=True)


@app.post("/api/acc/import-json")
def acc_import():
    core.backup()
    st = core.import_accounts_json(request.json)
    return jsonify(dict(st, text=ACC_TXT % st))


@app.post("/api/acc/import-db")
def acc_import_db():
    data = request.get_data()
    if not data.startswith(b"SQLite format 3"):
        raise ValueError("الملف ليس قاعدة بيانات SQLite (.db)")
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        d = core.accounts_from_db(tmp)
        core.backup()
        st = core.import_accounts_json(d)
    finally:
        os.unlink(tmp)
    return jsonify(dict(st, text=ACC_TXT % st))


def _backup_names():
    return [b["name"] for b in core.list_backups()]


@app.get("/api/backups")
def backups_list():
    return jsonify(core.list_backups())


@app.get("/api/backups/<name>")
def backup_download(name):
    if name not in _backup_names():
        abort(404)
    return send_from_directory(core.BACKUP_DIR, name, as_attachment=True)


@app.post("/api/restore/<name>")
def restore_named(name):
    if name not in _backup_names():
        abort(404)
    return jsonify(ok=True, safety=core.restore_from(core.BACKUP_DIR / name))


@app.post("/api/restore-upload")
def restore_upload():
    data = request.get_data()
    if not data.startswith(b"SQLite format 3"):
        raise ValueError("الملف ليس نسخة احتياطية (.db)")
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        safety = core.restore_from(tmp)
    finally:
        os.unlink(tmp)
    return jsonify(ok=True, safety=safety)


@app.get("/api/<table>")
def list_(table):
    if table not in core._SCHEMA:
        abort(404)
    return jsonify(core.list_rows(table))


@app.post("/api/<table>")
def create(table):
    if table not in core._SCHEMA:
        abort(404)
    return jsonify(id=core.save(table, request.json))


@app.put("/api/<table>/<int:rid>")
def update(table, rid):
    if table not in core._SCHEMA:
        abort(404)
    core.save(table, request.json, rid)
    return jsonify(ok=True)


@app.delete("/api/<table>/<int:rid>")
def remove(table, rid):
    if table not in core._SCHEMA:
        abort(404)
    core.delete(table, rid)
    return jsonify(ok=True)


def free_port(start=8765):
    for p in range(start, start + 20):
        with socket.socket() as sk:
            if sk.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


@app.errorhandler(Exception)
def crash(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    with open(core.BASE / "error.log", "a", encoding="utf-8") as fh:
        fh.write(traceback.format_exc() + "\n")
    return jsonify(error="%s: %s" % (type(e).__name__, e)), 500


def lan_ips():
    ips = set()
    try:
        ips.update(a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


if __name__ == "__main__":
    try:
        core.init_db()
        core.auto_backup()
        port = free_port()
        if not os.environ.get("CT_NO_BROWSER"):
            threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:%d" % port)).start()
        host = os.environ.get("CT_HOST", "127.0.0.1")   # 0.0.0.0 = إتاحة البرنامج لأجهزة الشبكة
        print("Running at http://127.0.0.1:%d  (close this window to stop)" % port)
        if host != "127.0.0.1":
            print("Network access ON. From other devices on the same network open:")
            for ip in lan_ips():
                print("    http://%s:%d" % (ip, port))
            print("If it does not open: run open_firewall.bat once as Administrator.")
            if port != 8765:
                print("NOTE: port 8765 was busy (an old window is still open) -> using %d" % port)
        try:
            from waitress import serve          # خادم أنسب للتشغيل المستمر من خادم Flask التجريبي
            serve(app, host=host, port=port, threads=8)
        except ImportError:
            app.run(host=host, port=port, debug=False)
    except Exception:
        with open(core.BASE / "error.log", "a", encoding="utf-8") as fh:
            fh.write(traceback.format_exc() + "\n")
        traceback.print_exc()
        print("\nاحفظ نص الخطأ أعلاه أو الملف error.log وأرسله للمساعدة")
        input()
