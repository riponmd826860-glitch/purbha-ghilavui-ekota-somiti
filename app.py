import os,sqlite3,secrets
from datetime import date,datetime
from flask import Flask,request,session,redirect,url_for,render_template_string,flash,send_from_directory
from werkzeug.security import generate_password_hash,check_password_hash
from werkzeug.utils import secure_filename
BASE=os.path.dirname(__file__); DB=os.path.join(BASE,'somobay.db'); UP=os.path.join(BASE,'uploads'); os.makedirs(UP,exist_ok=True)
app=Flask(__name__); app.secret_key=os.environ.get('SECRET_KEY',secrets.token_hex(32)); app.config['MAX_CONTENT_LENGTH']=5*1024*1024

def db(): c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
 c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY,name TEXT,monthly REAL);CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,member_id TEXT UNIQUE,name TEXT,phone TEXT,nid TEXT,photo TEXT,username TEXT UNIQUE,password TEXT,role TEXT,status TEXT,joining TEXT);CREATE TABLE IF NOT EXISTS deposits(id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER,month TEXT,amount REAL,date TEXT,method TEXT,note TEXT);CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER,amount REAL,date TEXT,reason TEXT);CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT,target TEXT,at TEXT);''')
 if not c.execute('select 1 from settings').fetchone(): c.execute('insert into settings values(1,?,?)',('পূর্ব ঘিলাভুই যুব একতা সমবায় সমিতি',1000))
 if not c.execute("select 1 from users where username='admin'").fetchone(): c.execute('insert into users(member_id,name,username,password,role,status,joining) values(?,?,?,?,?,?,?)',('ADMIN','সমিতির Admin','admin',generate_password_hash('admin123'),'admin','Active',str(date.today())))
 c.commit();c.close()
init()
def me():
 if not session.get('uid'): return None
 c=db(); x=c.execute('select * from users where id=?',(session['uid'],)).fetchone();c.close();return x
def req_admin(): return me() and me()['role']=='admin'
def settings(): c=db();x=c.execute('select * from settings where id=1').fetchone();c.close();return x
def layout(body,title=''):
 s=settings(); u=me(); nav=''
 if u and u['role']=='admin': nav='''<a href="/">Dashboard</a><a href="/members">Members</a><a href="/collections">Monthly Collection</a><a href="/transactions">Transactions</a><a href="/reports">Reports</a><a href="/logs">Audit Log</a><a href="/settings">Settings</a>'''
 elif u: nav='<a href="/">Home</a><a href="/me">My Account</a>'
 return '''<!doctype html><html lang="bn"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'''+s['name']+'''</title><style>*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:#f4f7fb;color:#172033}.side{position:fixed;inset:0 auto 0 0;width:230px;background:#17324d;color:#fff;padding:18px}.brand{font-weight:800;line-height:1.4;margin-bottom:20px}.side a{display:block;color:#dce7f2;text-decoration:none;padding:10px;border-radius:8px}.side a:hover{background:#274966}.main{margin-left:230px;padding:24px;max-width:1500px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card,.panel{background:#fff;border-radius:15px;padding:18px;box-shadow:0 3px 15px #17203312;margin-top:16px}.big{font-size:25px;font-weight:800}.muted{color:#6d7787;font-size:13px}.btn,button{display:inline-block;padding:9px 13px;border:0;border-radius:9px;text-decoration:none;background:#e8eef5;color:#172033;cursor:pointer}.primary{background:#1f7a5a;color:#fff}.danger{background:#d83b3b;color:#fff}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.field{margin:12px 0}.field label{display:block;font-size:13px;margin-bottom:5px}.field input,.field select{width:100%;padding:10px;border:1px solid #d5dce6;border-radius:9px}.table{width:100%;border-collapse:collapse}.table th,.table td{padding:10px;border-bottom:1px solid #edf0f4;text-align:left}.badge{padding:5px 8px;border-radius:99px;font-size:12px}.ok{background:#dcfce7;color:#166534}.bad{background:#fee2e2;color:#991b1b}.warn{background:#fef3c7;color:#92400e}.avatar{width:85px;height:85px;object-fit:cover;border-radius:13px}.login{min-height:100vh;display:grid;place-items:center;background:linear-gradient(135deg,#17324d,#287b63)}.box{background:#fff;padding:28px;border-radius:18px;width:min(430px,92%)}@media(max-width:800px){.side{width:65px;padding:8px}.brand{font-size:0}.brand:after{content:'পূ';font-size:22px}.side a{font-size:0;text-align:center}.side a:before{content:'•';font-size:22px}.main{margin-left:65px}.cards{grid-template-columns:1fr 1fr}}@media(max-width:550px){.grid,.cards{grid-template-columns:1fr}.main{padding:12px}.table{font-size:12px}}</style><div class="side"><div class="brand">'''+s['name']+'''</div>'''+nav+(' <a href="/logout">Logout</a>' if u else '')+'''</div><main class="main"><h2>'''+title+'''</h2>'''+''.join(f'<div class="panel">{m}</div>' for m in [f'<b>{x[0]}</b>' for x in []])+body+'''</main></html>'''

