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
CREATE TABLE IF NOT EXISTS cashflows(id INTEGER PRIMARY KEY, dt TEXT, kind TEXT, amount REAL, note TEXT, created TEXT);
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
        q("INSERT INTO users(username,pw) VALUES(?,?)", ("admin", generate_password_hash("admin123", method="pbkdf2:sha256")))

def cash_summary(invested=None, realized=None, portfolio_val=None):
    """Capital ledger: deposits fund buys; sells return cash via realized P/L."""
    deposited = q("SELECT COALESCE(SUM(amount),0) s FROM cashflows WHERE kind='deposit'", one=True)["s"]
    withdrawn = q("SELECT COALESCE(SUM(amount),0) s FROM cashflows WHERE kind='withdraw'", one=True)["s"]
    if invested is None:
        invested = q("SELECT COALESCE(SUM(entry_price * qty),0) s FROM positions WHERE status='Active' AND qty IS NOT NULL", one=True)["s"]
    if realized is None:
        realized = q("SELECT COALESCE(SUM(net),0) s FROM trades", one=True)["s"]
    if portfolio_val is None:
        portfolio_val = invested  # caller should pass marked-to-market when available
    net_in = deposited - withdrawn
    available = net_in - invested + realized  # cash left after funding open positions
    equity = available + portfolio_val        # cash + market value of holdings
    return dict(deposited=deposited, withdrawn=withdrawn, net_in=net_in, invested=invested,
                available=available, equity=equity, realized=realized)

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
        cost = (w["qty"] or 0) * r["close"]
        if w["qty"] and cost > cash_summary()["available"] + 1e-9:
            q("UPDATE watchlist SET status='Expired',reason=? WHERE id=?",
              (f"Insufficient cash (need {cost:.2f})", w["id"])); continue
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
    inv = sum(p["inv"] for p in pos); val = sum(p["val"] for p in pos)
    cash = cash_summary(invested=inv, realized=realized, portfolio_val=val)
    S = dict(active=len(pos), closed=len(t), inv=inv, val=val,
        realized=realized, unreal=unreal, net=realized + unreal, wins=len(wins), loss=len(loss),
        wr=(len(wins) / len(t) * 100) if t else 0, avgw=sum(x["net"] for x in wins) / len(wins) if wins else 0,
        avgl=sum(x["net"] for x in loss) / len(loss) if loss else 0,
        best=max(by, key=by.get) if by else "-", worst=min(by, key=by.get) if by else "-",
        hold=sum(x["days"] for x in t) / len(t) if t else 0,
        deposited=cash["deposited"], withdrawn=cash["withdrawn"], available=cash["available"], equity=cash["equity"])
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
    inv = sum(p["inv"] for p in rows); val = sum(p["last"] * (p["qty"] or 0) for p in rows)
    cash = cash_summary(invested=inv, portfolio_val=val)
    return render_template("holdings.html", rows=rows, today=date.today().isoformat(), cash=cash)

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
        qty = float(f["qty"]) if f.get("qty") else None
        price = float(f["price"]); cost = (qty or 0) * price
        cash = cash_summary()
        if qty and cost > cash["available"] + 1e-9:
            flash(f"পর্যাপ্ত ক্যাশ নেই — Available {cash['available']:,.2f}, প্রয়োজন {cost:,.2f}. আগে Deposit করুন।", "err")
            return redirect("/holdings")
        q("INSERT INTO positions(symbol,entry_date,entry_price,entry_volume,qty,target,stop,sell_volume) VALUES(?,?,?,?,?,?,?,0)",
          (s, f["date"], price, 0, qty, float(f["target"]), f["stop"] or None)); audit(f"manual buy {s}"); flash("Position যোগ হয়েছে", "ok")
    return redirect("/holdings")

