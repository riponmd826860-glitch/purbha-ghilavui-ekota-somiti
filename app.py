import os
import secrets
from datetime import date, datetime
from uuid import uuid4

from flask import Flask, request, session, redirect, render_template_string, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from supabase import create_client
except Exception:
    create_client = None

BASE = os.path.dirname(__file__)
LOCAL_DB = os.path.join(BASE, "somobay.db")
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or "").strip()
BKASH_NUMBER = os.environ.get("BKASH_NUMBER", "").strip()
SUPABASE_BUCKET = "payment-screenshots"

supabase = None
if SUPABASE_URL and SUPABASE_KEY and create_client:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception:
        supabase = None


class DB:
    def __init__(self):
        self.pg = None
        self.conn = None
        self.cur = None
        if USE_POSTGRES:
            import psycopg
            from psycopg.rows import dict_row
            url = DATABASE_URL
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://"):]
            self.pg = psycopg.connect(url, connect_timeout=15, row_factory=dict_row)
            self.cur = self.pg.cursor()
        else:
            import sqlite3
            self.conn = sqlite3.connect(LOCAL_DB)
            self.conn.row_factory = sqlite3.Row

    def sql(self, query):
        return query.replace("?", "%s") if USE_POSTGRES else query

    def execute(self, query, params=()):
        return self.cur.execute(self.sql(query), params) if USE_POSTGRES else self.conn.execute(query, params)

    def script(self, script):
        if USE_POSTGRES:
            for statement in script.split(";"):
                statement = statement.strip()
                if statement:
                    self.cur.execute(statement)
        else:
            self.conn.executescript(script)

    def commit(self):
        (self.pg or self.conn).commit()

    def close(self):
        if self.cur:
            self.cur.close()
        if self.pg:
            self.pg.close()
        if self.conn:
            self.conn.close()


def db():
    return DB()


def init_db():
    c = db()
    if USE_POSTGRES:
        c.script("""
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,name TEXT NOT NULL,monthly DOUBLE PRECISION NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id SERIAL PRIMARY KEY,member_id TEXT UNIQUE,name TEXT,phone TEXT,nid TEXT,photo TEXT,username TEXT UNIQUE,password TEXT,role TEXT,status TEXT,joining TEXT);
        CREATE TABLE IF NOT EXISTS deposits(id SERIAL PRIMARY KEY,member_id INTEGER REFERENCES users(id) ON DELETE CASCADE,month TEXT,amount DOUBLE PRECISION,date TEXT,method TEXT,note TEXT);
        CREATE TABLE IF NOT EXISTS withdrawals(id SERIAL PRIMARY KEY,member_id INTEGER REFERENCES users(id) ON DELETE CASCADE,amount DOUBLE PRECISION,date TEXT,reason TEXT);
        CREATE TABLE IF NOT EXISTS logs(id SERIAL PRIMARY KEY,action TEXT,target TEXT,at TEXT);
        CREATE TABLE IF NOT EXISTS payment_requests(id UUID PRIMARY KEY,member_id UUID,app_user_id INTEGER,month DATE NOT NULL,amount DOUBLE PRECISION NOT NULL,transaction_id TEXT NOT NULL,screenshot TEXT,status TEXT NOT NULL DEFAULT 'pending',admin_note TEXT,created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),approved_at TIMESTAMPTZ,approved_by INTEGER);
        ALTER TABLE payment_requests ADD COLUMN IF NOT EXISTS app_user_id INTEGER;
        ALTER TABLE payment_requests ADD COLUMN IF NOT EXISTS admin_user_id INTEGER;
        """)
    else:
        c.script("""
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,name TEXT NOT NULL,monthly REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,member_id TEXT UNIQUE,name TEXT,phone TEXT,nid TEXT,photo TEXT,username TEXT UNIQUE,password TEXT,role TEXT,status TEXT,joining TEXT);
        CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER,month TEXT,amount REAL,date TEXT,method TEXT,note TEXT);
        CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER,amount REAL,date TEXT,reason TEXT);
        CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT,target TEXT,at TEXT);
        CREATE TABLE IF NOT EXISTS payment_requests(id TEXT PRIMARY KEY,member_id TEXT,app_user_id INTEGER,month TEXT NOT NULL,amount REAL NOT NULL,transaction_id TEXT NOT NULL,screenshot TEXT,status TEXT NOT NULL DEFAULT 'pending',admin_note TEXT,created_at TEXT NOT NULL,approved_at TEXT,approved_by TEXT,admin_user_id INTEGER);
        """)
    if not c.execute("SELECT 1 FROM settings WHERE id=1").fetchone():
        c.execute("INSERT INTO settings(id,name,monthly) VALUES(1,?,?)", ("পূর্ব ঘিলাভুই যুব একতা সমবায় সমিতি", 1000))
    c.commit()
    c.close()


init_db()


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    c = db()
    user = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return user


def is_admin():
    user = current_user()
    return bool(user and user["role"] == "admin" and user["status"] == "Active")


def guard():
    return redirect("/login") if not current_user() else None


