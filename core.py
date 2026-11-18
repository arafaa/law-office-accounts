# -*- coding: utf-8 -*-
"""الطبقة المشتركة: قاعدة البيانات + المنطق. يستخدمها تطبيق الويب."""
import os, sqlite3, datetime as dt
from contextlib import contextmanager
from pathlib import Path

BASE = Path(os.environ.get("CASES_HOME") or Path(__file__).resolve().parent)
DB_PATH = BASE / "cases.db"
BACKUP_DIR = BASE / "backups"

WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
TASK_TYPES = ["تصوير حكم", "طعن", "تصوير ملف"]          # المهام الثلاث فقط
APPEAL = "طعن"
APPEAL_KINDS = ["استئناف", "تمييز", "إشكال", "رفع دعوى"]
STATUSES = ["قيد التنفيذ", "منجز", "مؤجل"]
DONE = "منجز"
# (يُطبَّق على نوع الطعن فقط) عدد الأيام لحساب "آخر موعد" تلقائياً من تاريخ الحكم (استنتجتها من جدولك: 30 للاستئناف، 60 للتمييز)
DEADLINE_DAYS = {"استئناف": 30, "تمييز": 60}
WARN_DAYS = 7
DEFAULT_COURTS = ["المحكمة الكلية", "محكمة الاستئناف", "محكمة التمييز", "محكمة حولي", "محكمة الأحمدي", "محكمة الجهراء", "مبارك الكبير"]

SQL = """
CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY, code INTEGER, client TEXT NOT NULL, case_no TEXT,
  court TEXT, category TEXT, opponent TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  date TEXT NOT NULL, notes TEXT);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id) ON DELETE CASCADE,
  type TEXT, appeal_kind TEXT, judgment_date TEXT, deadline TEXT, place TEXT, status TEXT DEFAULT 'قيد التنفيذ', notes TEXT);
CREATE TABLE IF NOT EXISTS classes(court TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, pw_hash TEXT NOT NULL,
  role TEXT NOT NULL, see_acc INTEGER DEFAULT 0, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS push_subs(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, endpoint TEXT NOT NULL UNIQUE, p256dh TEXT, auth TEXT);
CREATE TABLE IF NOT EXISTS contracts(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  title TEXT, total REAL DEFAULT 0, monthly REAL DEFAULT 0, cnt INTEGER DEFAULT 0, start TEXT);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  rcpt_no INTEGER, date TEXT, amt REAL, note TEXT);
CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  date TEXT, descr TEXT, amt REAL, paid REAL DEFAULT 0);
"""

# ---------- تعريف الجداول والحقول (يُستخدم لبناء النماذج في الواجهتين) ----------
LAWYERS = ["خليفة الرديني", "دانة الخبيزي"]     # المحامون المتاحون (أضف اسماً جديداً هنا ليظهر في القوائم)

_SCHEMA = {
    "cases": {"title": "القضايا", "single": "قضية",
        "fields": [
            {"k": "code", "l": "الكود", "t": "int"},
            {"k": "client", "l": "الموكل", "t": "text", "req": True},
            {"k": "case_no", "l": "رقم القضية", "t": "text"},
            {"k": "lawyer", "l": "المحامي المسؤول", "t": "choice", "choices": LAWYERS},
            {"k": "court", "l": "المحكمة", "t": "choice"},
            {"k": "category", "l": "التصنيف / الدائرة", "t": "combo"},
            {"k": "opponent", "l": "الخصم", "t": "text"},
            {"k": "phone", "l": "الهاتف / وسائل التواصل", "t": "text"},
            {"k": "notes", "l": "ملاحظات", "t": "area"}],
        "cols": [{"k": "code", "l": "الكود", "w": 70}, {"k": "client", "l": "الموكل", "w": 240}, {"k": "lawyer", "l": "المحامي", "w": 120},
                 {"k": "case_no", "l": "رقم القضية", "w": 110}, {"k": "court", "l": "المحكمة", "w": 130},
                 {"k": "category", "l": "التصنيف", "w": 150}, {"k": "next_session", "l": "الجلسة القادمة", "t": "date", "w": 110},
                 {"k": "open_tasks", "l": "مهام مفتوحة", "w": 90}]},
    "sessions": {"title": "الجلسات", "single": "جلسة",
        "fields": [
            {"k": "case_id", "l": "القضية", "t": "case", "req": True},
            {"k": "date", "l": "تاريخ الجلسة", "t": "date", "req": True},
            {"k": "notes", "l": "ملاحظات", "t": "area"}],
        "cols": [{"k": "code", "l": "الكود", "w": 60}, {"k": "case_no", "l": "رقم القضية", "w": 110}, {"k": "client", "l": "الموكل", "w": 230},
                 {"k": "weekday", "l": "اليوم", "w": 90}, {"k": "date", "l": "التاريخ", "t": "date", "w": 100},
                 {"k": "days_left", "l": "المتبقي", "t": "sdays", "w": 90}, {"k": "notes", "l": "ملاحظات", "w": 240}]},
    "tasks": {"title": "المهام", "single": "مهمة",
        "fields": [
            {"k": "case_id", "l": "القضية", "t": "case"},
            {"k": "type", "l": "نوع المهمة", "t": "choice", "choices": TASK_TYPES, "req": True},
            {"k": "appeal_kind", "l": "نوع الطعن", "t": "choice", "choices": APPEAL_KINDS, "only": [APPEAL]},
            {"k": "judgment_date", "l": "تاريخ الحكم", "t": "date"},
            {"k": "deadline", "l": "آخر موعد (تصوير الملف: اتركه فارغاً ليؤخذ من الجلسة القادمة)", "t": "date", "only": [APPEAL, "تصوير ملف"]},
            {"k": "place", "l": "المكان / الجهة", "t": "text"},
            {"k": "status", "l": "الحالة", "t": "choice", "choices": STATUSES},
            {"k": "notes", "l": "ملاحظات", "t": "area"}],
        "cols": [{"k": "code", "l": "الكود", "w": 60}, {"k": "case_no", "l": "رقم القضية", "w": 110}, {"k": "client", "l": "الموكل", "w": 200},
                 {"k": "type", "l": "المهمة", "w": 90}, {"k": "appeal_kind", "l": "نوع الطعن", "w": 90},
                 {"k": "judgment_date", "l": "تاريخ الحكم", "t": "date", "w": 100},
                 {"k": "deadline", "l": "آخر موعد", "t": "date", "w": 100}, {"k": "days_left", "l": "المتبقي", "t": "tdays", "w": 100},
                 {"k": "status", "l": "الحالة", "w": 90}, {"k": "place", "l": "المكان", "w": 110}, {"k": "notes", "l": "ملاحظات", "w": 180}]},
}


def get_schema():
    with db() as c:
        cl = c.execute("SELECT court, category FROM classes").fetchall()
    classes = {}
    for r in cl:
        classes.setdefault(r["court"], []).append(r["category"])
    courts = list(classes) or list(DEFAULT_COURTS)
    import copy
    s = copy.deepcopy(_SCHEMA)
    for f in s["cases"]["fields"]:
        if f["k"] == "court":
            f["choices"] = courts
    s["classes"] = classes
    s["dash"] = DASH
    s["meta"] = {"warn_days": WARN_DAYS, "deadline_days": DEADLINE_DAYS, "done": DONE, "appeal": APPEAL}
    return s