@app.route("/capital", methods=["GET", "POST"])
@login_required
def capital():
    if request.method == "POST":
        f = request.form; kind = f.get("kind", "deposit")
        if kind not in ("deposit", "withdraw"): flash("Invalid type", "err"); return redirect("/capital")
        try: amount = float(f["amount"])
        except (KeyError, ValueError): flash("Amount দিন", "err"); return redirect("/capital")
        if amount <= 0: flash("Amount ০ এর বেশি হতে হবে", "err"); return redirect("/capital")
        if kind == "withdraw" and amount > cash_summary()["available"] + 1e-9:
            flash("Withdraw করতে পর্যাপ্ত Available Cash নেই", "err"); return redirect("/capital")
        q("INSERT INTO cashflows(dt,kind,amount,note,created) VALUES(?,?,?,?,?)",
          (f.get("date") or date.today().isoformat(), kind, amount, (f.get("note") or "").strip() or None,
           datetime.now().isoformat(timespec="seconds")))
        audit(f"{kind} {amount}"); flash(("Deposit" if kind == "deposit" else "Withdraw") + " সংরক্ষিত", "ok")
        return redirect(request.form.get("next") or "/capital")
    cash = cash_summary()
    rows = q("SELECT * FROM cashflows ORDER BY dt DESC, id DESC")
    return render_template("capital.html", cash=cash, rows=rows, today=date.today().isoformat())

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
        else: q("UPDATE users SET pw=? WHERE id=?", (generate_password_hash(request.form["new"], method="pbkdf2:sha256"), u["id"])); flash("পাসওয়ার্ড পরিবর্তিত হয়েছে", "ok")
    return render_template("settings.html")

@app.template_filter("n")
def n(v, d=2): return "-" if v is None else f"{v:,.{d}f}"