def society_settings():
    c = db()
    row = c.execute("SELECT * FROM settings WHERE id=1").fetchone()
    c.close()
    return row


def log_action(action, target):
    try:
        c = db()
        c.execute("INSERT INTO logs(action,target,at) VALUES(?,?,?)", (action, target, datetime.now().isoformat(timespec="seconds")))
        c.commit()
        c.close()
    except Exception:
        pass


def pending_count():
    try:
        c = db()
        n = c.execute("SELECT COUNT(*) AS n FROM payment_requests WHERE status='pending'").fetchone()["n"]
        c.close()
        return int(n or 0)
    except Exception:
        return 0


def upload_screenshot(file_obj, path):
    if not supabase:
        return None, "Supabase Storage configuration is missing."
    try:
        data = file_obj.read()
        options = {"content-type": file_obj.mimetype or "application/octet-stream", "upsert": False}
        try:
            supabase.storage.from_(SUPABASE_BUCKET).upload(path, data, options)
        except TypeError:
            supabase.storage.from_(SUPABASE_BUCKET).upload(path, data, file_options=options)
        return path, None
    except Exception as exc:
        return None, str(exc)


def signed_url(path, expires=900):
    if not path or not supabase:
        return None
    try:
        result = supabase.storage.from_(SUPABASE_BUCKET).create_signed_url(path, expires)
        if isinstance(result, dict):
            return result.get("signedURL") or result.get("signedUrl") or (result.get("data") or {}).get("signedUrl")
        return getattr(result, "signed_url", None) or getattr(result, "signedURL", None)
    except Exception:
        return None


def svg_icon(name):
    icons = {
        "dashboard": '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
        "members": '<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><circle cx="17" cy="9" r="2.5"/><path d="M3 20c.5-4 2.7-6 6-6s5.5 2 6 6M15 14c3.2-.1 5 1.7 5.5 5"/></svg>',
        "calendar": '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18M7 14h2M11 14h2M15 14h2M7 17h2M11 17h2"/></svg>',
        "payment": '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M7 9h.01M17 15h.01"/></svg>',
        "report": '<svg viewBox="0 0 24 24"><path d="M6 3h9l3 3v15H6zM15 3v4h4M9 12h6M9 16h6M9 8h2"/></svg>',
        "audit": '<svg viewBox="0 0 24 24"><path d="M4 4h12v16H4zM8 8h4M8 12h4M8 16h2"/><circle cx="17" cy="17" r="3"/><path d="m19.2 19.2 2 2"/></svg>',
        "settings": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M4.9 5.6 7 7M17 7l2.1-1.4M7 17l-2.1 1.4M17 17l2.1 1.4M12 4V2M12 22v-2M4 12H2M22 12h-2"/></svg>',
        "home": '<svg viewBox="0 0 24 24"><path d="m3 11 9-8 9 8v9H5a2 2 0 0 1-2-2zM9 20v-6h6v6"/></svg>',
        "account": '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3"/><path d="M5 21c.7-4.2 3-6 7-6s6.3 1.8 7 6"/></svg>',
        "logout": '<svg viewBox="0 0 24 24"><path d="M10 4H5v16h5M14 8l4 4-4 4M8 12h10"/></svg>',
    }
    return icons.get(name, icons["dashboard"])


def nav_link(href, label, icon_name, badge=0):
    badge_html = f'<span class="nav-badge">{badge}</span>' if badge else ""
    return f'<a class="nav-link" href="{href}"><span class="nav-icon">{svg_icon(icon_name)}</span><span class="nav-label">{label}</span>{badge_html}</a>'