# ---------- التواريخ ----------
def today():
    return dt.date.today()


def parse_date(v):
    """يقبل 25/11/2026 أو 2026-11-25 أو كائن تاريخ، ويعيد صيغة ISO."""
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    s = str(v).strip().replace("-", "/").replace(".", "/")
    if not s:
        return None
    p = s.split("/")
    try:
        if len(p) == 3:
            y, m, d = (p[0], p[1], p[2]) if len(p[0]) == 4 else (p[2], p[1], p[0])
            return dt.date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        pass
    raise ValueError("تاريخ غير صالح: %s — اكتبه بالشكل 25/11/2026" % v)


def fmt_date(iso):
    return "/".join(reversed(iso.split("-"))) if iso else ""


def days_between(iso):
    return (dt.date.fromisoformat(iso) - today()).days if iso else None


def weekday_name(iso):
    return WEEKDAYS[dt.date.fromisoformat(iso).weekday()] if iso else ""


def calc_deadline(appeal_kind, judgment_iso):
    n = DEADLINE_DAYS.get(appeal_kind)
    if n and judgment_iso:
        return (dt.date.fromisoformat(judgment_iso) + dt.timedelta(days=n)).isoformat()
    return None


def days_text(n, kind="t"):
    if n is None:
        return ""
    if n < 0:
        return "انقضت" if kind == "s" else "متأخر %d يوم" % -n
    return "اليوم" if n == 0 else "غداً" if n == 1 else "%d يوم" % n


def cell_text(col, row):
    v = row.get(col["k"])
    t = col.get("t")
    if t == "date":
        return fmt_date(v) + (" (جلسة)" if col["k"] == "deadline" and row.get("deadline_auto") else "")
    if t in ("sdays", "tdays"):
        return days_text(v, "s" if t == "sdays" else "t")
    return "" if v is None else str(v)


# ---------- قاعدة البيانات ----------
@contextmanager
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def migrate(c):
    """ترقية قاعدة بيانات قديمة: إضافة عمود نوع الطعن وتحويل الأنواع القديمة إلى الأنواع الثلاثة."""
    sql = (c.execute("SELECT sql FROM sqlite_master WHERE name='contracts'").fetchone() or {"sql": ""})["sql"] or ""
    if "UNIQUE" in sql.upper():     # ترقية: السماح بأكثر من عقد للموكل الواحد
        import shutil
        if DB_PATH.exists():
            shutil.copy2(DB_PATH, DB_PATH.with_name("cases_before_multi_contracts_%s.db" % dt.date.today().strftime("%Y%m%d")))
        c.execute("ALTER TABLE contracts RENAME TO contracts_old")
        c.execute("CREATE TABLE contracts(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,"
                  " title TEXT, total REAL DEFAULT 0, monthly REAL DEFAULT 0, cnt INTEGER DEFAULT 0, start TEXT)")
        c.execute("INSERT INTO contracts(id,case_id,total,monthly,cnt,start) SELECT id,case_id,total,monthly,cnt,start FROM contracts_old")
        c.execute("DROP TABLE contracts_old")
    if "contract_id" not in [r["name"] for r in c.execute("PRAGMA table_info(payments)")]:
        c.execute("ALTER TABLE payments ADD COLUMN contract_id INTEGER")
        c.execute("UPDATE payments SET contract_id=(SELECT id FROM contracts k WHERE k.case_id=payments.case_id)"
                  " WHERE (SELECT COUNT(*) FROM contracts k WHERE k.case_id=payments.case_id)=1")
    c.execute("DROP TABLE IF EXISTS lawyer_remits")     # سجل دفعات المحامي أُلغي بطلب المستخدم (الأرصدة محفوظة في المصروفات نفسها)
    if "lawyer_paid" not in [r["name"] for r in c.execute("PRAGMA table_info(expenses)")]:
        c.execute("ALTER TABLE expenses ADD COLUMN lawyer_paid REAL DEFAULT 0")   # ما سدّده المحامي للمدير
    if "lawyer" not in [r["name"] for r in c.execute("PRAGMA table_info(cases)")]:
        c.execute("ALTER TABLE cases ADD COLUMN lawyer TEXT")
    if "phone" not in [r["name"] for r in c.execute("PRAGMA table_info(cases)")]:
        c.execute("ALTER TABLE cases ADD COLUMN phone TEXT")
    if "appeal_kind" not in [r["name"] for r in c.execute("PRAGMA table_info(tasks)")]:
        c.execute("ALTER TABLE tasks ADD COLUMN appeal_kind TEXT")
    for old, kind in {"عمل استئناف": "استئناف", "عمل تمييز": "تمييز", "عمل إشكال": "إشكال", "رفع دعوى": "رفع دعوى"}.items():
        c.execute("UPDATE tasks SET type=?, appeal_kind=? WHERE type=?", (APPEAL, kind, old))
    for r in c.execute("SELECT id, type, deadline, judgment_date, notes FROM tasks WHERE type NOT IN (?,?,?)", tuple(TASK_TYPES)).fetchall():
        if r["type"] == "أخرى" and "استئناف" in (r["notes"] or ""):
            c.execute("UPDATE tasks SET type=?, appeal_kind='استئناف', deadline=NULL WHERE id=?", (APPEAL, r["id"]))
            continue
        new = TASK_TYPES[0] if (r["type"] == "أخرى" and r["judgment_date"]) else TASK_TYPES[2]
        parts = [x for x in ((r["type"] if r["type"] != "أخرى" else ""), r["notes"] or "",
                             ("موعد سابق " + fmt_date(r["deadline"])) if r["deadline"] else "") if x]
        c.execute("UPDATE tasks SET type=?, deadline=NULL, notes=? WHERE id=?", (new, " — ".join(parts) or None, r["id"]))


def init_db():
    with db() as c:
        c.executescript(SQL)
        migrate(c)


def list_rows(table, case_id=None):
    q = {"cases": "SELECT c.*, (SELECT MIN(date) FROM sessions s WHERE s.case_id=c.id AND s.date>=?) AS next_session,"
                  " (SELECT COUNT(*) FROM tasks k WHERE k.case_id=c.id AND k.status!='منجز') AS open_tasks FROM cases c ORDER BY c.code",
         "sessions": "SELECT s.*, c.code, c.client, c.case_no, c.lawyer FROM sessions s JOIN cases c ON c.id=s.case_id ORDER BY s.date",
         "tasks": "SELECT k.*, c.code, c.client, c.case_no, c.lawyer FROM tasks k LEFT JOIN cases c ON c.id=k.case_id ORDER BY k.deadline IS NULL, k.deadline"}[table]
    with db() as c:
        rows = [dict(r) for r in c.execute(q, (today().isoformat(),) if table == "cases" else ())]
    if case_id is not None:
        rows = [r for r in rows if r.get("id" if table == "cases" else "case_id") == case_id]
    nxt = {}
    if table == "tasks":
        with db() as c:
            nxt = {x["case_id"]: x["d"] for x in c.execute(
                "SELECT case_id, MIN(date) d FROM sessions WHERE date>=? GROUP BY case_id", (today().isoformat(),))}
    for r in rows:
        if table == "sessions":
            n = days_between(r["date"])
            r["weekday"], r["days_left"] = weekday_name(r["date"]), n
            r["lv"] = "past" if n < 0 else "warn" if n <= WARN_DAYS else ""
        elif table == "tasks":
            if r["type"] == TASK_TYPES[2] and not r["deadline"] and r["case_id"] in nxt:
                r["deadline"], r["deadline_auto"] = nxt[r["case_id"]], True   # موعد تصوير الملف = الجلسة القادمة
            done = r["status"] == DONE
            n = None if done or not r["deadline"] else days_between(r["deadline"])
            r["days_left"] = n
            r["lv"] = "done" if done else "bad" if (n is not None and n < 0) else "warn" if (n is not None and n <= WARN_DAYS) else ""
        else:
            r["lv"] = ""
    return rows