# ---------- templates ----------
CSS = """<style>
:root,:root.dark{
--bg:#020617;--bg2:#0B1224;--card:#0E1223;--muted:#1A1E2F;--line:#334155;--tx:#F8FAFC;--mut:#94A3B8;
--ac:#14B8A6;--ac2:#2DD4BF;--cta:#22C55E;--ink-btn:#0F172A;--g:#22C55E;--r:#EF4444;
--soft:rgba(20,184,166,.12);--ring:#FFFFFF;--shadow:0 4px 6px rgba(0,0,0,.25);
--space-xs:2px;--space-sm:4px;--space-md:8px;--space-lg:12px;--space-xl:16px;--space-2xl:24px}
:root.light,body.light{
--bg:#F1F5F9;--bg2:#F8FAFC;--card:#FFFFFF;--muted:#E2E8F0;--line:#CBD5E1;--tx:#0F172A;--mut:#64748B;
--ac:#0F766E;--ac2:#14B8A6;--cta:#16A34A;--ink-btn:#042F2A;--g:#15803D;--r:#DC2626;
--soft:rgba(15,118,110,.08);--ring:#0F172A;--shadow:0 4px 6px rgba(15,23,42,.08)}
*{box-sizing:border-box}
html{color-scheme:dark}html.light{color-scheme:light}
body{margin:0;min-height:100vh;display:flex;color:var(--tx);font:15px/1.5 "Fira Sans",sans-serif;
background:radial-gradient(ellipse 60% 40% at 0% 0%,rgba(20,184,166,.12),transparent 55%),
radial-gradient(ellipse 45% 35% at 100% 100%,rgba(34,197,94,.08),transparent 50%),var(--bg)}
a,button,.b,th,select,label[for]{cursor:pointer}
:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
nav{width:232px;flex-shrink:0;padding:var(--space-xl) var(--space-lg);position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:var(--space-sm);
background:linear-gradient(180deg,#0B1224 0%,#020617 100%);border-right:1px solid var(--line)}
body.light nav{background:linear-gradient(180deg,#FFFFFF,#F8FAFC);box-shadow:var(--shadow)}
nav .brand{padding:var(--space-sm) var(--space-md) var(--space-xl);border-bottom:1px solid var(--line);margin-bottom:var(--space-lg)}
nav .brand .mark{display:block;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--ac2);margin-bottom:var(--space-sm);font-weight:600}
nav .brand h2{font-family:"Fira Code",monospace;font-size:1.35rem;margin:0;letter-spacing:-.03em;color:var(--tx);font-weight:700}
nav a{display:flex;align-items:center;min-height:44px;padding:0 var(--space-lg);border-radius:8px;color:var(--mut);text-decoration:none;font-weight:500;font-size:14px;transition:background .2s,color .2s}
nav a:hover{background:var(--soft);color:var(--tx)}
nav a.on{background:var(--muted);color:var(--tx);box-shadow:inset 3px 0 0 var(--ac)}
nav .nav-foot{margin-top:auto;padding-top:var(--space-xl);border-top:1px solid var(--line);display:flex;flex-direction:column;gap:var(--space-lg)}
nav .theme-wrap label{display:block;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);margin:0 0 var(--space-sm) var(--space-sm);font-weight:600}
nav .theme-wrap select{width:100%;min-height:44px;background:var(--card);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:0 var(--space-lg);font:500 14px "Fira Sans",sans-serif}
nav a.logout{color:#FCA5A5}nav a.logout:hover{background:rgba(239,68,68,.12);color:#FECACA}
main{flex:1;padding:var(--space-2xl) clamp(16px,3vw,32px);min-width:0}
h1{font-family:"Fira Code",monospace;margin:0 0 var(--space-xl);font-size:clamp(1.4rem,2.2vw,1.75rem);letter-spacing:-.03em;font-weight:600}
h3{font-family:"Fira Sans",sans-serif;margin:0 0 var(--space-lg);font-size:1rem;font-weight:600;letter-spacing:-.01em}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--space-lg);margin-bottom:var(--space-xl)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:var(--space-xl);margin-bottom:var(--space-xl);overflow-x:auto;box-shadow:var(--shadow)}
.grid .card{margin:0}
@media(prefers-reduced-motion:no-preference){
.grid .card{animation:rise .4s cubic-bezier(.22,1,.36,1) both}
.grid .card:nth-child(1){animation-delay:.02s}.grid .card:nth-child(2){animation-delay:.06s}.grid .card:nth-child(3){animation-delay:.1s}
.grid .card:nth-child(4){animation-delay:.14s}.grid .card:nth-child(5){animation-delay:.18s}.grid .card:nth-child(6){animation-delay:.22s}
.grid .card:nth-child(n+7){animation-delay:.26s}}
.grid .card:hover{border-color:var(--ac)}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.k{color:var(--mut);font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase}
.v{font-size:1.25rem;font-weight:600;margin-top:var(--space-md);font-family:"Fira Code",monospace;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.g{color:var(--g)}.r{color:var(--r)}
table{width:100%;border-collapse:collapse}th,td{padding:var(--space-lg) var(--space-md);text-align:left;border-bottom:1px solid var(--line);white-space:nowrap;font-variant-numeric:tabular-nums}
th{color:var(--mut);font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase}
td{font-family:"Fira Code",monospace;font-size:13px}td:first-child,th:first-child{font-family:"Fira Sans",sans-serif}
tbody tr{transition:background .15s}tbody tr:hover{background:var(--soft)}
input,select,textarea{background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:11px 12px;min-height:44px;width:100%;font:500 14px "Fira Sans",sans-serif;outline:none;transition:border-color .2s,box-shadow .2s}
input:focus-visible,select:focus-visible,textarea:focus-visible{border-color:var(--ac);box-shadow:0 0 0 3px rgba(20,184,166,.25)}
.f{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:var(--space-lg)}
label{font-size:11px;color:var(--mut);font-weight:600;letter-spacing:.04em;text-transform:uppercase;display:block;margin-bottom:var(--space-sm)}
button,.b{background:var(--cta);color:var(--ink-btn);border:0;border-radius:8px;padding:11px 16px;min-height:44px;font:600 14px "Fira Sans",sans-serif;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;transition:opacity .2s,transform .15s}
button:hover,.b:hover{opacity:.92;transform:translateY(-1px)}button:active,.b:active{transform:none}
.b2{background:transparent;color:var(--tx);border:1px solid var(--line)}.bd{background:var(--r);color:#fff}
.tag{padding:4px 8px;border-radius:6px;font-size:11px;background:var(--muted);color:var(--tx);font-weight:600;border:1px solid var(--line);display:inline-block}
.msg{padding:var(--space-lg) var(--space-xl);border-radius:8px;margin-bottom:var(--space-xl);font-size:14px;border:1px solid var(--line)}
.ok{background:rgba(34,197,94,.12);color:var(--g)}.err{background:rgba(239,68,68,.12);color:var(--r)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-xl)}
.page-head{display:flex;align-items:flex-end;justify-content:space-between;gap:var(--space-xl);margin-bottom:var(--space-xl);flex-wrap:wrap}
.page-head p{margin:0;color:var(--mut);font-size:14px;max-width:42rem}
@media(max-width:860px){nav{width:78px;padding:var(--space-lg) var(--space-sm)}nav .brand .mark,nav .theme-wrap label,nav a.logout span{display:none}
nav .brand h2{font-size:.95rem;text-align:center}nav a{font-size:0;justify-content:center;padding:0}
nav a:before{font-size:12px;content:attr(data-i);font-weight:700;font-family:"Fira Code",monospace}
nav .theme-wrap select{font-size:12px;padding:0 4px}.two{grid-template-columns:1fr}main{padding:var(--space-xl)}}
</style>"""