def layout(body, title=""):
    s = society_settings()
    u = current_user()
    nav = ""
    if u and u["role"] == "admin":
        p = pending_count()
        nav = "".join([
            nav_link("/", "ড্যাশবোর্ড", "dashboard"),
            nav_link("/members", "সদস্য", "members"),
            nav_link("/collections", "মাসিক জমা", "calendar"),
            nav_link("/payment-requests", "পেমেন্ট রিকোয়েস্ট", "payment", p),
            nav_link("/transactions", "লেনদেন", "payment"),
            nav_link("/reports", "রিপোর্ট", "report"),
            nav_link("/logs", "অডিট লগ", "audit"),
            nav_link("/settings", "সেটিংস", "settings"),
        ])
    elif u:
        nav = "".join([
            nav_link("/", "হোম", "home"),
            nav_link("/me", "আমার হিসাব", "account"),
            nav_link("/payment-request/new", "মাসিক জমা", "payment"),
        ])
    if u:
        nav += nav_link("/logout", "লগআউট", "logout")
    return f'''<!doctype html><html lang="bn"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>{s["name"]}</title><style>
*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,sans-serif;background:#f4f7fb;color:#172033}}.side{{position:fixed;inset:0 auto 0 0;width:235px;background:#17324d;color:#fff;padding:14px 10px;z-index:10}}.brand{{font-weight:800;line-height:1.4;margin:2px 8px 20px;display:flex;align-items:center;gap:10px}}.brand-logo{{width:46px;height:46px;object-fit:contain;border-radius:50%;background:#fff}}.brand-name{{font-size:15px}}.nav-link{{display:flex;align-items:center;gap:12px;color:#dce7f2;text-decoration:none;padding:11px 12px;margin:5px 0;border-radius:10px;min-height:46px}}.nav-link:hover{{background:#274966;color:#fff}}.nav-icon{{width:28px;height:28px;display:grid;place-items:center;flex:none}}.nav-icon svg{{width:25px;height:25px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}}.nav-label{{font-size:15px;font-weight:600}}.nav-badge{{margin-left:auto;background:#d83b3b;color:#fff;border-radius:99px;padding:2px 7px;font-size:11px}}.main{{margin-left:235px;padding:24px;max-width:1500px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card,.panel{{background:#fff;border-radius:15px;padding:18px;box-shadow:0 3px 15px #17203312;margin-top:16px}}.big{{font-size:25px;font-weight:800}}.muted{{color:#6d7787;font-size:13px}}.btn,button{{display:inline-block;padding:9px 13px;border:0;border-radius:9px;text-decoration:none;background:#e8eef5;color:#172033;cursor:pointer}}.primary{{background:#1f7a5a;color:#fff}}.danger{{background:#d83b3b;color:#fff}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.field{{margin:12px 0}}.field label{{display:block;font-size:13px;margin-bottom:5px}}.field input,.field select{{width:100%;padding:10px;border:1px solid #d5dce6;border-radius:9px}}.table{{width:100%;border-collapse:collapse}}.table th,.table td{{padding:10px;border-bottom:1px solid #edf0f4;text-align:left}}.badge{{padding:5px 8px;border-radius:99px;font-size:12px}}.ok{{background:#dcfce7;color:#166534}}.bad{{background:#fee2e2;color:#991b1b}}.warn{{background:#fef3c7;color:#92400e}}.avatar{{width:85px;height:85px;object-fit:cover;border-radius:13px}}.notice{{padding:12px 14px;border-radius:10px;background:#eef6ff;margin:12px 0}}.upload-preview{{max-width:420px;width:100%;border-radius:12px;border:1px solid #e4e8ee}}.login{{min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#17324d,#287b63);padding:20px}}.box{{background:#fff;padding:28px;border-radius:18px;width:min(430px,94%);box-shadow:0 18px 50px #0004}}.logo{{width:min(210px,60vw);height:min(210px,60vw);object-fit:contain;margin:0 auto 12px;display:block}}.title{{font-size:22px;font-weight:800;color:#17324d;line-height:1.45;margin:8px 0 22px}}@media(max-width:800px){{.side{{width:72px;padding:10px 7px}}.brand{{margin:2px 0 18px;justify-content:center}}.brand-logo{{width:50px;height:50px}}.brand-name,.nav-label{{display:none}}.nav-link{{justify-content:center;padding:10px 4px;margin:6px 0}}.nav-badge{{position:absolute;margin:0 0 28px 32px}}.main{{margin-left:72px;padding:15px}}.cards{{grid-template-columns:1fr 1fr}}.grid{{grid-template-columns:1fr}}.table{{font-size:13px;display:block;overflow-x:auto;white-space:nowrap}}}}@media(max-width:480px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><aside class="side"><div class="brand"><img class="brand-logo" src="/logo.jpg" alt="Logo"><span class="brand-name">{s["name"]}</span></div>{nav}</aside><main class="main"><h2>{title}</h2>{body}</main></body></html>'''


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        c = db()
        user = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        c.close()
        if user and user["status"] == "Active" and check_password_hash(user["password"], password):
            session.clear()
            session["uid"] = user["id"]
            return redirect("/")
        flash("ইউজারনেম অথবা পাসওয়ার্ড ভুল")
    s = society_settings()
    return f'''<!doctype html><html lang="bn"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{s["name"]}</title><style>body{{margin:0;font-family:system-ui,sans-serif}}.login{{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#17324d,#287b63);padding:20px}}.box{{background:#fff;padding:30px;border-radius:22px;width:min(430px,94%);box-shadow:0 18px 50px #0004;text-align:center}}.logo{{width:min(210px,60vw);height:min(210px,60vw);object-fit:contain;margin:0 auto 12px;display:block}}.title{{font-size:22px;font-weight:800;color:#17324d;line-height:1.45;margin:8px 0 22px}}.field{{text-align:left;margin:14px 0}}.field label{{display:block;font-size:14px;font-weight:700;margin-bottom:7px}}.field input{{width:100%;padding:13px;border:1px solid #d5dce6;border-radius:11px;font-size:16px;box-sizing:border-box}}button{{width:100%;padding:13px;border:0;border-radius:11px;background:#1f7a5a;color:#fff;font-size:16px;font-weight:700}}</style><div class="login"><form class="box" method="post"><img class="logo" src="/logo.jpg" alt="সমিতির লোগো"><div class="title">{s["name"]}</div><div class="field"><label>ইউজারনেম</label><input name="username" autocomplete="username" required></div><div class="field"><label>পাসওয়ার্ড</label><input name="password" type="password" autocomplete="current-password" required></div><button type="submit">লগইন</button></form></div></html>'''


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def home():
    g = guard()
    if g:
        return g
    u = current_user()
    c = db()
    if u["role"] == "admin":
        members = c.execute("SELECT COUNT(*) AS n FROM users WHERE role='member'").fetchone()["n"]
        deposits = c.execute("SELECT COALESCE(SUM(amount),0) AS n FROM deposits").fetchone()["n"]
        pending = c.execute("SELECT COUNT(*) AS n FROM payment_requests WHERE status='pending'").fetchone()["n"]
        recent = c.execute("SELECT d.*,u.name FROM deposits d JOIN users u ON u.id=d.member_id ORDER BY d.id DESC LIMIT 10").fetchall()
        c.close()
        s = society_settings()
        rows = "".join(f'<tr><td>{x["name"]}</td><td>{x["month"]}</td><td>৳{float(x["amount"]):,.2f}</td><td>{x["date"]}</td></tr>' for x in recent)
        body = f'''<div class="cards"><div class="card"><div class="muted">মোট সদস্য</div><div class="big">{members}</div></div><div class="card"><div class="muted">মোট জমা</div><div class="big">৳{float(deposits):,.2f}</div></div><div class="card"><div class="muted">Pending Payment</div><div class="big">{pending}</div></div><div class="card"><div class="muted">মাসিক নির্ধারিত জমা</div><div class="big">৳{float(s["monthly"]):,.2f}</div></div></div><div class="panel"><a class="btn primary" href="/members/new">+ নতুন সদস্য</a> <a class="btn" href="/payment-requests">পেমেন্ট রিকোয়েস্ট</a><h3>সাম্প্রতিক মাসিক জমা</h3><table class="table"><tr><th>সদস্য</th><th>মাস</th><th>জমা</th><th>তারিখ</th></tr>{rows}</table></div>'''
        return layout(body, "Admin Dashboard")
    deposits = c.execute("SELECT COALESCE(SUM(amount),0) AS n FROM deposits WHERE member_id=?", (u["id"],)).fetchone()["n"]
    rows = c.execute("SELECT * FROM deposits WHERE member_id=? ORDER BY id DESC LIMIT 10", (u["id"],)).fetchall()
    c.close()
    body = f'''<div class="cards"><div class="card"><div class="muted">মোট জমা</div><div class="big">৳{float(deposits):,.2f}</div></div><div class="card"><div class="muted">Member ID</div><div class="big">{u["member_id"]}</div></div></div><div class="panel"><a class="btn primary" href="/payment-request/new">+ মাসিক জমা Payment Request</a><h3>সাম্প্রতিক জমা</h3><table class="table"><tr><th>মাস</th><th>পরিমাণ</th><th>তারিখ</th></tr>{''.join(f'<tr><td>{x["month"]}</td><td>৳{float(x["amount"]):,.2f}</td><td>{x["date"]}</td></tr>' for x in rows)}</table></div>'''
    return layout(body, "স্বাগতম, " + u["name"])