def guard():
 if not me(): return redirect('/login')
 return None
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  c=db();u=c.execute('select * from users where username=?',(request.form['username'].strip(),)).fetchone();c.close()
  if u and u['status']=='Active' and check_password_hash(u['password'],request.form['password']): session['uid']=u['id'];return redirect('/')
  flash('Login তথ্য ভুল')
 return '''<div class="login"><form class="box" method="post"><h2>'''+settings()['name']+'''</h2><div class="field"><label>Username / Member ID</label><input name="username" required></div><div class="field"><label>Password</label><input name="password" type="password" required></div><button class="primary" style="width:100%">LOGIN</button><p class="muted">Admin demo: admin / admin123</p></form></div>'''
@app.route('/logout')
def logout(): session.clear();return redirect('/login')
@app.route('/')
def home():
 g=guard();
 if g:return g
 u=me();c=db()
 if u['role']=='admin':
  members=c.execute("select count(*) n from users where role='member'").fetchone()['n'];dep=c.execute('select coalesce(sum(amount),0)n from deposits').fetchone()['n'];wd=c.execute('select coalesce(sum(amount),0)n from withdrawals').fetchone()['n'];cur=dep-wd
  recent=c.execute('select d.*,u.name from deposits d join users u on u.id=d.member_id order by d.id desc limit 10').fetchall();c.close()
  b=f'''<div class="cards"><div class="card"><div class="muted">মোট সদস্য</div><div class="big">{members}</div></div><div class="card"><div class="muted">মোট জমা</div><div class="big">৳{dep:,.2f}</div></div><div class="card"><div class="muted">মোট উত্তোলন</div><div class="big">৳{wd:,.2f}</div></div><div class="card"><div class="muted">বর্তমান তহবিল</div><div class="big">৳{cur:,.2f}</div></div></div><div class="panel"><a class="btn primary" href="/members/new">+ নতুন সদস্য</a><h3>সাম্প্রতিক জমা</h3><table class="table"><tr><th>সদস্য</th><th>মাস</th><th>জমা</th><th>তারিখ</th></tr>'''+''.join(f'<tr><td>{x["name"]}</td><td>{x["month"]}</td><td>৳{x["amount"]}</td><td>{x["date"]}</td></tr>' for x in recent)+'''</table></div>'''
  return layout(b,'Admin Dashboard')
 c=db();dep=c.execute('select coalesce(sum(amount),0)n from deposits where member_id=?',(u['id'],)).fetchone()['n'];wd=c.execute('select coalesce(sum(amount),0)n from withdrawals where member_id=?',(u['id'],)).fetchone()['n'];rows=c.execute('select * from deposits where member_id=? order by id desc limit 10',(u['id'],)).fetchall();c.close();b=f'''<div class="cards"><div class="card"><div class="muted">বর্তমান ব্যালেন্স</div><div class="big">৳{dep-wd:,.2f}</div></div><div class="card"><div class="muted">মোট জমা</div><div class="big">৳{dep:,.2f}</div></div><div class="card"><div class="muted">মোট উত্তোলন</div><div class="big">৳{wd:,.2f}</div></div><div class="card"><div class="muted">Member ID</div><div class="big">{u['member_id']}</div></div></div><div class="panel"><h3>আমার জমা</h3><table class="table"><tr><th>মাস</th><th>পরিমাণ</th><th>তারিখ</th></tr>'''+''.join(f'<tr><td>{x["month"]}</td><td>৳{x["amount"]}</td><td>{x["date"]}</td></tr>' for x in rows)+'''</table></div>''';return layout(b,'স্বাগতম, '+u['name'])