BASE = """<!doctype html><html class=dark lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Sany Stock Tracker</title>
<link rel=preconnect href=https://fonts.googleapis.com>
<link rel=preconnect href=https://fonts.gstatic.com crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@400;500;600;700&display=swap" rel=stylesheet>
""" + CSS + """
<script src=https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js></script>
<script>(function(){var t=localStorage.theme||(localStorage.th==='l'?'light':'dark');
document.documentElement.className=t;if(t==='light')document.documentElement.classList.add('light');})()</script>
</head><body>
<script>if(document.documentElement.classList.contains('light'))document.body.classList.add('light')</script>
<nav aria-label="Primary">
<div class=brand><span class=mark>Private desk</span><h2>Sany</h2></div>
{% for u,t,i in [('/','Dashboard','Da'),('/watchlist','Watchlist','Wa'),('/eod','EOD Upload','EO'),('/holdings','Active Holdings','Ho'),('/capital','Deposit / Capital','Ca'),('/history','Trade History','Hi'),('/archive','Archive','Ar'),('/settings','Settings','Se')] %}
<a href="{{u}}" data-i="{{i}}" class="{{'on' if request.path==u}}" {{'aria-current="page"' if request.path==u}}> {{t}}</a>{% endfor %}
<div class=nav-foot>
<div class=theme-wrap>
<label for=themeSel>Theme</label>
<select id=themeSel aria-label="Color theme">
<option value=dark>Dark</option>
<option value=light>Light</option>
</select>
</div>
<a class=logout href="/logout" data-i="Out"><span>Logout</span></a>
</div>
</nav>
<main id=content>{% with m=get_flashed_messages(with_categories=true) %}{% for c,t in m %}<div class="msg {{c}}" role=status>{{t}}</div>{% endfor %}{% endwith %}{% block c %}{% endblock %}</main>
<script>
(function(){
  const sel=document.getElementById('themeSel');
  const cur=localStorage.theme||(localStorage.th==='l'?'light':'dark');
  sel.value=cur;
  function apply(t){
    localStorage.theme=t; localStorage.th=t==='light'?'l':'d';
    document.documentElement.className=t+(t==='light'?' light':'');
    document.body.classList.toggle('light', t==='light');
  }
  sel.onchange=()=>apply(sel.value);
})();
document.querySelectorAll('th').forEach(h=>h.onclick=()=>{const t=h.closest('table'),i=[...h.parentNode.children].indexOf(h),b=t.tBodies[0],d=h.d=-(h.d||-1);
[...b.rows].sort((a,c)=>{let x=a.cells[i].innerText.replace(/,/g,''),y=c.cells[i].innerText.replace(/,/g,'');return (isNaN(x)||isNaN(y)?x.localeCompare(y):x-y)*d}).forEach(r=>b.appendChild(r))});
</script></body></html>"""

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
"login.html": """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Sany Stock Tracker — Sign in</title>
<link rel=preconnect href=https://fonts.googleapis.com>
<link rel=preconnect href=https://fonts.gstatic.com crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@400;500;600;700&display=swap" rel=stylesheet>
<style>
:root{--bg:#020617;--card:#0E1223;--panel:#F8FAFC;--ink:#0F172A;--mut:#64748B;--tx:#F8FAFC;--ac:#14B8A6;--cta:#22C55E;--line:#334155;--warn:#DC2626}
*{box-sizing:border-box}html,body{height:100%;margin:0}
body{font:15px/1.5 "Fira Sans",sans-serif;color:var(--ink);background:var(--bg);display:grid;grid-template-columns:1.12fr .88fr;min-height:100vh}
a,button{cursor:pointer}:focus-visible{outline:2px solid #fff;outline-offset:2px}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
.hero{position:relative;overflow:hidden;padding:clamp(28px,5vw,56px);display:flex;flex-direction:column;justify-content:flex-end;color:var(--tx);
background:radial-gradient(ellipse 70% 50% at 15% 10%,rgba(20,184,166,.28),transparent 55%),
radial-gradient(ellipse 55% 45% at 90% 85%,rgba(34,197,94,.18),transparent 50%),linear-gradient(160deg,#020617 0%,#0B1224 48%,#0E1223 100%)}
.hero::before{content:"";position:absolute;inset:0;opacity:.18;background-image:linear-gradient(rgba(248,250,252,.09) 1px,transparent 1px),linear-gradient(90deg,rgba(248,250,252,.09) 1px,transparent 1px);background-size:44px 44px;mask-image:linear-gradient(180deg,#000 25%,transparent 92%);pointer-events:none}
.chart{position:absolute;left:8%;right:8%;bottom:16%;height:42%;opacity:.5;pointer-events:none}
.chart path{fill:none;stroke:#2DD4BF;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:900;stroke-dashoffset:900;animation:draw 2.2s ease forwards .3s}
.chart .fill{fill:url(#g);stroke:none;opacity:0;animation:fade .7s ease forwards 1.5s}
.brand{position:relative;z-index:1;max-width:34rem;animation:rise .75s cubic-bezier(.22,1,.36,1) both}
.brand .mark{display:inline-block;font:600 12px/1 "Fira Sans",sans-serif;letter-spacing:.16em;text-transform:uppercase;color:#2DD4BF;margin-bottom:16px}
.brand h1{font-family:"Fira Code",monospace;font-weight:700;font-size:clamp(2.5rem,6vw,4.2rem);line-height:.95;margin:0 0 14px;letter-spacing:-.04em}
.brand p{margin:0;font-size:1.05rem;line-height:1.55;color:#94A3B8;max-width:28rem}
.panel{display:flex;align-items:center;justify-content:center;padding:clamp(24px,4vw,48px);background:linear-gradient(180deg,#FFFFFF,#F1F5F9)}
.auth{width:min(100%,380px);animation:rise .65s cubic-bezier(.22,1,.36,1) .1s both}
.auth h2{font-family:"Fira Code",monospace;font-size:1.7rem;margin:0 0 6px;letter-spacing:-.03em}
.auth .sub{color:var(--mut);font-size:.95rem;margin:0 0 26px}
.field{margin-bottom:14px}
.field label{display:block;font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--mut);margin-bottom:7px}
.field input{width:100%;min-height:44px;border:1px solid #CBD5E1;background:#fff;border-radius:8px;padding:12px 14px;font:500 15px/1.2 "Fira Sans",sans-serif;color:var(--ink);outline:none;transition:border-color .2s,box-shadow .2s}
.field input:focus-visible{border-color:var(--ac);box-shadow:0 0 0 3px rgba(20,184,166,.22)}
button{width:100%;min-height:48px;margin-top:8px;border:0;border-radius:8px;padding:14px 16px;font:600 15px/1 "Fira Sans",sans-serif;color:#0F172A;background:var(--cta);transition:opacity .2s,transform .15s}
button:hover{opacity:.92;transform:translateY(-1px)}
.msg{padding:11px 13px;border-radius:8px;margin-bottom:16px;font-size:.9rem}.err{background:#FEE2E2;color:var(--warn)}.ok{background:#DCFCE7;color:#166534}
.foot{margin-top:20px;font-size:.8rem;color:#94A3B8}
@keyframes rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@keyframes draw{to{stroke-dashoffset:0}}@keyframes fade{to{opacity:.32}}
@media(max-width:860px){body{grid-template-columns:1fr}.hero{min-height:36vh;padding-bottom:24px}.brand h1{font-size:clamp(2.1rem,10vw,3rem)}.chart{opacity:.28}}
</style></head><body>
<section class=hero aria-hidden=true>
<svg class=chart viewBox="0 0 800 280" preserveAspectRatio="none">
<defs><linearGradient id=g x1=0 y1=0 x2=0 y2=1><stop stop-color=#2DD4BF stop-opacity=.45/><stop offset=1 stop-color=#2DD4BF stop-opacity=0/></linearGradient></defs>
<path class=fill d="M0 210 C80 200 120 150 180 160 S280 220 340 170 S450 80 520 110 S640 180 720 90 L800 70 V280 H0 Z"/>
<path d="M0 210 C80 200 120 150 180 160 S280 220 340 170 S450 80 520 110 S640 180 720 90 L800 70"/>
</svg>
<div class=brand>
<span class=mark>Private trading desk</span>
<h1>Sany</h1>
<p>Track watchlists, EOD signals, capital, and holdings in one focused workspace.</p>
</div>
</section>
<section class=panel>
<form class=auth method=post>
<h2>Welcome back</h2>
<p class=sub>Sign in to continue to your tracker.</p>
{% with m=get_flashed_messages(with_categories=true) %}{% for c,t in m %}<div class="msg {{c}}" role=alert>{{t}}</div>{% endfor %}{% endwith %}
<div class=field><label for=username>Username</label><input id=username name=username autocomplete=username autofocus required></div>
<div class=field><label for=password>Password</label><input id=password name=password type=password autocomplete=current-password required></div>
<button type=submit>Sign in</button>
<p class=foot>Authorized access only</p>
</form>
</section>
</body></html>""",
"dash.html": """{% extends 'base.html' %}{% block c %}
<div class=page-head><div><h1>Dashboard</h1><p>Capital, signals, holdings, and performance in one dense trading view.</p></div>
<span class=tag>EOD {{last.eod_date if last else '—'}}</span></div>
<div class=grid>
{% for k,v,c in [('Total Deposited',S.deposited|n,0),('Available Cash',S.available|n,1 if S.available>0 else -1 if S.available<0 else 0),('Total Equity',S.equity|n,0),('Withdrawn',S.withdrawn|n,0),
('Active Positions',S.active,0),('Closed Trades',S.closed,0),('Total Investment',S.inv|n,0),('Portfolio Value',S.val|n,0),('Realized P/L',S.realized|n,S.realized),('Unrealized P/L',S.unreal|n,S.unreal),('Overall Net P/L',S.net|n,S.net),
('Winning / Losing',S.wins~' / '~S.loss,0),('Win Rate',(S.wr|n(1))~'%',0),('Avg Profit',S.avgw|n,1 if S.avgw else 0),('Avg Loss',S.avgl|n,-1 if S.avgl else 0),('Best Stock',S.best,0),('Worst Stock',S.worst,0),('Avg Holding (days)',S.hold|n(1),0)] %}
<div class=card><div class=k>{{k}}</div><div class="v {{'g' if c>0 else 'r' if c<0}}">{{v}}</div></div>{% endfor %}</div>
<div class=card><h3>Today's Signals ({{today or '-'}})</h3><table><thead><tr><th>Symbol<th>Type<th>Price<th>Volume</tr></thead><tbody>{% for s in sig %}<tr><td>{{s.symbol}}<td class="{{'g' if s.kind=='BUY' else 'r'}}">{{s.kind}}<td>{{s.price|n}}<td>{{s.volume|n(0)}}</tr>{% else %}<tr><td colspan=4>কোনো সিগন্যাল নেই</tr>{% endfor %}</tbody></table></div>
<div class=card><h3>Active Holdings</h3><table><thead><tr><th>Symbol<th>Entry<th>Last<th>Qty<th>P/L<th>Return%</tr></thead><tbody>{% for p in pos %}<tr><td>{{p.symbol}}<td>{{p.entry_price|n}}<td>{{p.last|n}}<td>{{p.qty|n(0)}}<td class="{{'g' if p.pl>0 else 'r'}}">{{p.pl|n}}<td class="{{'g' if p.ret>0 else 'r'}}">{{p.ret|n}}%</tr>{% else %}<tr><td colspan=6>No active holdings</tr>{% endfor %}</tbody></table></div>
<div class=two><div class=card><h3>Monthly Profit/Loss</h3><canvas id=c1 aria-label="Monthly profit and loss chart"></canvas></div><div class=card><h3>Cumulative P/L / Equity Curve</h3><canvas id=c2 aria-label="Cumulative profit and loss chart"></canvas></div>
<div class=card><h3>Winning vs Losing</h3><canvas id=c3 aria-label="Win loss doughnut chart"></canvas></div><div class=card><h3>Monthly Win Rate %</h3><canvas id=c4 aria-label="Monthly win rate chart"></canvas></div></div>
<div class=card><h3>Latest EOD {% if last %}<span class=tag>{{last.rows}} rows</span>{% endif %}</h3><p class=k style="margin:0">{{last.eod_date if last else 'No upload yet'}}{% if last %} · {{last.filename}}{% endif %}</p></div>
<div class=card><h3>Recently Closed</h3><table><thead><tr><th>Symbol<th>Sell Date<th>Net P/L<th>Return%</tr></thead><tbody>{% for t in recent %}<tr><td>{{t.symbol}}<td>{{t.sell_date}}<td class="{{'g' if t.net>0 else 'r'}}">{{t.net|n}}<td>{{t.ret|n}}%</tr>{% else %}<tr><td colspan=4>No closed trades yet</tr>{% endfor %}</tbody></table></div>
<script>const D={{ch|safe}};const tick={color:'#94A3B8'};const o={plugins:{legend:{display:false}},scales:{x:{ticks:tick,grid:{color:'#33415555'}},y:{ticks:tick,grid:{color:'#33415555'}}}};
new Chart(c1,{type:'bar',data:{labels:D.months,datasets:[{data:D.pl,backgroundColor:D.pl.map(v=>v>=0?'#22C55E':'#EF4444'),borderRadius:4}]},options:o});
new Chart(c2,{type:'line',data:{labels:D.cum.map((_,i)=>i+1),datasets:[{data:D.cum,borderColor:'#14B8A6',tension:.3,fill:true,backgroundColor:'#14B8A622',pointRadius:2}]},options:o});
new Chart(c3,{type:'doughnut',data:{labels:['Win','Loss'],datasets:[{data:[D.w,D.l],backgroundColor:['#22C55E','#EF4444'],borderWidth:0}]},options:{plugins:{legend:{position:'bottom',labels:{color:'#94A3B8'}}}}});
new Chart(c4,{type:'line',data:{labels:D.months,datasets:[{data:D.wr,borderColor:'#38BDF8',tension:.3,pointRadius:2}]},options:o});</script>{% endblock %}""",
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
"holdings.html": """{% extends 'base.html' %}{% block c %}<h1>Active Holdings</h1>
<div class=grid>
<div class=card><div class=k>Total Deposited</div><div class=v>{{cash.deposited|n}}</div></div>
<div class=card><div class=k>Available Cash</div><div class="v {{'g' if cash.available>=0 else 'r'}}">{{cash.available|n}}</div></div>
<div class=card><div class=k>Invested</div><div class=v>{{cash.invested|n}}</div></div>
<div class=card><div class=k>Total Equity</div><div class=v>{{cash.equity|n}}</div></div>
</div>
<a class="b b2" href="/export/holdings">Excel Export</a> <a class=b href="/capital">Add Deposit</a><br><br>
""" + MS + MB + """
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
<div class=card><h3>Backup</h3><a class=b href="/backup">Database Backup Download</a></div>{% endblock %}""",
"capital.html": """{% extends 'base.html' %}{% block c %}<h1>Deposit / Capital</h1>
<div class=grid>
<div class=card><div class=k>Total Deposited</div><div class=v>{{cash.deposited|n}}</div></div>
<div class=card><div class=k>Withdrawn</div><div class=v>{{cash.withdrawn|n}}</div></div>
<div class=card><div class=k>Net Capital In</div><div class=v>{{cash.net_in|n}}</div></div>
<div class=card><div class=k>Invested (open)</div><div class=v>{{cash.invested|n}}</div></div>
<div class=card><div class=k>Available Cash</div><div class="v {{'g' if cash.available>=0 else 'r'}}">{{cash.available|n}}</div></div>
<div class=card><div class=k>Total Equity</div><div class=v>{{cash.equity|n}}</div></div>
</div>
<p class=k style="margin-top:-8px;margin-bottom:14px">Logic: Available Cash = Deposits − Withdrawals − Invested + Realized P/L · Equity = Available Cash + Portfolio Value</p>
<div class=two>
<div class=card><h3>Add Deposit</h3><form method=post class=f><input type=hidden name=kind value=deposit>
<div><label>Amount</label><input name=amount type=number step=any min=0.01 required></div>
<div><label>Date</label><input name=date type=date value="{{today}}" required></div>
<div style="grid-column:1/-1"><label>Note</label><input name=note placeholder="e.g. Bank transfer"></div>
<div style="align-self:end"><button>Deposit</button></div></form></div>
<div class=card><h3>Withdraw</h3><form method=post class=f><input type=hidden name=kind value=withdraw>
<div><label>Amount</label><input name=amount type=number step=any min=0.01 required></div>
<div><label>Date</label><input name=date type=date value="{{today}}" required></div>
<div style="grid-column:1/-1"><label>Note</label><input name=note></div>
<div style="align-self:end"><button class=bd>Withdraw</button></div></form></div>
</div>
<div class=card><h3>Cashflow History</h3><table><thead><tr><th>Date<th>Type<th>Amount<th>Note<th>Recorded</tr></thead>
<tbody>{% for r in rows %}<tr><td>{{r.dt}}<td class="{{'g' if r.kind=='deposit' else 'r'}}">{{r.kind|capitalize}}<td class="{{'g' if r.kind=='deposit' else 'r'}}">{{r.amount|n}}<td>{{r.note or '-'}}<td>{{r.created}}</tr>
{% else %}<tr><td colspan=5>এখনো কোনো Deposit/Withdraw নেই — প্রথমে Deposit যোগ করুন</tr>{% endfor %}</tbody></table></div>
{% endblock %}"""}
app.jinja_loader = DictLoader(T)

if __name__ == "__main__":
    init(); print("http://127.0.0.1:5000  | login: admin / admin123"); app.run(debug=False)