def case_choices():
    with db() as c:
        return [{"id": r["id"], "label": " | ".join(x for x in (str(r["code"]) if r["code"] is not None else "", r["client"], r["case_no"] or "") if x)}
                for r in c.execute("SELECT id, code, client, case_no FROM cases ORDER BY code IS NULL, code")]


def save(table, data, rid=None):
    fields = _SCHEMA[table]["fields"]
    vals = {}
    for f in fields:
        v = data.get(f["k"])
        if isinstance(v, str):
            v = v.strip()
        if v in ("", None):
            v = None
        elif f["t"] == "date":
            v = parse_date(v)
        elif f["t"] in ("int", "case"):
            v = int(v)
        if f.get("req") and v is None:
            raise ValueError('الحقل "%s" مطلوب' % f["l"])
        vals[f["k"]] = v
    if table == "cases" and vals.get("lawyer") and vals["lawyer"] not in LAWYERS:
        raise ValueError("المحامي المسؤول غير معروف")
    if table == "tasks":
        if vals["type"] != APPEAL:
            vals["appeal_kind"] = None
        if vals["type"] == TASK_TYPES[0]:          # تصوير حكم: بلا موعد
            vals["deadline"] = None
        elif vals["type"] == APPEAL and not vals["deadline"]:
            vals["deadline"] = calc_deadline(vals["appeal_kind"], vals["judgment_date"])
        vals["status"] = vals["status"] or STATUSES[0]
    keys = list(vals)
    old_status = None
    with db() as c:
        if rid:
            if table == "tasks":
                r0 = c.execute("SELECT status FROM tasks WHERE id=?", (rid,)).fetchone()
                old_status = r0["status"] if r0 else None
            c.execute("UPDATE %s SET %s WHERE id=?" % (table, ",".join(k + "=?" for k in keys)), [vals[k] for k in keys] + [rid])
        else:
            rid = c.execute("INSERT INTO %s(%s) VALUES(%s)" % (table, ",".join(keys), ",".join("?" * len(keys))),
                            [vals[k] for k in keys]).lastrowid
    if table == "tasks" and old_status and old_status != DONE and vals["status"] == DONE:
        _task_done_notice(rid)
    return rid


def delete(table, rid):
    with db() as c:
        if table == "cases" and c.execute("SELECT 1 FROM payments WHERE case_id=? UNION SELECT 1 FROM expenses WHERE case_id=?", (rid, rid)).fetchone():
            raise ValueError("لا يمكن حذف قضية لها دفعات أو مصروفات في الحسابات. احذفها من تبويب الحسابات أولاً.")
        c.execute("DELETE FROM %s WHERE id=?" % table, (rid,))


def set_done(rid, done=True):
    with db() as c:
        r0 = c.execute("SELECT status FROM tasks WHERE id=?", (rid,)).fetchone()
        c.execute("UPDATE tasks SET status=? WHERE id=?", (DONE if done else STATUSES[0], rid))
    if done and r0 and r0["status"] != DONE:
        _task_done_notice(rid)


def _pick(table, keys):
    by = {c["k"]: c for c in _SCHEMA[table]["cols"]}
    return [by[k] for k in keys]


SESSION_DAYS = 30
DASH = [
    {"key": "judgments", "title": "📄 تصوير الأحكام", "table": "tasks",
     "cols": _pick("tasks", ["code", "case_no", "client", "judgment_date", "place", "status", "notes"])},
    {"key": "files", "title": "📁 تصوير الملفات (قبل موعد الجلسة)", "table": "tasks",
     "cols": _pick("tasks", ["code", "case_no", "client", "deadline", "days_left", "place", "status", "notes"])},
    {"key": "appeals", "title": "⚖️ مواعيد الطعون", "table": "tasks",
     "cols": _pick("tasks", ["code", "case_no", "client", "appeal_kind", "judgment_date", "deadline", "days_left", "status", "notes"])},
    {"key": "sessions", "title": "📅 الجلسات القادمة (%d يوماً)" % SESSION_DAYS, "table": "sessions",
     "cols": _pick("sessions", ["code", "case_no", "client", "weekday", "date", "days_left", "notes"])},
]


def dashboard():
    """الصفحة الرئيسية: المهام المفتوحة مقسمة حسب النوع (الأقرب موعداً أولاً)، ثم الجلسات."""
    opn = [t for t in list_rows("tasks") if t["status"] != DONE]
    key = lambda t: (t["days_left"] is None, t["days_left"] or 0, t["judgment_date"] or "")
    out = {n: sorted([t for t in opn if t["type"] == typ], key=key)
           for n, typ in (("judgments", TASK_TYPES[0]), ("files", TASK_TYPES[2]), ("appeals", APPEAL))}
    out["sessions"] = [x for x in list_rows("sessions") if 0 <= x["days_left"] <= SESSION_DAYS]
    return out


# ---------- النسخ الاحتياطي ----------
def backup(prune=True):
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst, i = BACKUP_DIR / ("cases_%s.db" % stamp), 1
    while dst.exists():                      # لا نكتب فوق نسخة موجودة أبداً (حتى لو في نفس الثانية)
        i += 1
        dst = BACKUP_DIR / ("cases_%s_%d.db" % (stamp, i))
    src = sqlite3.connect(DB_PATH)
    out = sqlite3.connect(dst)
    src.backup(out)
    out.close(); src.close()
    if prune:
        for old in sorted(BACKUP_DIR.glob("cases_*.db"))[:-60]:
            old.unlink()
    return dst


def list_backups():
    BACKUP_DIR.mkdir(exist_ok=True)
    out = []
    for p in sorted(BACKUP_DIR.glob("cases_*.db"), reverse=True):
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size, "mtime": dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    return out


def restore_from(path):
    """استعادة نسخة احتياطية مكان البيانات الحالية. تُحفظ نسخة من الوضع الحالي أولاً،
    ويُبقى على حسابات المستخدمين ومفاتيح الأمان كما هي حتى لا يُحبس أحد خارج البرنامج."""
    src = sqlite3.connect(str(path))
    try:
        if not src.execute("SELECT 1 FROM sqlite_master WHERE name='cases'").fetchone() \
                or src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("الملف ليس نسخة احتياطية صالحة لهذا البرنامج")
    except sqlite3.DatabaseError:
        src.close()
        raise ValueError("الملف ليس نسخة احتياطية صالحة لهذا البرنامج")
    with db() as c:
        users = [tuple(r) for r in c.execute("SELECT id,username,pw_hash,role,see_acc,active FROM users")]
        subs = [tuple(r) for r in c.execute("SELECT id,user_id,endpoint,p256dh,auth FROM push_subs")]
        keep = [tuple(r) for r in c.execute("SELECT k,v FROM settings WHERE k IN ('secret','vapid_priv','vapid_pub')")]
    safety = backup(prune=False)   # بلا حذف نسخ قديمة أثناء الاستعادة
    dst = sqlite3.connect(str(DB_PATH))
    try:
        src.backup(dst)          # يستبدل محتوى القاعدة كاملاً
    finally:
        dst.close()
        src.close()
    init_db()                    # يرقّي النسخة القديمة لهيكل البرنامج الحالي
    with db() as c:
        c.execute("DELETE FROM users")
        c.executemany("INSERT INTO users(id,username,pw_hash,role,see_acc,active) VALUES(?,?,?,?,?,?)", users)
        c.execute("DELETE FROM push_subs")
        c.executemany("INSERT INTO push_subs(id,user_id,endpoint,p256dh,auth) VALUES(?,?,?,?,?)", subs)
        c.executemany("INSERT OR REPLACE INTO settings VALUES(?,?)", keep)
    return safety.name