@app.route('/members')
def members():
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 q=request.args.get('q','');c=db();rows=c.execute("select * from users where role='member' and (name like ? or member_id like ? or nid like ? or phone like ?) order by id desc",(f'%{q}%',)*4).fetchall();c.close()
 b='''<a class="btn primary" href="/members/new">+ নতুন সদস্য</a><div class="panel"><form><input name="q" placeholder="নাম / ID / NID / মোবাইল" value="'''+q+'''" style="padding:10px;width:300px"><button>Search</button></form><table class="table"><tr><th>ছবি</th><th>ID</th><th>নাম</th><th>NID</th><th>মোবাইল</th><th>Status</th><th></th></tr>'''+''.join(f'<tr><td>{"<img class=avatar src=/uploads/"+x["photo"]+">" if x["photo"] else "—"}</td><td>{x["member_id"]}</td><td>{x["name"]}</td><td>{x["nid"] or "—"}</td><td>{x["phone"] or "—"}</td><td><span class="badge {"ok" if x["status"]=="Active" else "bad"}">{x["status"]}</span></td><td><a class="btn" href="/members/{x["id"]}">View</a></td></tr>' for x in rows)+'''</table></div>''';return layout(b,'Members')

def form_page(m=None):
 return layout('''<form class="panel" method="post" enctype="multipart/form-data"><div class="grid">'''+(f'<div class="field"><label>Member ID</label><input value="{m["member_id"]}" disabled></div>' if m else '<div class="field"><label>Member ID</label><input name="member_id" required></div>')+f'''<div class="field"><label>পূর্ণ নাম</label><input name="name" value="{m["name"] if m else ""}" required></div><div class="field"><label>মোবাইল</label><input name="phone" value="{m["phone"] if m else ""}"></div><div class="field"><label>NID Number</label><input name="nid" value="{m["nid"] if m else ""}"></div>'''+(f'<div class="field"><label>Username</label><input value="{m["username"]}" disabled></div>' if m else '<div class="field"><label>Username</label><input name="username" required></div>')+f'''<div class="field"><label>Password</label><input name="password" type="password" {'required' if not m else ''}></div><div class="field"><label>Joining Date</label><input name="joining" type="date" value="{m["joining"] if m else date.today()}" required></div><div class="field"><label>Status</label><select name="status"><option {'selected' if not m or m['status']=='Active' else ''}>Active</option><option {'selected' if m and m['status']=='Inactive' else ''}>Inactive</option></select></div><div class="field"><label>সদস্যের ছবি</label><input name="photo" type="file" accept=".jpg,.jpeg,.png,.webp"></div></div>'''+(f'<p><img class=avatar src="/uploads/{m["photo"]}"></p>' if m and m['photo'] else '')+'''<button class="btn primary">SAVE</button> <a class="btn" href="/members">Cancel</a></form>''','Edit Member' if m else 'নতুন সদস্য')
@app.route('/members/new',methods=['GET','POST'])
def new_member():
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 if request.method=='POST':
  photo='';f=request.files.get('photo')
  if f and f.filename:
   ext=f.filename.rsplit('.',1)[-1].lower()
   if ext not in {'jpg','jpeg','png','webp'}: return 'Invalid image',400
   photo=secrets.token_hex(10)+'.'+ext;f.save(os.path.join(UP,photo))
  try:
   c=db();c.execute('insert into users(member_id,name,phone,nid,photo,username,password,role,status,joining) values(?,?,?,?,?,?,?,?,?,?)',(request.form['member_id'],request.form['name'],request.form.get('phone',''),request.form.get('nid',''),photo,request.form['username'],generate_password_hash(request.form['password']),'member',request.form['status'],request.form['joining']));c.commit();c.close();return redirect('/members')
  except sqlite3.IntegrityError:return 'Member ID or Username already exists',409
 return form_page()
@app.route('/members/<int:i>')
def view_member(i):
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 c=db();m=c.execute('select * from users where id=?',(i,)).fetchone();ds=c.execute('select * from deposits where member_id=? order by id desc',(i,)).fetchall();ws=c.execute('select * from withdrawals where member_id=? order by id desc',(i,)).fetchall();c.close()
 dep=sum(x['amount'] for x in ds);wd=sum(x['amount'] for x in ws)
 b=(f'''<div class="panel">{('<img class=avatar src="/uploads/'+m['photo']+'">') if m['photo'] else ''}<p><b>Member ID:</b> {m['member_id']}</p><p><b>NID:</b> {m['nid'] or '—'}</p><p><b>মোবাইল:</b> {m['phone'] or '—'}</p><p><b>বর্তমান ব্যালেন্স:</b> ৳{dep-wd:,.2f}</p><a class="btn" href="/members/{i}/edit">Edit</a> <a class="btn primary" href="/deposits/new/{i}">+ জমা</a> <a class="btn" href="/withdrawals/new/{i}">উত্তোলন</a></div><div class="panel"><h3>জমা</h3><table class="table"><tr><th>মাস</th><th>পরিমাণ</th><th>তারিখ</th></tr>'''+''.join(f'<tr><td>{x["month"]}</td><td>৳{x["amount"]}</td><td>{x["date"]}</td></tr>' for x in ds)+'''</table></div><div class="panel"><h3>উত্তোলন</h3><table class="table"><tr><th>তারিখ</th><th>পরিমাণ</th><th>কারণ</th></tr>'''+''.join(f'<tr><td>{x["date"]}</td><td>৳{x["amount"]}</td><td>{x["reason"] or "—"}</td></tr>' for x in ws)+'''</table></div>''');return layout(b,m['name'])