@app.route("/members")
def members():
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    q = request.args.get("q", "").strip()
    c = db()
    rows = c.execute("SELECT * FROM users WHERE role='member' AND (name LIKE ? OR member_id LIKE ? OR nid LIKE ? OR phone LIKE ?) ORDER BY id DESC", (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
    c.close()
    html = '<div class="panel"><a class="btn primary" href="/members/new">+ নতুন সদস্য</a><form style="margin-top:14px"><input name="q" placeholder="নাম / ID / NID / মোবাইল" value="'+q+'" style="padding:10px;width:min(420px,100%);border:1px solid #d5dce6;border-radius:9px"><button>Search</button></form></div><div class="panel"><table class="table"><tr><th>ছবি</th><th>ID</th><th>নাম</th><th>NID</th><th>মোবাইল</th><th>Status</th><th></th></tr>'
    for x in rows:
        photo = f'<img class="avatar" src="/uploads/{secure_filename(x["photo"])}">' if x["photo"] else "—"
        status_class = "ok" if x["status"] == "Active" else "bad"
        html += f'<tr><td>{photo}</td><td>{x["member_id"]}</td><td>{x["name"]}</td><td>{x["nid"] or "—"}</td><td>{x["phone"] or "—"}</td><td><span class="badge {status_class}">{x["status"]}</span></td><td><a class="btn" href="/members/{x["id"]}">View</a></td></tr>'
    html += '</table></div>'
    return layout(html, "সদস্য")


def member_form(member=None):
    editing = bool(member)
    return layout(f'''<form class="panel" method="post" enctype="multipart/form-data"><div class="grid"><div class="field"><label>Member ID</label><input name="member_id" value="{member["member_id"] if member else ""}" {'disabled' if editing else 'required'}></div><div class="field"><label>পূর্ণ নাম</label><input name="name" value="{member["name"] if member else ""}" required></div><div class="field"><label>মোবাইল</label><input name="phone" value="{member["phone"] if member else ""}"></div><div class="field"><label>NID Number</label><input name="nid" value="{member["nid"] if member else ""}"></div><div class="field"><label>Username</label><input name="username" value="{member["username"] if member else ""}" {'disabled' if editing else 'required'}></div><div class="field"><label>Password</label><input name="password" type="password" {'required' if not editing else ''}></div><div class="field"><label>Joining Date</label><input name="joining" type="date" value="{member["joining"] if member else date.today()}" required></div><div class="field"><label>Status</label><select name="status"><option {'selected' if not member or member["status"]=="Active" else ''}>Active</option><option {'selected' if member and member["status"]=="Inactive" else ''}>Inactive</option></select></div><div class="field"><label>সদস্যের ছবি</label><input name="photo" type="file" accept=".jpg,.jpeg,.png,.webp"></div></div>{f'<p><img class="avatar" src="/uploads/{secure_filename(member["photo"])}"></p>' if member and member["photo"] else ''}<button class="btn primary">SAVE</button> <a class="btn" href="/members">Cancel</a></form>''', "সদস্য সম্পাদনা" if editing else "নতুন সদস্য")


@app.route("/members/new", methods=["GET", "POST"])
def new_member():
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    if request.method == "POST":
        photo = ""
        f = request.files.get("photo")
        if f and f.filename:
            ext = f.filename.rsplit(".", 1)[-1].lower()
            if ext not in {"jpg", "jpeg", "png", "webp"}: return "Invalid image", 400
            photo = secrets.token_hex(10) + "." + ext
            f.save(os.path.join(UPLOADS, photo))
        try:
            c = db()
            c.execute("INSERT INTO users(member_id,name,phone,nid,photo,username,password,role,status,joining) VALUES(?,?,?,?,?,?,?,?,?,?)", (request.form["member_id"], request.form["name"], request.form.get("phone", ""), request.form.get("nid", ""), photo, request.form["username"], generate_password_hash(request.form["password"]), "member", request.form["status"], request.form["joining"]))
            c.commit(); c.close()
            log_action("MEMBER_CREATED", request.form["member_id"])
            return redirect("/members")
        except Exception:
            return "Member ID or Username already exists", 409
    return member_form()


@app.route("/members/<int:member_id>")
def view_member(member_id):
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    c = db()
    m = c.execute("SELECT * FROM users WHERE id=? AND role='member'", (member_id,)).fetchone()
    deposits = c.execute("SELECT * FROM deposits WHERE member_id=? ORDER BY id DESC", (member_id,)).fetchall()
    c.close()
    if not m: return "Member not found", 404
    total = sum(float(x["amount"]) for x in deposits)
    photo = f'<img class="avatar" src="/uploads/{secure_filename(m["photo"])}">' if m["photo"] else ""
    body = f'''<div class="panel">{photo}<p><b>Member ID:</b> {m["member_id"]}</p><p><b>নাম:</b> {m["name"]}</p><p><b>NID:</b> {m["nid"] or "—"}</p><p><b>মোবাইল:</b> {m["phone"] or "—"}</p><p><b>মোট জমা:</b> ৳{total:,.2f}</p><a class="btn" href="/members/{member_id}/edit">Edit</a> <a class="btn primary" href="/deposits/new/{member_id}">+ জমা</a></div><div class="panel"><h3>মাসিক জমা</h3><table class="table"><tr><th>মাস</th><th>পরিমাণ</th><th>তারিখ</th><th>Method</th></tr>{''.join(f'<tr><td>{x["month"]}</td><td>৳{float(x["amount"]):,.2f}</td><td>{x["date"]}</td><td>{x["method"]}</td></tr>' for x in deposits)}</table></div>'''
    return layout(body, m["name"])


@app.route("/members/<int:member_id>/edit", methods=["GET", "POST"])
def edit_member(member_id):
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    c = db(); member = c.execute("SELECT * FROM users WHERE id=? AND role='member'", (member_id,)).fetchone()
    if not member:
        c.close(); return "Member not found", 404
    if request.method == "POST":
        photo = member["photo"]
        f = request.files.get("photo")
        if f and f.filename:
            ext = f.filename.rsplit(".", 1)[-1].lower()
            if ext not in {"jpg", "jpeg", "png", "webp"}: return "Invalid image", 400
            photo = secrets.token_hex(10) + "." + ext
            f.save(os.path.join(UPLOADS, photo))
        password = generate_password_hash(request.form["password"]) if request.form.get("password") else member["password"]
        c.execute("UPDATE users SET name=?,phone=?,nid=?,photo=?,password=?,status=?,joining=? WHERE id=?", (request.form["name"], request.form.get("phone", ""), request.form.get("nid", ""), photo, password, request.form["status"], request.form["joining"], member_id))
        c.commit(); c.close(); log_action("MEMBER_UPDATED", member["member_id"]); return redirect(f"/members/{member_id}")
    c.close(); return member_form(member)


@app.route("/deposits/new/<int:member_id>", methods=["GET", "POST"])
def new_deposit(member_id):
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    c = db(); member = c.execute("SELECT * FROM users WHERE id=? AND role='member'", (member_id,)).fetchone(); monthly = c.execute("SELECT monthly FROM settings WHERE id=1").fetchone()["monthly"]
    if not member:
        c.close(); return "Member not found", 404
    if request.method == "POST":
        amount = float(request.form["amount"])
        if amount <= 0: c.close(); return "Amount must be positive", 400
        c.execute("INSERT INTO deposits(member_id,month,amount,date,method,note) VALUES(?,?,?,?,?,?)", (member_id, request.form["month"], amount, request.form["date"], request.form["method"], request.form.get("note", "")))
        c.commit(); c.close(); log_action("DEPOSIT_RECORDED", f'{member["member_id"]} / {request.form["month"]} / {amount}'); return redirect(f"/members/{member_id}")
    c.close()
    return layout(f'''<form class="panel" method="post"><div class="grid"><div class="field"><label>মাস</label><input name="month" type="month" value="{date.today().strftime('%Y-%m')}" required></div><div class="field"><label>পরিমাণ</label><input name="amount" type="number" min="0.01" step="0.01" value="{monthly}" required></div><div class="field"><label>তারিখ</label><input name="date" type="date" value="{date.today()}" required></div><div class="field"><label>Method</label><select name="method"><option>Cash</option><option>Bank</option><option>bKash</option><option>Mobile Banking</option></select></div></div><div class="field"><label>Note</label><input name="note"></div><button class="btn primary">SAVE DEPOSIT</button></form>''', "মাসিক জমা — " + member["name"])


@app.route("/collections")
def collections():
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    month = request.args.get("month", date.today().strftime("%Y-%m"))
    c = db(); monthly = c.execute("SELECT monthly FROM settings WHERE id=1").fetchone()["monthly"]
    rows = c.execute("SELECT u.id,u.member_id,u.name,COALESCE(SUM(d.amount),0) AS amount FROM users u LEFT JOIN deposits d ON d.member_id=u.id AND d.month=? WHERE u.role='member' GROUP BY u.id ORDER BY u.id", (month,)).fetchall(); c.close()
    html = f'<div class="panel"><form><input name="month" type="month" value="{month}"><button>View</button></form></div><div class="panel"><table class="table"><tr><th>ID</th><th>নাম</th><th>নির্ধারিত</th><th>জমা</th><th>Status</th><th></th></tr>'
    for x in rows:
        amount = float(x["amount"] or 0); target = float(monthly)
        cls = "ok" if amount >= target else ("warn" if amount else "bad")
        status = "Paid" if amount >= target else ("Partial" if amount else "Due")
        html += f'<tr><td>{x["member_id"]}</td><td>{x["name"]}</td><td>৳{target:,.2f}</td><td>৳{amount:,.2f}</td><td><span class="badge {cls}">{status}</span></td><td><a class="btn" href="/deposits/new/{x["id"]}">Record</a></td></tr>'
    html += '</table></div>'
    return layout(html, "মাসিক জমা")


@app.route("/transactions")
def transactions():
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    c = db(); rows = c.execute("SELECT d.*,u.name FROM deposits d JOIN users u ON u.id=d.member_id ORDER BY d.id DESC").fetchall(); c.close()
    html = '<div class="panel"><h3>মাসিক জমার লেনদেন</h3><table class="table"><tr><th>তারিখ</th><th>সদস্য</th><th>মাস</th><th>জমা</th><th>Method</th></tr>'
    html += "".join(f'<tr><td>{x["date"]}</td><td>{x["name"]}</td><td>{x["month"]}</td><td>৳{float(x["amount"]):,.2f}</td><td>{x["method"]}</td></tr>' for x in rows)
    return layout(html + '</table></div>', "লেনদেন")


@app.route("/reports")
def reports():
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    c = db(); members = c.execute("SELECT COUNT(*) AS n FROM users WHERE role='member'").fetchone()["n"]; deposits = c.execute("SELECT COALESCE(SUM(amount),0) AS n FROM deposits").fetchone()["n"]; c.close()
    return layout(f'<div class="cards"><div class="card"><div class="muted">মোট সদস্য</div><div class="big">{members}</div></div><div class="card"><div class="muted">মোট মাসিক জমা</div><div class="big">৳{float(deposits):,.2f}</div></div></div><div class="panel">রিপোর্ট শুধুমাত্র মাসিক জমার হিসাবের উপর ভিত্তি করে তৈরি।</div>', "রিপোর্ট")


@app.route("/logs")
def logs():
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    c = db(); rows = c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 200").fetchall(); c.close()
    return layout('<div class="panel"><table class="table"><tr><th>সময়</th><th>Action</th><th>Target</th></tr>' + "".join(f'<tr><td>{x["at"]}</td><td>{x["action"]}</td><td>{x["target"]}</td></tr>' for x in rows) + '</table></div>', "অডিট লগ")


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    if request.method == "POST":
        c = db(); c.execute("UPDATE settings SET name=?,monthly=? WHERE id=1", (request.form["name"], float(request.form["monthly"]))); c.commit(); c.close(); return redirect("/settings")
    s = society_settings()
    return layout(f'<form class="panel" method="post"><div class="grid"><div class="field"><label>সমিতির নাম</label><input name="name" value="{s["name"]}"></div><div class="field"><label>মাসিক জমা</label><input name="monthly" type="number" min="0" step="0.01" value="{s["monthly"]}"></div></div><button class="btn primary">SAVE</button></form>', "সেটিংস")


@app.route("/me")
def my_account():
    g = guard()
    if g: return g
    u = current_user()
    c = db(); deposits = c.execute("SELECT * FROM deposits WHERE member_id=? ORDER BY id DESC", (u["id"],)).fetchall(); requests = c.execute("SELECT * FROM payment_requests WHERE app_user_id=? ORDER BY created_at DESC", (u["id"],)).fetchall(); c.close()
    photo = f'<img class="avatar" src="/uploads/{secure_filename(u["photo"])}">' if u["photo"] else ""
    req_rows = "".join(f'<tr><td>{str(x["month"])[:7]}</td><td>৳{float(x["amount"]):,.2f}</td><td>{x["transaction_id"]}</td><td><span class="badge {"ok" if x["status"]=="approved" else ("bad" if x["status"]=="rejected" else "warn")}">{x["status"]}</span></td></tr>' for x in requests)
    dep_rows = "".join(f'<tr><td>{x["month"]}</td><td>৳{float(x["amount"]):,.2f}</td><td>{x["date"]}</td></tr>' for x in deposits)
    return layout(f'''<div class="panel">{photo}<p><b>নাম:</b> {u["name"]}</p><p><b>Member ID:</b> {u["member_id"]}</p><p><b>NID:</b> {u["nid"] or "—"}</p><p><b>মোবাইল:</b> {u["phone"] or "—"}</p><a class="btn primary" href="/payment-request/new">+ মাসিক জমা Payment Request</a></div><div class="panel"><h3>আমার মাসিক জমা</h3><table class="table"><tr><th>মাস</th><th>পরিমাণ</th><th>তারিখ</th></tr>{dep_rows}</table></div><div class="panel"><h3>আমার Payment Requests</h3><table class="table"><tr><th>মাস</th><th>পরিমাণ</th><th>Transaction ID</th><th>Status</th></tr>{req_rows}</table></div>''', "আমার হিসাব")


@app.route("/payment-request/new", methods=["GET", "POST"])
def payment_request_new():
    g = guard()
    if g: return g
    u = current_user()
    if u["role"] != "member": return redirect("/payment-requests")
    if request.method == "POST":
        month = request.form.get("month", "").strip()
        transaction_id = request.form.get("transaction_id", "").strip()
        try:
            amount = float(request.form.get("amount", "0"))
        except ValueError:
            amount = 0
        screenshot = request.files.get("screenshot")
        if len(month) != 7 or amount <= 0 or not transaction_id or not screenshot or not screenshot.filename:
            return "মাস, পরিমাণ, Transaction ID এবং Screenshot আবশ্যক।", 400
        try:
            date.fromisoformat(month + "-01")
        except ValueError:
            return "Invalid month", 400
        ext = screenshot.filename.rsplit(".", 1)[-1].lower()
        if ext not in {"jpg", "jpeg", "png", "webp"}:
            return "শুধু JPG, JPEG, PNG বা WEBP ছবি দিন।", 400
        c = db(); existing = c.execute("SELECT COUNT(*) AS n FROM payment_requests WHERE app_user_id=? AND month=? AND status='pending'", (u["id"], month + "-01")).fetchone()["n"]; c.close()
        if existing:
            return "এই মাসের একটি Payment Request ইতিমধ্যে Pending আছে।", 409
        path = f'{u["id"]}/{month}-{uuid4().hex}.{ext}'
        stored, error = upload_screenshot(screenshot, path)
        if error: return "Screenshot upload failed: " + error, 500
        c = db(); c.execute("INSERT INTO payment_requests(id,member_id,app_user_id,month,amount,transaction_id,screenshot,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid4()), str(uuid4()), u["id"], month + "-01", amount, transaction_id, stored, "pending", datetime.now().isoformat(timespec="seconds"))); c.commit(); c.close()
        log_action("PAYMENT_REQUEST", f'{u["member_id"]} / {month} / {amount}')
        return redirect("/me")
    s = society_settings()
    return layout(f'''<div class="panel"><div class="notice">bKash নম্বর: <b>{BKASH_NUMBER or "Admin সেট করেননি"}</b><br>টাকা পাঠানোর পর Transaction ID এবং Screenshot দিন। Admin অনুমোদন না করা পর্যন্ত আপনার হিসাবে টাকা যোগ হবে না।</div><form method="post" enctype="multipart/form-data"><div class="field"><label>মাস</label><input name="month" type="month" value="{date.today().strftime('%Y-%m')}" required></div><div class="field"><label>পরিমাণ</label><input name="amount" type="number" min="1" step="0.01" value="{s["monthly"]}" required></div><div class="field"><label>bKash Transaction ID</label><input name="transaction_id" required></div><div class="field"><label>Payment Screenshot</label><input name="screenshot" type="file" accept="image/jpeg,image/png,image/webp" required></div><button class="btn primary">Payment Request পাঠান</button></form></div>''', "মাসিক জমা")


@app.route("/payment-requests")
def payment_requests():
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    status = request.args.get("status", "pending")
    if status not in {"pending", "approved", "rejected", "all"}: status = "pending"
    c = db()
    query = "SELECT p.*,u.name,u.member_id AS member_code FROM payment_requests p LEFT JOIN users u ON u.id=p.app_user_id"
    if status == "all": rows = c.execute(query + " ORDER BY p.created_at DESC").fetchall()
    else: rows = c.execute(query + " WHERE p.status=? ORDER BY p.created_at DESC", (status,)).fetchall()
    c.close()
    tabs = " ".join(f'<a class="btn {"primary" if status==s else ""}" href="/payment-requests?status={s}">{label}</a>' for s,label in [("pending","Pending"),("approved","Approved"),("rejected","Rejected"),("all","All")])
    html = f'<div class="panel">{tabs}</div><div class="panel"><table class="table"><tr><th>Member</th><th>মাস</th><th>Amount</th><th>Transaction ID</th><th>Status</th><th></th></tr>'
    for x in rows:
        html += f'<tr><td>{x["name"] or "—"}<br><span class="muted">{x["member_code"] or ""}</span></td><td>{str(x["month"])[:7]}</td><td>৳{float(x["amount"]):,.2f}</td><td>{x["transaction_id"]}</td><td>{x["status"]}</td><td><a class="btn" href="/payment-requests/{x["id"]}">Review</a></td></tr>'
    html += '</table></div>'
    return layout(html, "Payment Requests")


@app.route("/payment-requests/<rid>", methods=["GET", "POST"])
def payment_request_review(rid):
    g = guard()
    if g: return g
    if not is_admin(): return "Forbidden", 403
    c = db(); item = c.execute("SELECT p.*,u.name,u.member_id AS member_code FROM payment_requests p LEFT JOIN users u ON u.id=p.app_user_id WHERE p.id=?", (rid,)).fetchone(); c.close()
    if not item: return "Payment request not found", 404
    if request.method == "POST":
        action = request.form.get("action")
        note = request.form.get("admin_note", "").strip()
        if action not in {"approve", "reject"}: return "Invalid action", 400
        if item["status"] != "pending": return "এই request ইতিমধ্যে processed.", 409
        c = db()
        if action == "approve":
            month = str(item["month"])[:7]
            already = c.execute("SELECT COUNT(*) AS n FROM deposits WHERE member_id=? AND month=?", (item["app_user_id"], month)).fetchone()["n"]
            if already:
                c.close(); return "এই সদস্যের এই মাসের জমা ইতিমধ্যে আছে।", 409
            c.execute("INSERT INTO deposits(member_id,month,amount,date,method,note) VALUES(?,?,?,?,?,?)", (item["app_user_id"], month, item["amount"], str(date.today()), "bKash", "TX: " + item["transaction_id"]))
            c.execute("UPDATE payment_requests SET status=?,admin_note=?,approved_at=?,approved_by=?,admin_user_id=? WHERE id=?", ("approved", note, datetime.now().isoformat(timespec="seconds"), str(uuid4()), current_user()["id"], rid))
            c.commit(); c.close(); log_action("PAYMENT_APPROVED", f'{item["member_code"]} / {month} / {item["amount"]} / {item["transaction_id"]}')
            return redirect("/payment-requests?status=approved")
        c.execute("UPDATE payment_requests SET status=?,admin_note=?,approved_by=?,admin_user_id=? WHERE id=?", ("rejected", note, str(uuid4()), current_user()["id"], rid)); c.commit(); c.close(); log_action("PAYMENT_REJECTED", f'{item["member_code"]} / {item["transaction_id"]}')
        return redirect("/payment-requests?status=rejected")
    image = signed_url(item["screenshot"])
    image_html = f'<p><a class="btn" target="_blank" href="{image}">Screenshot দেখুন</a></p><img class="upload-preview" src="{image}" alt="Payment screenshot">' if image else '<p class="bad">Screenshot পাওয়া যাচ্ছে না। Supabase Storage configuration পরীক্ষা করুন।</p>'
    actions = f'''<form method="post"><div class="field"><label>Admin Note</label><input name="admin_note"></div><button class="btn primary" name="action" value="approve">Approve</button> <button class="btn danger" name="action" value="reject">Reject</button></form>''' if item["status"] == "pending" else '<p class="muted">এই request ইতিমধ্যে processed.</p>'
    return layout(f'''<div class="panel"><h3>Payment Request Review</h3><p><b>Member:</b> {item["name"] or "—"} ({item["member_code"] or "—"})</p><p><b>মাস:</b> {str(item["month"])[:7]}</p><p><b>পরিমাণ:</b> ৳{float(item["amount"]):,.2f}</p><p><b>Transaction ID:</b> {item["transaction_id"]}</p><p><b>Status:</b> {item["status"]}</p>{image_html}{actions}</div>''', "Payment Request Review")


@app.route("/uploads/<name>")
def uploads(name):
    return send_from_directory(UPLOADS, secure_filename(name))


@app.route("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