def auto_backup():
    """نسخة احتياطية تلقائية مرة واحدة يومياً عند فتح البرنامج."""
    BACKUP_DIR.mkdir(exist_ok=True)
    if not list(BACKUP_DIR.glob("cases_%s_*.db" % today().strftime("%Y%m%d"))) and DB_PATH.exists():
        backup()


# ---------- استيراد / تصدير Excel ----------
def import_excel(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    hdr = idx = None
    for i, r in enumerate(rows[:15]):
        names = [str(x).strip() if x is not None else "" for x in r]
        if "الكود" in names and "الموكل" in names:
            hdr, idx = i, {n: j for j, n in enumerate(names) if n}
            break
    if hdr is None:
        raise ValueError("لم أجد العمودين (الكود) و(الموكل) في الورقة الأولى")
    jcol = next((j for n, j in idx.items() if n.startswith("الجلسة")), None)
    ccol = idx.get("اليوم")
    st = {"cases_new": 0, "cases_updated": 0, "sessions": 0, "classes": 0}
    init_db()
    with db() as c:
        for r in rows[hdr + 1:]:
            code, client = r[idx["الكود"]], r[idx["الموكل"]]
            if code is None or not client:
                continue
            code = int(code)
            cat = "إداري" if ccol is not None and str(r[ccol] or "").strip() == "الإداري" else None
            row = c.execute("SELECT id, category FROM cases WHERE code=?", (code,)).fetchone()
            if row:
                cid = row["id"]
                c.execute("UPDATE cases SET client=?, category=COALESCE(category,?) WHERE id=?", (str(client).strip(), cat, cid))
                st["cases_updated"] += 1
            else:
                cid = c.execute("INSERT INTO cases(code,client,category) VALUES(?,?,?)", (code, str(client).strip(), cat)).lastrowid
                st["cases_new"] += 1
            d = parse_date(r[jcol]) if jcol is not None and r[jcol] else None
            if d and not c.execute("SELECT 1 FROM sessions WHERE case_id=? AND date=?", (cid, d)).fetchone():
                c.execute("INSERT INTO sessions(case_id,date) VALUES(?,?)", (cid, d))
                st["sessions"] += 1
        if "تصنيف البوابة" in wb.sheetnames:
            c.execute("DELETE FROM classes")
            for a, b, *_ in wb["تصنيف البوابة"].iter_rows(min_row=2, values_only=True):
                if a and b:
                    c.execute("INSERT INTO classes VALUES(?,?)", (str(a).strip(), str(b).strip()))
                    st["classes"] += 1
    return st


import re
_DATE_RE = re.compile(r"(\d{1,4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,4})")


def find_date(v):
    """يستخرج تاريخاً من خلية (تاريخ حقيقي أو نص مثل 'جلسة 25-11-2026')."""
    if isinstance(v, (dt.datetime, dt.date)):
        return parse_date(v)
    m = _DATE_RE.search(str(v or ""))
    if not m:
        return None
    x, y_, z = m.groups()
    try:
        yy, mm, dd = (x, y_, z) if len(x) == 4 else (z, y_, x)
        return dt.date(int(yy), int(mm), int(dd)).isoformat()
    except ValueError:
        return None


def _s(v):
    return " ".join(str(v).split()) if v is not None else ""


def _pure_date(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return parse_date(v)
    return find_date(v) if re.fullmatch(r"[\d/\-. ]+", _s(v)) else None


def _num(v):
    if v is None or _s(v) == "":
        return None
    return str(int(v)) if isinstance(v, float) and v.is_integer() else _s(v)


def _norm(t):
    t = _s(t).replace(",", " ").replace("،", " ").replace("-", " ")
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        t = t.replace(a, b)
    return t


def _find_by_name(c, name):
    """مطابقة بالاسم لصفوف لا تحمل كوداً ولا رقم قضية: كل كلمات الاسم موجودة في اسم قضية واحدة على الأقل."""
    toks = set(_norm(name).split())
    if not toks:
        return None
    rows = c.execute("SELECT id, case_no, client FROM cases ORDER BY code IS NULL, code").fetchall()
    for exact in (True, False):                       # التطابق التام أولاً ثم الجزئي
        for r in rows:
            t = set(_norm(r["client"]).split())
            if (t == toks) if exact else (toks <= t):
                return r
    return None


def _status(g, deferred=False):
    g = _s(g)
    if g.startswith("تم"):
        return DONE, ("" if g == "تم" else g)
    if "غير" in g and "مطلوب" in g:
        return DONE, "غير مطلوب"
    return (STATUSES[2] if deferred else STATUSES[0]), g      # مثل: موجود / الملف لم يرد


def import_tasks_excel(path):
    """يستورد ورقة "التصوير": تصوير أحكام + تصوير ملفات + طعون + مؤجل، مع حالة (تم) لكل صف."""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    if "التصوير" not in wb.sheetnames:
        raise ValueError('لم أجد ورقة باسم "التصوير" في الملف')
    init_db()
    st = {"tasks_new": 0, "tasks_updated": 0, "task_cases_new": 0, "task_sessions": 0}
    section = "main"
    with db() as c:
        for n, row in enumerate(wb["التصوير"].iter_rows(values_only=True)):
            a, b, name, d, e, f, g, h, i, j = (list(row) + [None] * 10)[:10]
            cells = [_s(x) for x in (a, b, name, d, e, f, g, h, i, j)]
            if n == 0 or not any(cells) or cells[0] == "رقم الي":
                continue
            if cells[0] in ("تصوير ملف", "مؤجل") and not any(cells[1:]):
                section = "file" if cells[0] == "تصوير ملف" else "deferred"
                continue
            if cells[4] == "اخر موعد":
                section = "appeal"
                continue
            no = _num(a)
            try:
                code = int(b) if _s(b) else None
            except ValueError:
                code = None
            client = _s(name)
            if not (no or code or client):
                continue
            kw = ("تصوير الملف", "تقرير", "الملف", "الصحيفة")
            jd = _pure_date(d)
            dtext = "" if jd else _s(d)
            notes, place, deadline, kind = [], None, None, None
            stat, snote = _status(g, section == "deferred")
            if section == "appeal":
                typ = APPEAL
                ft = _s(f)
                kind = next((k for w, k in (("تمييز", "تمييز"), ("اشكال", "إشكال"), ("إشكال", "إشكال"), ("استئناف", "استئناف"), ("دعوى", "رفع دعوى")) if w in ft), None)
                deadline = find_date(e)
                if ft not in ("عمل استئناف", "عمل تمييز", "عمل اشكال"):
                    notes.append(ft)
            elif section in ("file", "deferred"):
                typ = TASK_TYPES[2]
                place = _s(f) if section == "file" else (dtext or None)
                if section == "file":
                    notes += [dtext, _s(e)]
                    jd = None if not jd else jd
                    if jd:
                        notes.append("تاريخ " + fmt_date(jd)); jd = None
                else:
                    jd = None
            else:
                typ = TASK_TYPES[2] if any(k in " ".join((client, _s(e), _s(f), dtext)) for k in kw) else TASK_TYPES[0]
                place = _s(e) or None
                if _pure_date(e):
                    place = None
                notes += [_s(f) if _s(f) != "تصوير الملف" else "", dtext]
                if "تقرير" in client and not code:
                    notes.append(client); client = ""
                if typ == TASK_TYPES[2]:
                    jd = jd
            for extra in (h, i, j):
                dd = _pure_date(extra)
                notes.append(("تاريخ " + fmt_date(dd)) if dd else _s(extra))
            notes.append(snote)
            note = " — ".join(dict.fromkeys(x for x in notes if x))
            # القضية
            r = c.execute("SELECT id, case_no FROM cases WHERE code=?", (code,)).fetchone() if code is not None else None
            if not r and no:
                r = c.execute("SELECT id, case_no FROM cases WHERE case_no=?", (no,)).fetchone()
            if not r and code is None and not no and client:
                r = _find_by_name(c, client)
            if r:
                cid = r["id"]
                if no and not r["case_no"]:
                    c.execute("UPDATE cases SET case_no=? WHERE id=?", (no, cid))
            else:
                cid = c.execute("INSERT INTO cases(code,client,case_no) VALUES(?,?,?)",
                                (code, client or ("قضية %s" % no), no)).lastrowid
                st["task_cases_new"] += 1
            old = c.execute("SELECT id, status, notes, place, deadline FROM tasks WHERE case_id=? AND type=? AND IFNULL(appeal_kind,'')=? "
                            "AND IFNULL(judgment_date,'')=?", (cid, typ, kind or "", jd or "")).fetchone()
            if old:
                c.execute("UPDATE tasks SET place=COALESCE(place,?), deadline=COALESCE(deadline,?), notes=COALESCE(notes,?) WHERE id=?",
                          (place, deadline, note or None, old["id"]))
                if stat == DONE and old["status"] != DONE:
                    c.execute("UPDATE tasks SET status=? WHERE id=?", (DONE, old["id"]))
                    st["tasks_updated"] += 1
            else:
                c.execute("INSERT INTO tasks(case_id,type,appeal_kind,judgment_date,deadline,place,status,notes) VALUES(?,?,?,?,?,?,?,?)",
                          (cid, typ, kind, jd, deadline, place, stat, note or None))
                st["tasks_new"] += 1
            # جلسة مذكورة بجانب مهمة غير منجزة
            sd = find_date(h) if "جلسة" in _s(h) else None
            if sd and stat != DONE and not c.execute("SELECT 1 FROM sessions WHERE case_id=? AND date=?", (cid, sd)).fetchone():
                c.execute("INSERT INTO sessions(case_id,date) VALUES(?,?)", (cid, sd))
                st["task_sessions"] += 1
    return st


def import_any(path):
    """استيراد ذكي: يتعرف على ملف القضايا (الكود/الموكل) وعلى ملف المهام (ورقة التصوير)."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True)
    names = wb.sheetnames
    wb.close()
    out, ok = {}, False
    try:
        out.update(import_excel(path)); ok = True
    except ValueError:
        pass
    if "التصوير" in names:
        out.update(import_tasks_excel(path)); ok = True
    if not ok:
        raise ValueError('لم أتعرف على الملف: يلزم عمودا (الكود، الموكل) في الورقة الأولى، أو ورقة باسم "التصوير"')
    return out


def summary_text(st):
    names = {"cases_new": "قضايا جديدة", "cases_updated": "قضايا محدّثة", "sessions": "جلسات مضافة", "classes": "تصنيفات",
             "tasks_new": "مهام جديدة", "tasks_updated": "مهام تحوّلت إلى منجزة", "task_cases_new": "قضايا جديدة من جدول المهام",
             "task_sessions": "جلسات مضافة من جدول المهام"}
    return "\n".join("%s: %d" % (names[k], v) for k, v in st.items() if k in names and v)


def export_excel(path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    wb.remove(wb.active)
    for t in ("cases", "sessions", "tasks"):
        sch = _SCHEMA[t]
        ws = wb.create_sheet(sch["title"])
        ws.sheet_view.rightToLeft = True
        cols = [c for c in sch["cols"] if c["k"] not in ("days_left", "open_tasks")]
        ws.append([c["l"] for c in cols])
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E8C")
            cell.alignment = Alignment(horizontal="center")
        for r in list_rows(t):
            ws.append([dt.date.fromisoformat(r[c["k"]]) if c.get("t") == "date" and r.get(c["k"]) else r.get(c["k"]) for c in cols])
        for i, c in enumerate(cols, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = max(12, c.get("w", 100) / 7)
            if c.get("t") == "date":
                for cell in ws.iter_cols(min_col=i, max_col=i, min_row=2):
                    for x in cell:
                        x.number_format = "DD/MM/YYYY"
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
    ws = wb.create_sheet("الحسابات")
    ws.sheet_view.rightToLeft = True
    ws.append(["الكود", "الموكل", "رقم القضية", "قيمة العقد", "المسدد", "المتبقي", "مصروفات مستحقة"])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E8C")
    for r in acc_list():
        if r["active"]:
            ws.append([r["code"], r["client"], r["case_no"], r["total"], r["paid"], r["remaining"], r["exp_due"]])
    wb.save(path)


# ---------- الحسابات: العقود والدفعات وسندات القبض والمصروفات القضائية (مرتبطة بالقضايا) ----------
def _f(v):
    try:
        x = float(str(v if v is not None else 0).replace(",", "").strip() or 0)
    except ValueError:
        raise ValueError("رقم غير صالح: %s" % v)
    if x < 0:
        raise ValueError("لا يُقبل رقم سالب")
    return x


def acc_settings(new=None):
    with db() as c:
        for k in (new or {}):
            if k in ("cur", "office"):
                c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, str(new[k] or "").strip()))
        s = {r["k"]: r["v"] for r in c.execute("SELECT k, v FROM settings")}
    return {"cur": s.get("cur") or "د.ك", "office": s.get("office") or ""}


def acc_list():
    q = ("SELECT c.id case_id, c.code, c.client, c.case_no, c.phone, IFNULL((SELECT SUM(total) FROM contracts k WHERE k.case_id=c.id),0) total, (SELECT COUNT(*) FROM contracts k WHERE k.case_id=c.id) n_contracts,"
         " IFNULL((SELECT SUM(amt) FROM payments p WHERE p.case_id=c.id),0) paid,"
         " IFNULL((SELECT SUM(amt-paid) FROM expenses e WHERE e.case_id=c.id),0) exp_due,"
         " (SELECT COUNT(*) FROM payments p WHERE p.case_id=c.id)+(SELECT COUNT(*) FROM expenses e WHERE e.case_id=c.id) n_rec"
         " FROM cases c ORDER BY c.code IS NULL, c.code")
    with db() as c:
        rows = [dict(r) for r in c.execute(q)]
    for r in rows:
        r["remaining"] = r["total"] - r["paid"]
        r["has_contract"] = r["n_contracts"] > 0
        r["active"] = bool(r["has_contract"] or r["n_rec"])
    return rows


def acc_totals():
    rows = acc_list()
    prev = (today().replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    with db() as c:
        m = lambda k: c.execute("SELECT IFNULL(SUM(amt),0) FROM payments WHERE substr(date,1,7)=?", (k,)).fetchone()[0]
        cur_m, prev_m = m(today().strftime("%Y-%m")), m(prev)
        lawyer_due = c.execute("SELECT IFNULL(SUM(MAX(amt-IFNULL(lawyer_paid,0),0)),0) FROM expenses").fetchone()[0]
    return {"contracts": sum(r["n_contracts"] for r in rows), "total": sum(r["total"] for r in rows),
            "paid": sum(r["paid"] for r in rows), "remaining": sum(r["remaining"] for r in rows if r["has_contract"]),
            "exp_due": sum(r["exp_due"] for r in rows), "month": cur_m, "prev_month": prev_m, "lawyer_due": lawyer_due}


def acc_unpaid_report():
    """بيان المصروفات القضائية لكل محامٍ (للمدير فقط): ما على المحامي للمدير (lawyer_due) وما على الموكل (client_due)."""
    q = ("SELECT c.id case_id, c.code, c.client, c.case_no, c.lawyer, e.id eid, e.date, e.descr, e.amt, e.paid, e.lawyer_paid "
         "FROM expenses e JOIN cases c ON c.id=e.case_id "
         "WHERE e.amt - IFNULL(e.paid,0) > 0.0005 OR e.amt - IFNULL(e.lawyer_paid,0) > 0.0005 "
         "ORDER BY c.client, c.id, e.date, e.id")
    groups = {}
    with db() as c:
        for r in c.execute(q):
            cs = groups.setdefault(r["lawyer"] or "", {}).setdefault(
                r["case_id"], {"case_id": r["case_id"], "code": r["code"], "client": r["client"], "case_no": r["case_no"], "items": []})
            amt, cp, lp = r["amt"], r["paid"] or 0, r["lawyer_paid"] or 0
            cs["items"].append({"id": r["eid"], "date": r["date"], "descr": r["descr"], "amt": amt,
                                "client_paid": cp, "client_due": max(amt - cp, 0), "lawyer_paid": lp, "lawyer_due": max(amt - lp, 0)})
    out = []
    for name in list(LAWYERS) + sorted(k for k in groups if k and k not in LAWYERS) + [""]:
        if name in LAWYERS or name in groups:      # لكل محامٍ بيان حتى لو لم تكن عليه مصروفات
            cases = list(groups.get(name, {}).values())
            items = [i for x in cases for i in x["items"]]
            out.append({"lawyer": name, "label": name or "بدون محامٍ محدد", "cases": cases,
                        "lawyer_total": sum(i["lawyer_due"] for i in items), "client_total": sum(i["client_due"] for i in items)})
    return out


def acc_case(cid):
    with db() as c:
        cs = c.execute("SELECT id,code,client,case_no,phone FROM cases WHERE id=?", (cid,)).fetchone()
        if not cs:
            raise ValueError("القضية غير موجودة")
        ks = [dict(r) for r in c.execute(
            "SELECT id,title,total,monthly,cnt,start,"
            " IFNULL((SELECT SUM(amt) FROM payments p WHERE p.contract_id=contracts.id),0) paid FROM contracts WHERE case_id=? ORDER BY id", (cid,))]
        pays = [dict(r) for r in c.execute("SELECT id,rcpt_no,contract_id,date,amt,note FROM payments WHERE case_id=? ORDER BY date DESC, rcpt_no DESC", (cid,))]
        exps = [dict(r) for r in c.execute("SELECT id,date,descr,amt,paid,IFNULL(lawyer_paid,0) lawyer_paid FROM expenses WHERE case_id=? ORDER BY id", (cid,))]
    return {"case": dict(cs), "contracts": ks, "payments": pays, "expenses": exps}


def _need_case(c, cid):
    if not c.execute("SELECT 1 FROM cases WHERE id=?", (cid,)).fetchone():
        raise ValueError("القضية غير موجودة")


def acc_save_contract(cid, d, kid=None):
    """kid=None: عقد جديد للقضية cid، وإلا تعديل العقد kid (للموكل الواحد أكثر من عقد)."""
    total, monthly, cnt = _f(d.get("total")), _f(d.get("monthly")), int(_f(d.get("count")))
    start = parse_date(d.get("start")) or today().isoformat()
    title = (d.get("title") or "").strip() or None
    with db() as c:
        if kid:
            if not c.execute("SELECT 1 FROM contracts WHERE id=?", (kid,)).fetchone():
                raise ValueError("العقد غير موجود")
            c.execute("UPDATE contracts SET title=?,total=?,monthly=?,cnt=?,start=? WHERE id=?", (title, total, monthly, cnt, start, kid))
            return kid
        _need_case(c, cid)
        return c.execute("INSERT INTO contracts(case_id,title,total,monthly,cnt,start) VALUES(?,?,?,?,?,?)",
                         (cid, title, total, monthly, cnt, start)).lastrowid


def _next_rcpt(c, taken=()):
    seq = int((c.execute("SELECT v FROM settings WHERE k='rcpt_seq'").fetchone() or {"v": 0})["v"] or 0)
    seq = max(seq, c.execute("SELECT IFNULL(MAX(rcpt_no),0) FROM payments").fetchone()[0], *taken) + 1   # لا يُعاد استخدام رقم محذوف
    c.execute("INSERT OR REPLACE INTO settings VALUES('rcpt_seq',?)", (str(seq),))
    return seq


def acc_add_payment(cid, d):
    amt = _f(d.get("amt"))
    if amt <= 0:
        raise ValueError("أدخل مبلغاً صحيحاً")
    date = parse_date(d.get("date")) or today().isoformat()
    with db() as c:
        _need_case(c, cid)
        ks = [r["id"] for r in c.execute("SELECT id FROM contracts WHERE case_id=? ORDER BY id", (cid,))]
        kid = d.get("contract_id")
        kid = int(kid) if kid not in (None, "") else None
        if kid is not None and kid not in ks:
            raise ValueError("العقد لا يخص هذه القضية")
        if kid is None and ks:
            if len(ks) > 1:
                raise ValueError("اختر العقد الذي تُسدَّد منه هذه الدفعة")
            kid = ks[0]
        no = _next_rcpt(c)
        pid = c.execute("INSERT INTO payments(case_id,contract_id,rcpt_no,date,amt,note) VALUES(?,?,?,?,?,?)",
                        (cid, kid, no, date, amt, (d.get("note") or "").strip() or None)).lastrowid
    return {"id": pid, "no": no}


def acc_add_expense(cid, d):
    descr, amt = (d.get("descr") or "").strip(), _f(d.get("amt"))
    if not descr or amt <= 0:
        raise ValueError("أدخل البيان والمبلغ")
    with db() as c:
        _need_case(c, cid)
        c.execute("INSERT INTO expenses(case_id,date,descr,amt,paid) VALUES(?,?,?,?,?)",
                  (cid, today().isoformat(), descr, amt, min(amt, _f(d.get("paid")))))


def acc_pay_expense(eid, amt):
    amt = _f(amt)
    if amt <= 0:
        raise ValueError("أدخل مبلغاً صحيحاً")
    with db() as c:
        c.execute("UPDATE expenses SET paid=MIN(amt, paid+?) WHERE id=?", (amt, eid))


def acc_lawyer_pay_expense(eid, amt):
    """سداد المحامي للمدير عن مصروف واحد."""
    amt = _f(amt)
    if amt <= 0:
        raise ValueError("أدخل مبلغاً صحيحاً")
    with db() as c:
        r = c.execute("SELECT e.amt, IFNULL(e.lawyer_paid,0) lp, cs.lawyer, cs.client FROM expenses e JOIN cases cs ON cs.id=e.case_id WHERE e.id=?", (eid,)).fetchone()
        if not r:
            raise ValueError("المصروف غير موجود")
        take = min(amt, r["amt"] - r["lp"])
        if take <= 0.0005:
            raise ValueError("هذا المصروف مسدَّد من المحامي بالكامل")
        c.execute("UPDATE expenses SET lawyer_paid=IFNULL(lawyer_paid,0)+? WHERE id=?", (take, eid))


def acc_remit(d):
    """دفعة من المحامي للمدير: تُوزَّع على أقدم مصروفاته غير المسددة أولاً."""
    name, amt = (d.get("lawyer") or "").strip(), _f(d.get("amt"))
    if name not in LAWYERS:
        raise ValueError("المحامي غير معروف")
    if amt <= 0:
        raise ValueError("أدخل مبلغاً صحيحاً")
    with db() as c:
        rows = c.execute("SELECT e.id, e.amt - IFNULL(e.lawyer_paid,0) due FROM expenses e JOIN cases cs ON cs.id=e.case_id "
                         "WHERE cs.lawyer=? AND e.amt - IFNULL(e.lawyer_paid,0) > 0.0005 ORDER BY e.date, e.id", (name,)).fetchall()
        owed = sum(r["due"] for r in rows)
        if amt > owed + 0.0005:
            raise ValueError("المبلغ أكبر من المستحق على المحامي (%s)" % ("%g" % round(owed, 3)))
        left = amt
        for r in rows:
            if left <= 0.0005:
                break
            take = min(r["due"], left)
            c.execute("UPDATE expenses SET lawyer_paid=IFNULL(lawyer_paid,0)+? WHERE id=?", (take, r["id"]))
            left -= take
    return {"owed_before": owed, "owed_after": owed - amt}


def acc_delete(kind, rid):
    with db() as c:
        if kind == "contract" and c.execute("SELECT 1 FROM payments WHERE contract_id=?", (rid,)).fetchone():
            raise ValueError("لا يمكن حذف عقد له دفعات. احذف دفعاته أولاً.")
        c.execute("DELETE FROM %s WHERE id=?" % {"payment": "payments", "expense": "expenses", "contract": "contracts"}[kind], (rid,))


def import_accounts_json(d):
    """استيراد بيانات النسخة القديمة (ملف JSON المصدَّر من برنامج الحسابات الأول)، بدون تكرار."""
    if not isinstance(d, dict) or not isinstance(d.get("clients"), list):
        raise ValueError("الملف ليس نسخة حسابات صالحة")
    st = {"clients": 0, "cases_new": 0, "skipped": 0, "payments": 0, "expenses": 0}
    if d.get("cur") or d.get("office"):
        acc_settings({k: d[k] for k in ("cur", "office") if d.get(k)})
    with db() as c:
        taken = {r[0] for r in c.execute("SELECT rcpt_no FROM payments")}
        for cl in d["clients"]:
            name = str(cl.get("name") or "").strip()
            if not name:
                continue
            toks = set(_norm(name).split())
            row = next((r for r in c.execute("SELECT id FROM cases WHERE 1").fetchall()
                        if set(_norm(c.execute("SELECT client FROM cases WHERE id=?", (r["id"],)).fetchone()["client"]).split()) == toks), None)
            if row:
                cid = row["id"]
                if c.execute("SELECT 1 FROM contracts WHERE case_id=?", (cid,)).fetchone():
                    st["skipped"] += 1
                    continue
                c.execute("UPDATE cases SET phone=COALESCE(phone,?) WHERE id=?", (cl.get("phone") or None, cid))
            else:
                cid = c.execute("INSERT INTO cases(client,case_no,phone) VALUES(?,?,?)",
                                (name, (cl.get("caseNo") or "").strip() or None, (cl.get("phone") or "").strip() or None)).lastrowid
                st["cases_new"] += 1
            kid = c.execute("INSERT INTO contracts(case_id,total,monthly,cnt,start) VALUES(?,?,?,?,?)",
                            (cid, _f(cl.get("total")), _f(cl.get("monthly")), int(_f(cl.get("count"))), parse_date(cl.get("start")) or today().isoformat())).lastrowid
            for p in cl.get("payments", []):
                no = int(p.get("no") or 0)
                if no <= 0 or no in taken:
                    no = _next_rcpt(c, taken)
                taken.add(no)
                c.execute("INSERT INTO payments(case_id,contract_id,rcpt_no,date,amt,note) VALUES(?,?,?,?,?,?)",
                          (cid, kid, no, parse_date(p.get("date")) or today().isoformat(), _f(p.get("amt")), p.get("note") or None))
                st["payments"] += 1
            for e in cl.get("expenses", []):
                c.execute("INSERT INTO expenses(case_id,date,descr,amt,paid) VALUES(?,?,?,?,?)",
                          (cid, parse_date(e.get("date")) or today().isoformat(), e.get("desc") or "", _f(e.get("amt")), _f(e.get("paid"))))
                st["expenses"] += 1
            st["clients"] += 1
        old = int((c.execute("SELECT v FROM settings WHERE k='rcpt_seq'").fetchone() or {"v": 0})["v"] or 0)
        seq = c.execute("SELECT IFNULL(MAX(rcpt_no),0) FROM payments").fetchone()[0]
        c.execute("INSERT OR REPLACE INTO settings VALUES('rcpt_seq',?)", (str(max(seq, old)),))
    return st


# ---------- استيراد قاعدة بيانات برنامج الحسابات القديم (ملف .db) ----------
def accounts_from_db(path):
    s = sqlite3.connect(str(path))
    s.row_factory = sqlite3.Row
    try:
        if not s.execute("SELECT 1 FROM sqlite_master WHERE name='clients'").fetchone():
            raise ValueError("الملف ليس قاعدة بيانات برنامج الحسابات")
        st = {r["k"]: r["v"] for r in s.execute("SELECT k,v FROM settings")}
        out = {"cur": st.get("cur"), "office": st.get("office"), "clients": []}
        has_no = "rcpt_no" in [r["name"] for r in s.execute("PRAGMA table_info(payments)")]
        for r in s.execute("SELECT * FROM clients ORDER BY pos"):
            out["clients"].append({
                "name": r["name"], "phone": r["phone"], "caseNo": r["case_no"], "total": r["total"],
                "monthly": r["monthly"], "count": r["cnt"], "start": r["start"],
                "payments": [{"no": (p["rcpt_no"] if has_no else 0), "date": p["date"], "amt": p["amt"], "note": p["note"]}
                             for p in s.execute("SELECT * FROM payments WHERE client_id=? ORDER BY pos", (r["id"],))],
                "expenses": [{"date": e["date"], "desc": e["descr"], "amt": e["amt"], "paid": e["paid"]}
                             for e in s.execute("SELECT * FROM expenses WHERE client_id=? ORDER BY pos", (r["id"],))]})
        return out
    except sqlite3.DatabaseError:
        raise ValueError("ملف قاعدة البيانات غير صالح")
    finally:
        s.close()


# ---------- المستخدمون والصلاحيات ----------
import json, threading, secrets, base64
ROLES = {"admin": "مدير", "editor": "موظف", "viewer": "مشاهدة فقط"}
_actor = threading.local()


def set_actor(name):
    _actor.name = name


def get_actor():
    return getattr(_actor, "name", None)


def secret_key():
    with db() as c:
        r = c.execute("SELECT v FROM settings WHERE k='secret'").fetchone()
        if r:
            return r["v"]
        k = secrets.token_hex(32)
        c.execute("INSERT INTO settings VALUES('secret',?)", (k,))
        return k


def _u(r):
    return None if r is None else {"id": r["id"], "username": r["username"], "role": r["role"],
                                   "see_acc": bool(r["see_acc"]), "active": bool(r["active"])}


def users_count():
    with db() as c:
        return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def user_list():
    with db() as c:
        return [_u(r) for r in c.execute("SELECT * FROM users ORDER BY id")]


def user_get(uid):
    with db() as c:
        return _u(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())


def _other_admins(c, uid):
    return c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (uid,)).fetchone()[0]


def user_create(username, password, role, see_acc=None):
    from werkzeug.security import generate_password_hash
    username = (username or "").strip()
    if not username or len(username) > 40:
        raise ValueError("اسم المستخدم مطلوب (حتى 40 حرفاً)")
    if role not in ROLES:
        raise ValueError("صلاحية غير صالحة")
    if len(password or "") < 8:
        raise ValueError("كلمة المرور 8 أحرف على الأقل")
    if see_acc is None:
        see_acc = role in ("admin", "viewer")
    with db() as c:
        try:
            return c.execute("INSERT INTO users(username,pw_hash,role,see_acc,active) VALUES(?,?,?,?,1)",
                             (username, generate_password_hash(password), role, 1 if see_acc else 0)).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError("اسم المستخدم موجود مسبقاً")


def user_update(uid, d):
    from werkzeug.security import generate_password_hash
    with db() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not r:
            raise ValueError("المستخدم غير موجود")
        role = d.get("role", r["role"])
        active = int(bool(d["active"])) if "active" in d else r["active"]
        if role not in ROLES:
            raise ValueError("صلاحية غير صالحة")
        if r["role"] == "admin" and (role != "admin" or not active) and _other_admins(c, uid) == 0:
            raise ValueError("لا بد من بقاء مدير فعّال واحد على الأقل")
        if d.get("password"):
            if len(d["password"]) < 8:
                raise ValueError("كلمة المرور 8 أحرف على الأقل")
            c.execute("UPDATE users SET pw_hash=? WHERE id=?", (generate_password_hash(d["password"]), uid))
        c.execute("UPDATE users SET role=?, active=?, see_acc=? WHERE id=?",
                  (role, active, int(bool(d["see_acc"])) if "see_acc" in d else r["see_acc"], uid))


def user_delete(uid):
    with db() as c:
        r = c.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if r and r["role"] == "admin" and _other_admins(c, uid) == 0:
            raise ValueError("لا يمكن حذف آخر مدير")
        c.execute("DELETE FROM push_subs WHERE user_id=?", (uid,))
        c.execute("DELETE FROM users WHERE id=?", (uid,))


def user_login(username, password):
    from werkzeug.security import check_password_hash
    with db() as c:
        r = c.execute("SELECT * FROM users WHERE username=?", ((username or "").strip(),)).fetchone()
    if r and r["active"] and check_password_hash(r["pw_hash"], password or ""):
        return _u(r)
    return None


# ---------- الإشعارات (Web Push) ----------
def push_available():
    try:
        import pywebpush  # noqa
        return True
    except ImportError:
        return False


def vapid_keys():
    with db() as c:
        s = {r["k"]: r["v"] for r in c.execute("SELECT k,v FROM settings WHERE k IN ('vapid_priv','vapid_pub')")}
        if len(s) == 2:
            return s["vapid_priv"], s["vapid_pub"]
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization as ser
        k = ec.generate_private_key(ec.SECP256R1())
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
        priv = b64(k.private_numbers().private_value.to_bytes(32, "big"))
        pub = b64(k.public_key().public_bytes(ser.Encoding.X962, ser.PublicFormat.UncompressedPoint))
        c.execute("INSERT OR REPLACE INTO settings VALUES('vapid_priv',?)", (priv,))
        c.execute("INSERT OR REPLACE INTO settings VALUES('vapid_pub',?)", (pub,))
        return priv, pub


def push_subscribe(uid, sub):
    ep, keys = (sub or {}).get("endpoint"), (sub or {}).get("keys") or {}
    if not ep or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("اشتراك غير صالح")
    with db() as c:
        c.execute("INSERT OR REPLACE INTO push_subs(user_id,endpoint,p256dh,auth) VALUES(?,?,?,?)",
                  (uid, ep, keys["p256dh"], keys["auth"]))


def push_unsubscribe(endpoint):
    with db() as c:
        c.execute("DELETE FROM push_subs WHERE endpoint=?", (endpoint,))


def push_all(title, body, url="/", exclude=None, only_user=None):
    """يرسل إشعاراً لكل الأجهزة المشتركة (عدا المنفّذ). يعمل في الخلفية ولا يعطّل البرنامج إن فشل."""
    def run():
        try:
            from pywebpush import webpush, WebPushException
            priv, _ = vapid_keys()
            with db() as c:
                subs = [dict(r) for r in c.execute(
                    "SELECT s.id, s.endpoint, s.p256dh, s.auth, u.username, u.id AS uid FROM push_subs s "
                    "JOIN users u ON u.id=s.user_id WHERE u.active=1")]
        except Exception as e:
            print("push disabled:", e)
            return
        for s in subs:
            if (only_user and s["uid"] != only_user) or (exclude and s["username"] == exclude):
                continue
            try:
                webpush(subscription_info={"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                        data=json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False),
                        vapid_private_key=priv,
                        vapid_claims={"sub": os.environ.get("CT_CONTACT", "mailto:admin@example.com")}, ttl=86400)
            except WebPushException as e:
                if getattr(e.response, "status_code", 0) in (404, 410):   # الاشتراك لم يعد صالحاً
                    push_unsubscribe(s["endpoint"])
            except Exception as e:
                print("push failed:", e)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _task_done_notice(rid):
    with db() as c:
        r = c.execute("SELECT t.type, c.client, c.case_no FROM tasks t LEFT JOIN cases c ON c.id=t.case_id WHERE t.id=?", (rid,)).fetchone()
    if not r:
        return
    who = get_actor()
    push_all("✔ تم إنجاز مهمة", "%s%s — %s%s" % ((who + ": ") if who else "", r["type"] or "", r["client"] or "",
                                                  (" (%s)" % r["case_no"]) if r["case_no"] else ""),
             "/#tasks", exclude=who)


if __name__ == "__main__":
    import sys
    init_db()
    if len(sys.argv) > 2 and sys.argv[1] == "import":
        print(import_excel(sys.argv[2]))
