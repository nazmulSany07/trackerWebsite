import os, io, hashlib, sqlite3, json, urllib.request, urllib.parse
from datetime import date, datetime, timedelta
from functools import wraps
import pandas as pd
from flask import Flask, request, redirect, session, render_template, flash, send_file, url_for
from jinja2 import DictLoader
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")
DB = os.environ.get("DB_PATH", "tracker.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw TEXT, role TEXT DEFAULT 'admin');
CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY, symbol TEXT, analysis_date TEXT, trading_date TEXT,
 buy_price REAL, req_volume REAL, target_price REAL, sell_volume REAL DEFAULT 0, qty REAL, stop_loss REAL,
 notes TEXT, status TEXT DEFAULT 'Pending', reason TEXT);
CREATE TABLE IF NOT EXISTS eod_uploads(id INTEGER PRIMARY KEY, eod_date TEXT, filename TEXT, hash TEXT UNIQUE,
 rows INTEGER, log TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS eod_data(eod_date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL,
 volume REAL, value REAL, trades REAL, UNIQUE(eod_date,symbol));
CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY, watch_id INTEGER, symbol TEXT, entry_date TEXT,
 entry_price REAL, entry_volume REAL, qty REAL, target REAL, stop REAL, sell_volume REAL, status TEXT DEFAULT 'Active');
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, pos_id INTEGER, symbol TEXT, buy_date TEXT, buy_price REAL,
 qty REAL, sell_date TEXT, sell_price REAL, sell_volume REAL, gross REAL, charges REAL, net REAL, ret REAL,
 days INTEGER, exit_type TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS signals(id INTEGER PRIMARY KEY, dt TEXT, symbol TEXT, kind TEXT, price REAL, volume REAL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts TEXT, msg TEXT);