@app.route('/members/<int:i>/edit',methods=['GET','POST'])
def edit_member(i):
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 c=db();m=c.execute('select * from users where id=?',(i,)).fetchone()
 if request.method=='POST':
  photo=m['photo'];f=request.files.get('photo')
  if f and f.filename:
   ext=f.filename.rsplit('.',1)[-1].lower();photo=secrets.token_hex(10)+'.'+ext;f.save(os.path.join(UP,photo))
  pw=generate_password_hash(request.form['password']) if request.form.get('password') else m['password']
  c.execute('update users set name=?,phone=?,nid=?,photo=?,password=?,status=?,joining=? where id=?',(request.form['name'],request.form.get('phone',''),request.form.get('nid',''),photo,pw,request.form['status'],request.form['joining'],i));c.commit();c.close();return redirect('/members/'+str(i))
 c.close();return form_page(m)
@app.route('/deposits/new/<int:i>',methods=['GET','POST'])
def new_dep(i):
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 c=db();m=c.execute('select * from users where id=?',(i,)).fetchone();monthly=c.execute('select monthly from settings').fetchone()['monthly']
 if request.method=='POST':c.execute('insert into deposits(member_id,month,amount,date,method,note) values(?,?,?,?,?,?)',(i,request.form['month'],float(request.form['amount']),request.form['date'],request.form['method'],request.form.get('note','')));c.commit();c.close();return redirect('/members/'+str(i))
 c.close();return layout(f'''<form class="panel" method="post"><div class="grid"><div class="field"><label>মাস</label><input name="month" type="month" value="{date.today().strftime('%Y-%m')}" required></div><div class="field"><label>পরিমাণ</label><input name="amount" type="number" step=".01" value="{monthly}"></div><div class="field"><label>তারিখ</label><input name="date" type="date" value="{date.today()}"></div><div class="field"><label>Method</label><select name="method"><option>Cash</option><option>Bank</option><option>Mobile Banking</option></select></div></div><button class="btn primary">SAVE DEPOSIT</button></form>''','টাকা জমা — '+m['name'])
@app.route('/withdrawals/new/<int:i>',methods=['GET','POST'])
def new_wd(i):
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 c=db();m=c.execute('select * from users where id=?',(i,)).fetchone();dep=c.execute('select coalesce(sum(amount),0)n from deposits where member_id=?',(i,)).fetchone()['n'];wd=c.execute('select coalesce(sum(amount),0)n from withdrawals where member_id=?',(i,)).fetchone()['n'];bal=dep-wd
 if request.method=='POST':
  a=float(request.form['amount'])
  if a<=0 or a>bal:return 'Insufficient balance',400
  c.execute('insert into withdrawals(member_id,amount,date,reason) values(?,?,?,?)',(i,a,request.form['date'],request.form.get('reason','')));c.commit();c.close();return redirect('/members/'+str(i))
 c.close();return layout(f'''<div class="panel"><p>বর্তমান ব্যালেন্স: <b>৳{bal:,.2f}</b></p><form method="post"><div class="field"><label>পরিমাণ</label><input name="amount" type="number" step=".01" required></div><div class="field"><label>তারিখ</label><input name="date" type="date" value="{date.today()}"></div><div class="field"><label>কারণ</label><input name="reason"></div><button class="btn primary">CONFIRM</button></form></div>''','টাকা উত্তোলন — '+m['name'])
@app.route('/collections')
def collections():
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 mo=request.args.get('month',date.today().strftime('%Y-%m'));c=db();monthly=c.execute('select monthly from settings').fetchone()['monthly'];rows=c.execute('select u.id,u.member_id,u.name,coalesce(sum(d.amount),0)amount from users u left join deposits d on d.member_id=u.id and d.month=? where u.role="member" group by u.id',(mo,)).fetchall();c.close()
 b='<form class="panel"><input name="month" type="month" value="'+mo+'"><button>View</button></form><div class="panel"><table class="table"><tr><th>ID</th><th>নাম</th><th>নির্ধারিত</th><th>জমা</th><th>Status</th><th></th></tr>'+''.join(f'<tr><td>{x["member_id"]}</td><td>{x["name"]}</td><td>৳{monthly}</td><td>৳{x["amount"]}</td><td><span class="badge {"ok" if x["amount"]>=monthly else ("warn" if x["amount"] else "bad")}">{"Paid" if x["amount"]>=monthly else ("Partial" if x["amount"] else "Due")}</span></td><td><a class="btn" href="/deposits/new/{x["id"]}">Record</a></td></tr>' for x in rows)+'</table></div>';return layout(b,'Monthly Collection')