"""

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

def q(sql, a=(), one=False):
    c = db(); cur = c.execute(sql, a); r = cur.fetchone() if one else cur.fetchall()
    c.commit(); c.close(); return r

def audit(msg): q("INSERT INTO audit(ts,msg) VALUES(?,?)", (datetime.now().isoformat(timespec="seconds"), msg))

def init():
    c = db(); c.executescript(SCHEMA); c.commit(); c.close()
    if not q("SELECT 1 FROM users", one=True):
        q("INSERT INTO users(username,pw) VALUES(?,?)", ("admin", generate_password_hash("admin123")))

def notify(text):  # optional Telegram: set TG_TOKEN and TG_CHAT env vars
    t, ch = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
    if t and ch:
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{t}/sendMessage",
                urllib.parse.urlencode({"chat_id": ch, "text": text}).encode(), timeout=8)
        except Exception: pass

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if "uid" not in session: return redirect(url_for("login"))
        return f(*a, **k)
    return w

# ---------- EOD parsing ----------
ALIASES = {"symbol": ["symbol", "trading code", "code", "scrip", "stock", "ticker", "company"],
 "open": ["open", "openp", "open price", "openprice"], "high": ["high", "high price", "highp"],
 "low": ["low", "low price", "lowp"], "close": ["close", "closing price", "closep", "ltp", "last price", "closeprice"],
 "volume": ["volume", "total volume", "vol", "totalvolume"], "value": ["value", "total value", "value(mn)", "totalvalue"],
 "trades": ["trade", "trades", "total trades", "no. of trades", "totaltrades"]}

def detect(cols):
    m = {}
    low = {str(c).strip().lower(): c for c in cols}
    for k, al in ALIASES.items():
        for a in al:
            if a in low: m[k] = low[a]; break
    return m

def read_file(f):
    name = f.filename.lower(); raw = f.read()
    if name.endswith((".xlsx", ".xls")): return pd.read_excel(io.BytesIO(raw)), raw
    sep = "\t" if name.endswith((".tsv", ".txt")) else ","
    return pd.read_csv(io.BytesIO(raw), sep=sep, thousands=","), raw

def process_eod(d):
    """Run buy/sell checks for EOD date d."""
    msgs = []
    px = lambda s: q("SELECT * FROM eod_data WHERE eod_date=? AND symbol=?", (d, s), one=True)
    # sells first (positions bought before d)
    for p in q("SELECT * FROM positions WHERE status='Active' AND entry_date<?", (d,)):
        r = px(p["symbol"])
        if not r: continue
        why = "Target Hit" if r["high"] >= p["target"] else ("Stop Loss" if p["stop"] and r["close"] <= p["stop"] else None)
        if why:
            close_position(p, p["qty"] or 0, r["close"], r["volume"], d, 0, "Automatic", why)
            q("INSERT INTO signals(dt,symbol,kind,price,volume) VALUES(?,?,?,?,?)", (d, p["symbol"], "SELL", r["close"], r["volume"]))
            notify(f"SELL {p['symbol']} @ {r['close']} on {d}"); msgs.append(f"SELL {p['symbol']}")
    # buys
    for w in q("SELECT * FROM watchlist WHERE status='Pending' AND trading_date=?", (d,)):
        r = px(w["symbol"])
        if not r:
            q("UPDATE watchlist SET status='Expired',reason='EOD data missing' WHERE id=?", (w["id"],)); continue
        fails = []
        if r["close"] < w["buy_price"]: fails.append(f"Price: Close {r['close']} < Buy {w['buy_price']}")
        if r["volume"] < w["req_volume"]: fails.append(f"Volume: {r['volume']:.0f} < Required {w['req_volume']:.0f}")
        if fails:
            q("UPDATE watchlist SET status='Expired',reason=? WHERE id=?", ("; ".join(fails), w["id"])); continue
        if q("SELECT 1 FROM positions WHERE symbol=? AND status='Active'", (w["symbol"],), one=True):
            q("UPDATE watchlist SET status='Expired',reason='Duplicate active position' WHERE id=?", (w["id"],)); continue
        q("INSERT INTO positions(watch_id,symbol,entry_date,entry_price,entry_volume,qty,target,stop,sell_volume) VALUES(?,?,?,?,?,?,?,?,?)",
          (w["id"], w["symbol"], d, r["close"], r["volume"], w["qty"], w["target_price"], w["stop_loss"], w["sell_volume"]))
        q("UPDATE watchlist SET status='Bought',reason='Buy condition met' WHERE id=?", (w["id"],))
        q("INSERT INTO signals(dt,symbol,kind,price,volume) VALUES(?,?,?,?,?)", (d, w["symbol"], "BUY", r["close"], r["volume"]))
        notify(f"BUY {w['symbol']} @ {r['close']} vol {r['volume']:.0f} on {d}"); msgs.append(f"BUY {w['symbol']}")
    return msgs

def close_position(p, qty, price, vol, d, charges, etype, reason):
    gross = (price - p["entry_price"]) * qty
    days = (datetime.fromisoformat(d) - datetime.fromisoformat(p["entry_date"])).days
    q("INSERT INTO trades(pos_id,symbol,buy_date,buy_price,qty,sell_date,sell_price,sell_volume,gross,charges,net,ret,days,exit_type,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
      (p["id"], p["symbol"], p["entry_date"], p["entry_price"], qty, d, price, vol, gross, charges, gross - charges,
       (price / p["entry_price"] - 1) * 100, days, etype, reason))
    left = (p["qty"] or 0) - qty
    if left > 0: q("UPDATE positions SET qty=? WHERE id=?", (left, p["id"]))
    else: q("UPDATE positions SET status='Closed' WHERE id=?", (p["id"],))
    audit(f"{etype} sell {p['symbol']} qty={qty} @ {price}")

# ---------- routes ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = q("SELECT * FROM users WHERE username=?", (request.form["username"],), one=True)
        if u and check_password_hash(u["pw"], request.form["password"]):
            session["uid"] = u["id"]; return redirect("/")
        flash("ভুল ইউজারনেম বা পাসওয়ার্ড", "err")
    return render_template("login.html")

@app.route("/logout")
def logout(): session.clear(); return redirect("/login")

@app.route("/")
@login_required
def dashboard():
    t = [dict(x) for x in q("SELECT * FROM trades ORDER BY sell_date")]
    pos = [dict(x) for x in q("SELECT * FROM positions WHERE status='Active'")]
    for p in pos:
        r = q("SELECT close FROM eod_data WHERE symbol=? ORDER BY eod_date DESC LIMIT 1", (p["symbol"],), one=True)
        p["last"] = r["close"] if r else p["entry_price"]
        p["inv"] = p["entry_price"] * (p["qty"] or 0); p["val"] = p["last"] * (p["qty"] or 0)
        p["pl"] = p["val"] - p["inv"]; p["ret"] = (p["last"] / p["entry_price"] - 1) * 100
        p["days"] = (date.today() - date.fromisoformat(p["entry_date"])).days
    wins = [x for x in t if x["net"] > 0]; loss = [x for x in t if x["net"] <= 0]
    realized = sum(x["net"] for x in t); unreal = sum(p["pl"] for p in pos)
    by = {}
    for x in t: by[x["symbol"]] = by.get(x["symbol"], 0) + x["net"]
    mon = {}
    for x in t:
        m = x["sell_date"][:7]; a = mon.setdefault(m, [0, 0, 0]); a[0] += x["net"]; a[1] += 1; a[2] += x["net"] > 0
    cum, run = [], 0
    for x in t: run += x["net"]; cum.append(round(run, 2))
    S = dict(active=len(pos), closed=len(t), inv=sum(p["inv"] for p in pos), val=sum(p["val"] for p in pos),
        realized=realized, unreal=unreal, net=realized + unreal, wins=len(wins), loss=len(loss),
        wr=(len(wins) / len(t) * 100) if t else 0, avgw=sum(x["net"] for x in wins) / len(wins) if wins else 0,
        avgl=sum(x["net"] for x in loss) / len(loss) if loss else 0,
        best=max(by, key=by.get) if by else "-", worst=min(by, key=by.get) if by else "-",
        hold=sum(x["days"] for x in t) / len(t) if t else 0)
    today = q("SELECT MAX(eod_date) d FROM eod_data", one=True)["d"]
    sig = q("SELECT * FROM signals WHERE dt=?", (today,)) if today else []
    last = q("SELECT * FROM eod_uploads ORDER BY id DESC LIMIT 1", one=True)
    charts = dict(months=sorted(mon), pl=[round(mon[m][0], 2) for m in sorted(mon)],
        wr=[round(mon[m][2] / mon[m][1] * 100) for m in sorted(mon)], cum=cum, w=len(wins), l=len(loss))
    return render_template("dash.html", S=S, pos=pos, recent=t[-8:][::-1], sig=sig, today=today, last=last, ch=json.dumps(charts))

FIELDS = ["symbol", "analysis_date", "trading_date", "buy_price", "req_volume", "target_price", "qty", "stop_loss", "notes"]

@app.route("/watchlist", methods=["GET", "POST"])
@login_required
def watchlist():
    if request.method == "POST":
        f = request.form; sym = f["symbol"].strip().upper(); vals = []
        for k in FIELDS:
            v = f.get(k, "").strip()
            vals.append(sym if k == "symbol" else (v or None))
        if f.get("id"):
            q(f"UPDATE watchlist SET {','.join(k+'=?' for k in FIELDS)} WHERE id=?", (*vals, f["id"]))
        else:
            q(f"INSERT INTO watchlist({','.join(FIELDS)}) VALUES({','.join('?'*len(FIELDS))})", vals)
        audit(f"watchlist save {sym}"); return redirect("/watchlist")
    edit = q("SELECT * FROM watchlist WHERE id=?", (request.args["edit"],), one=True) if request.args.get("edit") else None
    rows = q("SELECT * FROM watchlist ORDER BY trading_date DESC, id DESC")
    return render_template("watchlist.html", rows=rows, e=edit, today=date.today().isoformat(), tomorrow=next_day())

@app.route("/watchlist/delete/<int:i>")
@login_required
def wdel(i): q("DELETE FROM watchlist WHERE id=?", (i,)); audit(f"watchlist delete {i}"); return redirect("/watchlist")

@app.route("/eod", methods=["GET", "POST"])
@login_required
def eod():
    if request.method == "POST":
        f = request.files["file"]; d = request.form["eod_date"]
        try: df, raw = read_file(f)
        except Exception as ex: flash(f"ফাইল পড়া যায়নি: {ex}", "err"); return redirect("/eod")
        h = hashlib.sha256(raw).hexdigest()
        if q("SELECT 1 FROM eod_uploads WHERE hash=?", (h,), one=True) or q("SELECT 1 FROM eod_uploads WHERE eod_date=?", (d,), one=True):
            flash("এই ফাইল/তারিখ আগেই ইমপোর্ট হয়েছে (Duplicate)", "err"); return redirect("/eod")
        m = detect(df.columns)
        for k in ALIASES:  # manual mapping overrides
            if request.form.get("map_" + k): m[k] = request.form["map_" + k]
        miss = [k for k in ("symbol", "open", "high", "low", "close", "volume") if k not in m]
        if miss: flash("Column শনাক্ত হয়নি: " + ", ".join(miss) + " — নিচে ম্যানুয়ালি ম্যাপ করুন", "err"); return render_template("eod.html", ups=[], cols=list(df.columns), maps=m, d=d, fields=ALIASES.keys())
        ok, bad = 0, []
        c = db()
        for i, r in df.iterrows():
            try:
                row = [str(r[m["symbol"]]).strip().upper()] + [float(str(r[m[k]]).replace(",", "")) for k in ("open", "high", "low", "close", "volume")]
                row += [float(str(r[m[k]]).replace(",", "")) if k in m and pd.notna(r[m[k]]) else None for k in ("value", "trades")]
                if row[0] in ("", "NAN") or row[4] <= 0: raise ValueError("invalid")
                c.execute("INSERT OR REPLACE INTO eod_data(eod_date,symbol,open,high,low,close,volume,value,trades) VALUES(?,?,?,?,?,?,?,?,?)", (d, row[0], *row[1:]))
                ok += 1
            except Exception: bad.append(i + 2)
        c.commit(); c.close()
        msgs = process_eod(d)
        log = f"OK rows={ok}; invalid rows={bad[:30]}; signals={msgs}"
        q("INSERT INTO eod_uploads(eod_date,filename,hash,rows,log,created) VALUES(?,?,?,?,?,?)", (d, f.filename, h, ok, log, datetime.now().isoformat(timespec="seconds")))
        flash(f"{ok} টি রো ইমপোর্ট, {len(bad)} টি ভুল। সিগন্যাল: {', '.join(msgs) or 'নেই'}", "ok"); return redirect("/eod")
    return render_template("eod.html", ups=q("SELECT * FROM eod_uploads ORDER BY id DESC"), cols=None, maps={}, d=date.today().isoformat(), fields=ALIASES.keys())

@app.route("/holdings")
@login_required
def holdings():
    rows = []
    for p in q("SELECT * FROM positions WHERE status='Active' ORDER BY entry_date DESC"):
        p = dict(p); r = q("SELECT close FROM eod_data WHERE symbol=? ORDER BY eod_date DESC LIMIT 1", (p["symbol"],), one=True)
        p["last"] = r["close"] if r else p["entry_price"]; n = p["qty"] or 0
        p["inv"] = p["entry_price"] * n; p["pl"] = (p["last"] - p["entry_price"]) * n
        p["ret"] = (p["last"] / p["entry_price"] - 1) * 100
        p["days"] = (date.today() - date.fromisoformat(p["entry_date"])).days; rows.append(p)
    return render_template("holdings.html", rows=rows, today=date.today().isoformat())

@app.route("/position/<int:i>", methods=["POST"])
@login_required
def position(i):
    p = q("SELECT * FROM positions WHERE id=? AND status='Active'", (i,), one=True)
    if not p: return redirect("/holdings")
    f = request.form
    if f["act"] == "edit":
        q("UPDATE positions SET qty=?,target=?,stop=? WHERE id=?", (f["qty"] or None, f["target"], f["stop"] or None, i)); audit(f"edit position {i}")
    else:
        qty = float(f["qty"] or p["qty"] or 0)
        if qty <= 0 or qty > (p["qty"] or qty): flash("Quantity ঠিক নয়", "err")
        else: close_position(p, qty, float(f["price"]), 0, f["date"], float(f["charges"] or 0), "Manual", "Manual Sell"); flash("Sell সম্পন্ন", "ok")
    return redirect("/holdings")

def next_day():
    d = date.today() + timedelta(days=1)
    while d.weekday() in (4, 5): d += timedelta(days=1)  # DSE: শুক্র-শনি বন্ধ
    return d.isoformat()

@app.context_processor
def inj():
    return dict(act=q("SELECT id,symbol,qty,entry_price FROM positions WHERE status='Active'") if "uid" in session else [])

@app.route("/manual_sell", methods=["POST"])
@login_required
def manual_sell(): return position(int(request.form["pos_id"]))

@app.route("/manual_buy", methods=["POST"])
@login_required
def manual_buy():
    f = request.form; s = f["symbol"].strip().upper()
    if q("SELECT 1 FROM positions WHERE symbol=? AND status='Active'", (s,), one=True): flash("এই স্টকের Active Position আগেই আছে", "err")
    else:
        q("INSERT INTO positions(symbol,entry_date,entry_price,entry_volume,qty,target,stop,sell_volume) VALUES(?,?,?,?,?,?,?,0)",
          (s, f["date"], float(f["price"]), 0, f["qty"] or None, float(f["target"]), f["stop"] or None)); audit(f"manual buy {s}"); flash("Position যোগ হয়েছে", "ok")
    return redirect("/holdings")

@app.route("/history")
@login_required
def history():
    sql, a = "SELECT * FROM trades WHERE 1=1", []
    for k, col in (("symbol", "symbol"), ("exit_type", "exit_type"), ("frm", "sell_date>="), ("to", "sell_date<=")):
        v = request.args.get(k, "").strip().upper() if k == "symbol" else request.args.get(k, "")
        if v: sql += f" AND {col}=?" if "<" not in col and ">" not in col else f" AND {col}?"; a.append(v)
    if request.args.get("res") == "win": sql += " AND net>0"
    if request.args.get("res") == "loss": sql += " AND net<=0"
    return render_template("history.html", rows=q(sql + " ORDER BY sell_date DESC", a))

@app.route("/archive")
@login_required
def archive():
    return render_template("archive.html", wl=q("SELECT * FROM watchlist ORDER BY trading_date DESC"), sg=q("SELECT * FROM signals ORDER BY dt DESC"),
        ups=q("SELECT * FROM eod_uploads ORDER BY eod_date DESC"), au=q("SELECT * FROM audit ORDER BY id DESC LIMIT 100"))

@app.route("/export/<kind>")
@login_required
def export(kind):
    tbl = {"watchlist": "watchlist", "holdings": "positions", "history": "trades"}[kind]
    df = pd.read_sql(f"SELECT * FROM {tbl}", db()); b = io.BytesIO(); df.to_excel(b, index=False); b.seek(0)
    return send_file(b, as_attachment=True, download_name=f"{kind}_{date.today()}.xlsx")

@app.route("/backup")
@login_required
def backup(): return send_file(DB, as_attachment=True, download_name=f"tracker_backup_{date.today()}.db")

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        u = q("SELECT * FROM users WHERE id=?", (session["uid"],), one=True)
        if not check_password_hash(u["pw"], request.form["old"]): flash("পুরোনো পাসওয়ার্ড ভুল", "err")
        elif len(request.form["new"]) < 6: flash("কমপক্ষে ৬ অক্ষর দিন", "err")
        else: q("UPDATE users SET pw=? WHERE id=?", (generate_password_hash(request.form["new"]), u["id"])); flash("পাসওয়ার্ড পরিবর্তিত হয়েছে", "ok")
    return render_template("settings.html")

@app.template_filter("n")
def n(v, d=2): return "-" if v is None else f"{v:,.{d}f}"

# ---------- templates ----------
CSS = """<style>:root{--bg:#0a1628;--card:#10223d;--line:#1e3a5f;--tx:#e6f0fa;--mut:#8aa4c4;--ac:#14b8a6;--g:#22c55e;--r:#ef4444}
body.light{--bg:#f1f5f9;--card:#fff;--line:#d5dde8;--tx:#0f1f35;--mut:#52657e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px system-ui,sans-serif;display:flex;min-height:100vh}
nav{width:200px;background:var(--card);border-right:1px solid var(--line);padding:18px 10px;position:sticky;top:0;height:100vh}
nav h2{color:var(--ac);font-size:17px;margin:0 8px 18px}nav a{display:block;padding:9px 12px;border-radius:8px;color:var(--mut);text-decoration:none;margin-bottom:3px}
nav a:hover,nav a.on{background:var(--line);color:var(--tx)}main{flex:1;padding:22px;min-width:0}h1{margin:0 0 16px;font-size:21px}h3{margin:0 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:16px;overflow-x:auto}.grid .card{margin:0}
.k{color:var(--mut);font-size:12px}.v{font-size:20px;font-weight:700;margin-top:4px}.g{color:var(--g)}.r{color:var(--r)}
table{width:100%;border-collapse:collapse}th,td{padding:8px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--mut);font-size:12px;cursor:pointer}
input,select,textarea{background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:7px;padding:8px;width:100%}
.f{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}label{font-size:12px;color:var(--mut)}
button,.b{background:var(--ac);color:#04201c;border:0;border-radius:7px;padding:8px 14px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
.b2{background:var(--line);color:var(--tx)}.bd{background:var(--r);color:#fff}.tag{padding:2px 8px;border-radius:99px;font-size:12px;background:var(--line)}
.msg{padding:10px 14px;border-radius:8px;margin-bottom:12px}.ok{background:#14532d}.err{background:#7f1d1d}.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:800px){nav{width:70px}nav a{font-size:0;padding:12px}nav a:first-letter{font-size:14px}.two{grid-template-columns:1fr}}</style>"""

BASE = """<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Sany Stock Tracker</title>""" + CSS + """
<script src=https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js></script></head><body>
<script>if(localStorage.th=='l')document.body.classList.add('light')</script>
<nav><h2>📈 Sany Tracker</h2>
{% for u,t in [('/','Dashboard'),('/watchlist','Watchlist'),('/eod','EOD Upload'),('/holdings','Active Holdings'),('/history','Trade History'),('/archive','Archive'),('/settings','Settings')] %}
<a href="{{u}}" class="{{'on' if request.path==u}}">{{t}}</a>{% endfor %}
<a href="#" onclick="document.body.classList.toggle('light');localStorage.th=document.body.classList.contains('light')?'l':'d';return false">🌓 Theme</a><a href="/logout">Logout</a></nav>
<main>{% with m=get_flashed_messages(with_categories=true) %}{% for c,t in m %}<div class="msg {{c}}">{{t}}</div>{% endfor %}{% endwith %}{% block c %}{% endblock %}</main>
<script>document.querySelectorAll('th').forEach(h=>h.onclick=()=>{const t=h.closest('table'),i=[...h.parentNode.children].indexOf(h),b=t.tBodies[0],d=h.d=-(h.d||-1);
[...b.rows].sort((a,c)=>{let x=a.cells[i].innerText.replace(/,/g,''),y=c.cells[i].innerText.replace(/,/g,'');return (isNaN(x)||isNaN(y)?x.localeCompare(y):x-y)*d}).forEach(r=>b.appendChild(r))})</script></body></html>"""

def pl(v): return '{% set x=' + v + ' %}<span class="{{\'g\' if x>0 else \'r\' if x<0}}">{{x|n}}</span>'

MS = """<div class=card><h3>Manual Sell</h3>{% if act %}<form method=post action="/manual_sell" class=f><input type=hidden name=act value=sell>
<div><label>Stock</label><select name=pos_id>{% for a in act %}<option value="{{a.id}}">{{a.symbol}} (Qty {{a.qty|n(0) if a.qty else '-'}}, Entry {{a.entry_price|n}})</option>{% endfor %}</select></div>
<div><label>Sell Qty (ফাঁকা = সব)</label><input name=qty type=number step=any></div><div><label>Sell Price</label><input name=price type=number step=any required></div>
<div><label>Date</label><input name=date type=date value="{{today}}" required></div><div><label>Charges</label><input name=charges type=number step=any></div>
<div style="align-self:end"><button class=bd>Sell</button></div></form>{% else %}<span class=k>এখন কোনো Active Position নেই (Buy Signal এলে বা Manual Buy দিলে এখানে আসবে)</span>{% endif %}</div>"""
MB = """<div class=card><h3>Manual Buy (নিজে Position যোগ করুন)</h3><form method=post action="/manual_buy" class=f>
<div><label>Symbol</label><input name=symbol required></div><div><label>Buy Date</label><input type=date name=date value="{{today}}" required></div>
<div><label>Buy Price</label><input name=price type=number step=any required></div><div><label>Quantity</label><input name=qty type=number step=any></div>
<div><label>Target</label><input name=target type=number step=any required></div><div><label>Stop Loss</label><input name=stop type=number step=any></div>
<div style="align-self:end"><button>Add Position</button></div></form></div>"""
T = {"base.html": BASE,
"login.html": """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1>""" + CSS + """<body style="justify-content:center;align-items:center"><form method=post class=card style="width:340px"><h1>📈 Sany Stock Tracker</h1>
{% with m=get_flashed_messages(with_categories=true) %}{% for c,t in m %}<div class="msg {{c}}">{{t}}</div>{% endfor %}{% endwith %}
<label>Username</label><input name=username autofocus><br><br><label>Password</label><input name=password type=password><br><br><button style="width:100%">Login</button></form>""",
"dash.html": """{% extends 'base.html' %}{% block c %}<h1>Dashboard</h1><div class=grid>
{% for k,v,c in [('Active Positions',S.active,0),('Closed Trades',S.closed,0),('Total Investment',S.inv|n,0),('Portfolio Value',S.val|n,0),('Realized P/L',S.realized|n,S.realized),('Unrealized P/L',S.unreal|n,S.unreal),('Overall Net P/L',S.net|n,S.net),
('Winning / Losing',S.wins~' / '~S.loss,0),('Win Rate',(S.wr|n(1))~'%',0),('Avg Profit',S.avgw|n,1 if S.avgw else 0),('Avg Loss',S.avgl|n,-1 if S.avgl else 0),('Best Stock',S.best,0),('Worst Stock',S.worst,0),('Avg Holding (days)',S.hold|n(1),0)] %}
<div class=card><div class=k>{{k}}</div><div class="v {{'g' if c>0 else 'r' if c<0}}">{{v}}</div></div>{% endfor %}</div>
<div class=two><div class=card><h3>Monthly Profit/Loss</h3><canvas id=c1></canvas></div><div class=card><h3>Cumulative P/L / Equity Curve</h3><canvas id=c2></canvas></div>
<div class=card><h3>Winning vs Losing</h3><canvas id=c3></canvas></div><div class=card><h3>Monthly Win Rate %</h3><canvas id=c4></canvas></div></div>
<div class=card><h3>Latest EOD: {{last.eod_date if last else 'No upload yet'}} {% if last %}<span class=tag>{{last.rows}} rows</span>{% endif %}</h3></div>
<div class=card><h3>Today's Signals ({{today or '-'}})</h3><table><thead><tr><th>Symbol<th>Type<th>Price<th>Volume</tr></thead><tbody>{% for s in sig %}<tr><td>{{s.symbol}}<td class="{{'g' if s.kind=='BUY' else 'r'}}">{{s.kind}}<td>{{s.price|n}}<td>{{s.volume|n(0)}}</tr>{% else %}<tr><td colspan=4>কোনো সিগন্যাল নেই</tr>{% endfor %}</tbody></table></div>
<div class=card><h3>Active Holdings</h3><table><thead><tr><th>Symbol<th>Entry<th>Last<th>Qty<th>P/L<th>Return%</tr></thead><tbody>{% for p in pos %}<tr><td>{{p.symbol}}<td>{{p.entry_price|n}}<td>{{p.last|n}}<td>{{p.qty|n(0)}}<td class="{{'g' if p.pl>0 else 'r'}}">{{p.pl|n}}<td class="{{'g' if p.ret>0 else 'r'}}">{{p.ret|n}}%</tr>{% endfor %}</tbody></table></div>
<div class=card><h3>Recently Closed</h3><table><thead><tr><th>Symbol<th>Sell Date<th>Net P/L<th>Return%</tr></thead><tbody>{% for t in recent %}<tr><td>{{t.symbol}}<td>{{t.sell_date}}<td class="{{'g' if t.net>0 else 'r'}}">{{t.net|n}}<td>{{t.ret|n}}%</tr>{% endfor %}</tbody></table></div>
<script>const D={{ch|safe}};const o={plugins:{legend:{display:false}}};
new Chart(c1,{type:'bar',data:{labels:D.months,datasets:[{data:D.pl,backgroundColor:D.pl.map(v=>v>=0?'#22c55e':'#ef4444')}]},options:o});
new Chart(c2,{type:'line',data:{labels:D.cum.map((_,i)=>i+1),datasets:[{data:D.cum,borderColor:'#14b8a6',fill:true,backgroundColor:'#14b8a622'}]},options:o});
new Chart(c3,{type:'doughnut',data:{labels:['Win','Loss'],datasets:[{data:[D.w,D.l],backgroundColor:['#22c55e','#ef4444']}]}});
new Chart(c4,{type:'line',data:{labels:D.months,datasets:[{data:D.wr,borderColor:'#38bdf8'}]},options:o});</script>{% endblock %}""",
"watchlist.html": """{% extends 'base.html' %}{% block c %}<h1>Daily Watchlist</h1><form method=post class=card>{% if e %}<input type=hidden name=id value="{{e.id}}">{% endif %}
<div class=f>{% for k,l,t in [('symbol','Stock Symbol','text'),('analysis_date','Analysis Date','date'),('trading_date','Trading Date','date'),('buy_price','Buy Price','number'),('req_volume','Required Buy Volume','number'),('target_price','Target Sell Price','number'),('qty','Quantity (optional)','number'),('stop_loss','Stop Loss','number')] %}
<div><label>{{l}}</label><input name={{k}} type={{t}} step=any value="{{(e[k] if e else (today if k=='analysis_date' else tomorrow if k=='trading_date' else '')) or ''}}" {{'required' if k in ['symbol','trading_date','buy_price','req_volume','target_price']}}></div>{% endfor %}
<div style="grid-column:1/-1"><label>Analysis Notes</label><textarea name=notes rows=2>{{(e.notes if e else '') or ''}}</textarea></div></div><br><button>{{'Update' if e else 'Add to Watchlist'}}</button> <a class="b b2" href="/export/watchlist">Excel Export</a></form>""" + MS + """
<div class=card><table><thead><tr><th>Trading Date<th>Symbol<th>Buy<th>Req Vol<th>Target<th>Qty<th>Stop<th>Status<th>Reason<th></tr></thead><tbody>{% for r in rows %}<tr><td>{{r.trading_date}}<td><b>{{r.symbol}}</b><td>{{r.buy_price|n}}<td>{{r.req_volume|n(0)}}<td>{{r.target_price|n}}<td>{{r.qty|n(0)}}<td>{{r.stop_loss|n}}<td><span class=tag>{{r.status}}</span><td>{{r.reason or ''}}<td>
{% if r.status=='Pending' %}<a class="b b2" href="?edit={{r.id}}">Edit</a> {% endif %}<a class="b bd" href="/watchlist/delete/{{r.id}}" onclick="return confirm('Delete?')">Del</a></tr>{% endfor %}</tbody></table></div>{% endblock %}""",
"eod.html": """{% extends 'base.html' %}{% block c %}<h1>EOD Data Upload</h1><form method=post enctype=multipart/form-data class=card><div class=f>
<div><label>EOD Date</label><input type=date name=eod_date value="{{d}}" required></div><div><label>File (CSV / XLSX / TSV)</label><input type=file name=file accept=".csv,.xlsx,.xls,.tsv,.txt" required></div>
{% if cols %}{% for f in fields %}<div><label>Map: {{f}}</label><select name="map_{{f}}"><option value="">auto</option>{% for c in cols %}<option {{'selected' if maps.get(f)==c}}>{{c}}</option>{% endfor %}</select></div>{% endfor %}{% endif %}</div><br><button>Upload & Process</button></form>
<div class=card><h3>Upload Log</h3><table><thead><tr><th>EOD Date<th>File<th>Rows<th>Log<th>Uploaded</tr></thead><tbody>{% for u in ups %}<tr><td>{{u.eod_date}}<td>{{u.filename}}<td>{{u.rows}}<td>{{u.log}}<td>{{u.created}}</tr>{% endfor %}</tbody></table></div>{% endblock %}""",
"holdings.html": """{% extends 'base.html' %}{% block c %}<h1>Active Holdings</h1><a class="b b2" href="/export/holdings">Excel Export</a><br><br>""" + MS + MB + """
{% for p in rows %}<div class=card><div style="display:flex;gap:18px;flex-wrap:wrap;align-items:center"><b style="font-size:17px">{{p.symbol}}</b><span class=k>#{{p.id}} · {{p.entry_date}} · {{p.days}} days</span>
<span>Entry {{p.entry_price|n}}</span><span>Last {{p.last|n}}</span><span>Qty {{p.qty|n(0) if p.qty else 'PENDING'}}</span><span>Invested {{p.inv|n}}</span><span>Target {{p.target|n}}</span>
<span class="{{'g' if p.pl>0 else 'r'}}">P/L {{p.pl|n}} ({{p.ret|n}}%)</span></div><br>
<form method=post action="/position/{{p.id}}" class=f><input type=hidden name=act value=sell><div><label>Sell Qty</label><input name=qty type=number step=any placeholder="{{p.qty|n(0) if p.qty else 'required'}}"></div>
<div><label>Sell Price</label><input name=price type=number step=any value="{{p.last}}" required></div><div><label>Date</label><input name=date type=date value="{{today}}" required></div><div><label>Charges</label><input name=charges type=number step=any></div><div style="align-self:end"><button class=bd>Manual Sell</button></div></form><br>
<form method=post action="/position/{{p.id}}" class=f><input type=hidden name=act value=edit><div><label>Qty</label><input name=qty type=number step=any value="{{p.qty or ''}}"></div><div><label>Target</label><input name=target type=number step=any value="{{p.target}}"></div>
<div><label>Stop</label><input name=stop type=number step=any value="{{p.stop or ''}}"></div><div style="align-self:end"><button class=b2>Save Edit</button></div></form></div>
{% else %}<div class=card>কোনো Active Position নেই</div>{% endfor %}{% endblock %}""",
"history.html": """{% extends 'base.html' %}{% block c %}<h1>Trade History</h1><form class="card f"><div><label>Symbol</label><input name=symbol value="{{request.args.symbol}}"></div><div><label>From</label><input type=date name=frm value="{{request.args.frm}}"></div><div><label>To</label><input type=date name=to value="{{request.args.to}}"></div>
<div><label>Exit</label><select name=exit_type><option value="">All<option>Automatic<option>Manual</select></div><div><label>Result</label><select name=res><option value="">All<option value=win>Winning<option value=loss>Losing</select></div><div style="align-self:end"><button>Filter</button> <a class="b b2" href="/export/history">Excel</a></div></form>
<div class=card><table><thead><tr><th>Symbol<th>Buy Date<th>Buy<th>Qty<th>Sell Date<th>Sell<th>Gross<th>Charges<th>Net<th>Return%<th>Days<th>Exit<th>Reason</tr></thead><tbody>{% for t in rows %}<tr><td><b>{{t.symbol}}</b><td>{{t.buy_date}}<td>{{t.buy_price|n}}<td>{{t.qty|n(0)}}<td>{{t.sell_date}}<td>{{t.sell_price|n}}<td>{{t.gross|n}}<td>{{t.charges|n}}<td class="{{'g' if t.net>0 else 'r'}}">{{t.net|n}}<td>{{t.ret|n}}%<td>{{t.days}}<td>{{t.exit_type}}<td>{{t.reason}}</tr>{% endfor %}</tbody></table></div>{% endblock %}""",
"archive.html": """{% extends 'base.html' %}{% block c %}<h1>Archive</h1>
<div class=card><h3>Watchlist Archive</h3><table><thead><tr><th>Trading Date<th>Symbol<th>Buy<th>Status<th>Reason</tr></thead><tbody>{% for r in wl %}<tr><td>{{r.trading_date}}<td>{{r.symbol}}<td>{{r.buy_price|n}}<td>{{r.status}}<td>{{r.reason or ''}}</tr>{% endfor %}</tbody></table></div>
<div class=card><h3>Signals</h3><table><thead><tr><th>Date<th>Symbol<th>Type<th>Price</tr></thead><tbody>{% for s in sg %}<tr><td>{{s.dt}}<td>{{s.symbol}}<td>{{s.kind}}<td>{{s.price|n}}</tr>{% endfor %}</tbody></table></div>
<div class=card><h3>EOD Uploads</h3><table><thead><tr><th>Date<th>File<th>Rows</tr></thead><tbody>{% for u in ups %}<tr><td>{{u.eod_date}}<td>{{u.filename}}<td>{{u.rows}}</tr>{% endfor %}</tbody></table></div>
<div class=card><h3>Audit Log</h3><table><tbody>{% for a in au %}<tr><td>{{a.ts}}<td>{{a.msg}}</tr>{% endfor %}</tbody></table></div>{% endblock %}""",
"settings.html": """{% extends 'base.html' %}{% block c %}<h1>Settings</h1><form method=post class=card style="max-width:380px"><h3>Password পরিবর্তন</h3><label>পুরোনো</label><input type=password name=old required><br><br><label>নতুন</label><input type=password name=new required><br><br><button>Change</button></form>
<div class=card><h3>Backup</h3><a class=b href="/backup">Database Backup Download</a></div>{% endblock %}"""}
app.jinja_loader = DictLoader(T)

if __name__ == "__main__":
    init(); print("http://127.0.0.1:5000  | login: admin / admin123"); app.run(debug=False)