@app.route('/transactions')
def transactions():
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 c=db();ds=c.execute('select d.*,u.name from deposits d join users u on u.id=d.member_id order by d.id desc').fetchall();ws=c.execute('select w.*,u.name from withdrawals w join users u on u.id=w.member_id order by w.id desc').fetchall();c.close();b='<div class="panel"><h3>Deposits</h3><table class="table"><tr><th>তারিখ</th><th>সদস্য</th><th>মাস</th><th>জমা</th></tr>'+''.join(f'<tr><td>{x["date"]}</td><td>{x["name"]}</td><td>{x["month"]}</td><td>৳{x["amount"]}</td></tr>' for x in ds)+'</table></div><div class="panel"><h3>Withdrawals</h3><table class="table"><tr><th>তারিখ</th><th>সদস্য</th><th>উত্তোলন</th></tr>'+''.join(f'<tr><td>{x["date"]}</td><td>{x["name"]}</td><td>৳{x["amount"]}</td></tr>' for x in ws)+'</table></div>';return layout(b,'Transactions')
@app.route('/reports')
def reports():
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 c=db();m=c.execute("select count(*)n from users where role='member'").fetchone()['n'];d=c.execute('select coalesce(sum(amount),0)n from deposits').fetchone()['n'];w=c.execute('select coalesce(sum(amount),0)n from withdrawals').fetchone()['n'];c.close();return layout(f'<div class="cards"><div class="card"><div class="muted">মোট সদস্য</div><div class="big">{m}</div></div><div class="card"><div class="muted">মোট জমা</div><div class="big">৳{d:,.2f}</div></div><div class="card"><div class="muted">মোট উত্তোলন</div><div class="big">৳{w:,.2f}</div></div><div class="card"><div class="muted">বর্তমান তহবিল</div><div class="big">৳{d-w:,.2f}</div></div></div>','Reports')
@app.route('/logs')
def logs():
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 c=db();r=c.execute('select * from logs order by id desc limit 200').fetchall();c.close();return layout('<div class="panel"><table class="table"><tr><th>সময়</th><th>Action</th><th>Target</th></tr>'+''.join(f'<tr><td>{x["at"]}</td><td>{x["action"]}</td><td>{x["target"]}</td></tr>' for x in r)+'</table></div>','Audit Log')
@app.route('/settings',methods=['GET','POST'])
def settings_page():
 g=guard();
 if g:return g
 if not req_admin():return 'Forbidden',403
 if request.method=='POST':c=db();c.execute('update settings set name=?,monthly=? where id=1',(request.form['name'],float(request.form['monthly'])));c.commit();c.close();return redirect('/settings')
 s=settings();return layout(f'<form class="panel" method="post"><div class="grid"><div class="field"><label>সমিতির নাম</label><input name="name" value="{s["name"]}"></div><div class="field"><label>মাসিক জমা</label><input name="monthly" type="number" value="{s["monthly"]}"></div></div><button class="btn primary">SAVE</button></form>','Settings')
@app.route('/me')
def my_account():
 g=guard();
 if g:return g
 u=me();c=db();d=c.execute('select * from deposits where member_id=? order by id desc',(u['id'],)).fetchall();w=c.execute('select * from withdrawals where member_id=? order by id desc',(u['id'],)).fetchall();c.close();return layout(f'''<div class="panel">{('<img class=avatar src="/uploads/'+u['photo']+'">') if u['photo'] else ''}<p><b>নাম:</b> {u['name']}</p><p><b>Member ID:</b> {u['member_id']}</p><p><b>NID:</b> {u['nid'] or '—'}</p><p><b>মোবাইল:</b> {u['phone'] or '—'}</p></div><div class="panel"><h3>আমার জমা</h3><table class="table"><tr><th>মাস</th><th>পরিমাণ</th><th>তারিখ</th></tr>'''+''.join(f'<tr><td>{x["month"]}</td><td>৳{x["amount"]}</td><td>{x["date"]}</td></tr>' for x in d)+'''</table></div>''','My Account')
@app.route('/uploads/<name>')
def uploads(name):return send_from_directory(UP,secure_filename(name))
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
