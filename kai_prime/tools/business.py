"""Vision Works General Contracting — Business Management.
Enhanced: jobs, tax, payment tracking, CSV export, search/filter,
local rates, AI estimate generation, expense categories.
"""

import csv, io, json, sqlite3, re, threading
from pathlib import Path
from datetime import datetime, date

DB_DIR = Path(__file__).resolve().parent.parent / "kai_prime_data"
DB_PATH = DB_DIR / "business.db"
try:
    from kai_prime.config import WORKSPACE
except Exception:
    WORKSPACE = Path(__file__).resolve().parent.parent.parent
COMPANY = {
    "name": "Vision Works General Contracting",
    "owner": "Ryan",
    "phone": "",
    "email": "",
    "address": "Poplar Bluff, MO 63901",
}

EXPENSE_CATEGORIES = [
    "Materials", "Subcontractor", "Equipment Rental", "Permits & Fees",
    "Fuel", "Transportation", "Insurance", "Office & Admin",
    "Utilities", "Marketing", "Maintenance", "Other",
]

LOCAL_RATES_SEED = [
    ("General Labor", "General Labor", "hour", 25.00, "General construction labor"),
    ("Framing", "Framing Labor", "hour", 35.00, "Wall/roof framing labor"),
    ("Drywall", "Drywall Install", "sq ft", 2.50, "Drywall installation per sq ft"),
    ("Drywall", "Drywall Finish", "sq ft", 1.50, "Taping/mudding/sanding per sq ft"),
    ("Painting", "Interior Paint", "sq ft", 1.75, "Interior wall painting per sq ft"),
    ("Painting", "Exterior Paint", "sq ft", 2.25, "Exterior painting per sq ft"),
    ("Flooring", "LVP Flooring Install", "sq ft", 3.50, "Luxury vinyl plank installation per sq ft"),
    ("Flooring", "Tile Flooring Install", "sq ft", 5.00, "Ceramic/porcelain tile installation per sq ft"),
    ("Flooring", "Carpet Install", "sq ft", 2.00, "Carpet installation per sq ft"),
    ("Flooring", "Hardwood Install", "sq ft", 4.50, "Hardwood flooring install per sq ft"),
    ("Concrete", "Concrete Pour", "sq ft", 6.00, "Concrete slab pour per sq ft"),
    ("Concrete", "Concrete Finish", "sq ft", 2.00, "Concrete finishing per sq ft"),
    ("Roofing", "Roof Replacement", "sq ft", 4.50, "Asphalt shingle roof replacement"),
    ("Roofing", "Roof Repair", "hour", 50.00, "General roof repair labor"),
    ("Plumbing", "Plumbing Labor", "hour", 65.00, "General plumbing labor"),
    ("Electrical", "Electrical Labor", "hour", 60.00, "General electrical labor"),
    ("HVAC", "HVAC Labor", "hour", 70.00, "General HVAC labor"),
    ("Demolition", "Demolition Labor", "hour", 30.00, "General demolition labor"),
    ("Demolition", "Demo Disposal", "load", 150.00, "Debris removal per dump load"),
    ("Cabinetry", "Cabinet Install", "hour", 45.00, "Cabinet installation labor"),
    ("Cabinetry", "Countertop Install", "sq ft", 15.00, "Countertop installation per sq ft"),
    ("Excavation", "Excavation", "hour", 85.00, "Equipment + operator per hour"),
    ("Landscaping", "Landscaping Labor", "hour", 30.00, "General landscaping labor"),
    ("Fencing", "Fence Install", "linear ft", 18.00, "Wood fence installation per linear ft"),
    ("Fencing", "Chain Link Fence", "linear ft", 12.00, "Chain link fence per linear ft"),
    ("Decking", "Deck Build", "sq ft", 12.00, "Pressure-treated deck per sq ft"),
    ("Decking", "Composite Deck", "sq ft", 18.00, "Composite decking per sq ft"),
    ("Windows", "Window Install", "each", 250.00, "Standard window installation"),
    ("Doors", "Door Install", "each", 150.00, "Pre-hung door installation"),
    ("Doors", "Garage Door Install", "each", 500.00, "Garage door installation"),
    ("Misc", "Miscellaneous Labor", "hour", 35.00, "General miscellaneous labor"),
    ("Misc", "Trip / Mileage", "mile", 0.67, "Mileage reimbursement"),
    ("Misc", "Minimum Service Call", "each", 100.00, "Minimum trip/service call fee"),
]


class BusinessManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    address TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    start_date TEXT,
                    end_date TEXT,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (client_id) REFERENCES clients(id)
                );
                CREATE TABLE IF NOT EXISTS quotes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER DEFAULT NULL,
                    client_id INTEGER NOT NULL,
                    quote_number TEXT DEFAULT '',
                    date TEXT DEFAULT (datetime('now','localtime')),
                    items TEXT DEFAULT '[]',
                    subtotal REAL DEFAULT 0,
                    tax_rate REAL DEFAULT 0,
                    tax_amount REAL DEFAULT 0,
                    total REAL DEFAULT 0,
                    status TEXT DEFAULT 'draft',
                    notes TEXT DEFAULT '',
                    FOREIGN KEY (job_id) REFERENCES jobs(id),
                    FOREIGN KEY (client_id) REFERENCES clients(id)
                );
                CREATE TABLE IF NOT EXISTS invoices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER DEFAULT NULL,
                    quote_id INTEGER DEFAULT NULL,
                    client_id INTEGER NOT NULL,
                    invoice_number TEXT DEFAULT '',
                    date TEXT DEFAULT (datetime('now','localtime')),
                    items TEXT DEFAULT '[]',
                    subtotal REAL DEFAULT 0,
                    tax_rate REAL DEFAULT 0,
                    tax_amount REAL DEFAULT 0,
                    total REAL DEFAULT 0,
                    paid INTEGER DEFAULT 0,
                    partial_paid REAL DEFAULT 0,
                    payment_method TEXT DEFAULT '',
                    payment_date TEXT,
                    notes TEXT DEFAULT '',
                    FOREIGN KEY (job_id) REFERENCES jobs(id),
                    FOREIGN KEY (client_id) REFERENCES clients(id)
                );
                CREATE TABLE IF NOT EXISTS hours (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER DEFAULT NULL,
                    employee TEXT NOT NULL,
                    date TEXT NOT NULL,
                    hours REAL NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                );
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER DEFAULT NULL,
                    category TEXT NOT NULL,
                    date TEXT DEFAULT (datetime('now','localtime')),
                    amount REAL NOT NULL,
                    description TEXT DEFAULT '',
                    receipt TEXT DEFAULT '',
                    FOREIGN KEY (job_id) REFERENCES jobs(id)
                );
                CREATE TABLE IF NOT EXISTS company_info (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT DEFAULT 'Vision Works General Contracting',
                    owner TEXT DEFAULT 'Ryan',
                    phone TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    address TEXT DEFAULT 'Poplar Bluff, MO 63901',
                    facebook_url TEXT DEFAULT '',
                    homeadvisor_url TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS local_rates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    unit TEXT DEFAULT 'hour',
                    rate REAL NOT NULL,
                    description TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT DEFAULT '',
                    email TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    source TEXT DEFAULT '',
                    status TEXT DEFAULT 'new',
                    created_at TEXT DEFAULT (datetime('now','localtime'))
                );
            """)
            # Migrations
            for table, col, col_def in [
                ("quotes", "subtotal", "REAL DEFAULT 0"),
                ("quotes", "tax_rate", "REAL DEFAULT 0"),
                ("quotes", "tax_amount", "REAL DEFAULT 0"),
                ("quotes", "quote_number", "TEXT DEFAULT ''"),
                ("invoices", "subtotal", "REAL DEFAULT 0"),
                ("invoices", "tax_rate", "REAL DEFAULT 0"),
                ("invoices", "tax_amount", "REAL DEFAULT 0"),
                ("invoices", "partial_paid", "REAL DEFAULT 0"),
                ("invoices", "payment_method", "TEXT DEFAULT ''"),
                ("hours", "job_id", "INTEGER DEFAULT NULL"),
                ("hours", "rate", "REAL DEFAULT 0"),
                ("expenses", "job_id", "INTEGER DEFAULT NULL"),
                ("quotes", "job_id", "INTEGER DEFAULT NULL"),
                ("invoices", "job_id", "INTEGER DEFAULT NULL"),
                ("company_info", "facebook_url", "TEXT DEFAULT ''"),
                ("company_info", "homeadvisor_url", "TEXT DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")
                except Exception:
                    pass
            # Seed local_rates if empty
            cnt = conn.execute("SELECT COUNT(*) AS c FROM local_rates").fetchone()[0]
            if cnt == 0:
                for cat, item, unit, rate, desc in LOCAL_RATES_SEED:
                    conn.execute("INSERT INTO local_rates (category,item_name,unit,rate,description) VALUES (?,?,?,?,?)",
                                 (cat, item, unit, rate, desc))

    def _run(self, sql, params=()):
        with self._lock:
            with sqlite3.connect(str(DB_PATH)) as conn:
                conn.row_factory = sqlite3.Row
                c = conn.execute(sql, params)
                if sql.strip().upper().startswith("SELECT"):
                    rows = c.fetchall()
                    return [dict(r) for r in rows]
                conn.commit()
                return c.lastrowid

    def _calc_totals(self, items, tax_rate=0):
        subtotal = sum(i.get("total", 0) for i in items)
        tax_rate = float(tax_rate or 0)
        tax_amount = round(subtotal * tax_rate / 100, 2)
        total = round(subtotal + tax_amount, 2)
        return subtotal, tax_rate, tax_amount, total

    # ── Company Info ──
    def get_company(self):
        r = self._run("SELECT * FROM company_info LIMIT 1")
        if r:
            return r[0]
        return dict(COMPANY)

    def update_company(self, **kw):
        fields = ("name", "owner", "phone", "email", "address", "facebook_url", "homeadvisor_url")
        r = self._run("SELECT id FROM company_info LIMIT 1")
        vals = {k: kw.get(k, "") for k in fields}
        if r:
            set_clause = ",".join(f"{k}=?" for k in fields)
            self._run(f"UPDATE company_info SET {set_clause} WHERE id=?", tuple(vals[k] for k in fields) + (r[0]["id"],))
        else:
            placeholders = ",".join("?" for _ in fields)
            self._run(f"INSERT INTO company_info ({','.join(fields)}) VALUES ({placeholders})",
                     tuple(vals[k] for k in fields))

    # ── Clients ──
    def add_client(self, name, phone="", email="", address=""):
        return self._run("INSERT INTO clients (name,phone,email,address) VALUES (?,?,?,?)",
                        (name, phone, email, address))

    def get_clients(self, search=""):
        if search:
            return self._run("SELECT * FROM clients WHERE name LIKE ? ORDER BY name", (f"%{search}%",))
        return self._run("SELECT * FROM clients ORDER BY name")

    def get_client(self, cid):
        r = self._run("SELECT * FROM clients WHERE id=?", (cid,))
        return r[0] if r else None

    def delete_client(self, cid):
        self._run("DELETE FROM clients WHERE id=?", (cid,))

    def update_client(self, cid, name, phone="", email="", address=""):
        self._run("UPDATE clients SET name=?,phone=?,email=?,address=? WHERE id=?",
                  (name, phone, email, address, cid))

    # ── Jobs / Projects ──
    def add_job(self, client_id, name, description="", status="active", start_date=""):
        return self._run("INSERT INTO jobs (client_id,name,description,status,start_date) VALUES (?,?,?,?,?)",
                        (client_id, name, description, status, start_date or date.today().isoformat()))

    def get_jobs(self, search=""):
        if search:
            return self._run("""SELECT j.*, c.name AS client_name FROM jobs j
                              JOIN clients c ON j.client_id=c.id WHERE j.name LIKE ? ORDER BY j.created_at DESC""", (f"%{search}%",))
        return self._run("""SELECT j.*, c.name AS client_name FROM jobs j
                          JOIN clients c ON j.client_id=c.id ORDER BY j.created_at DESC""")

    def get_job(self, jid):
        r = self._run("""SELECT j.*, c.name AS client_name FROM jobs j
                       JOIN clients c ON j.client_id=c.id WHERE j.id=?""", (jid,))
        if r:
            job = r[0]
            job["quotes"] = self._run("SELECT id,quote_number,total,status,date FROM quotes WHERE job_id=?", (jid,))
            job["invoices"] = self._run("SELECT id,invoice_number,total,paid,date FROM invoices WHERE job_id=?", (jid,))
            job["hours"] = self._run("SELECT employee,SUM(hours) AS total FROM hours WHERE job_id=? GROUP BY employee", (jid,))
            job["expenses"] = self._run("SELECT category,SUM(amount) AS total FROM expenses WHERE job_id=? GROUP BY category", (jid,))
            return job
        return None

    def update_job_status(self, jid, status):
        self._run("UPDATE jobs SET status=? WHERE id=?", (status, jid))

    def delete_job(self, jid):
        self._run("DELETE FROM jobs WHERE id=?", (jid,))

    # ── Quotes ──
    def _next_quote_number(self):
        r = self._run("SELECT COUNT(*) AS cnt FROM quotes")
        return f"Q-{datetime.now().strftime('%Y%m')}-{(r[0]['cnt']+1):04d}"

    def create_quote(self, client_id, job_id=None, job_name="", items=None, notes="", tax_rate=0):
        items_list = items or []
        subtotal, tr, tax_amt, total = self._calc_totals(items_list, tax_rate)
        qnum = self._next_quote_number()
        return self._run("""INSERT INTO quotes (job_id,client_id,quote_number,items,subtotal,tax_rate,tax_amount,total,notes)
                          VALUES (?,?,?,?,?,?,?,?,?)""",
                        (job_id, client_id, qnum, json.dumps(items_list), subtotal, tr, tax_amt, total, notes))

    def get_quotes(self, search=""):
        if search:
            return self._run("""SELECT q.*, c.name AS client_name FROM quotes q
                             JOIN clients c ON q.client_id=c.id WHERE c.name LIKE ? OR q.quote_number LIKE ? ORDER BY q.date DESC""",
                           (f"%{search}%", f"%{search}%"))
        return self._run("""SELECT q.*, c.name AS client_name FROM quotes q
                          JOIN clients c ON q.client_id=c.id ORDER BY q.date DESC""")

    def get_quote(self, qid):
        r = self._run("""SELECT q.*, c.name AS client_name, c.phone AS client_phone, c.email AS client_email
                       FROM quotes q JOIN clients c ON q.client_id=c.id WHERE q.id=?""", (qid,))
        if r:
            r[0]["items"] = json.loads(r[0]["items"])
            return r[0]
        return None

    def update_client_contact(self, cid, phone, email):
        self._run("UPDATE clients SET phone=?, email=? WHERE id=?", (phone, email, cid))

    def update_quote_status(self, qid, status):
        self._run("UPDATE quotes SET status=? WHERE id=?", (status, qid))

    def delete_quote(self, qid):
        self._run("DELETE FROM quotes WHERE id=?", (qid,))

    # ── Invoices ──
    def _next_invoice_number(self):
        ym = datetime.now().strftime("%Y%m")
        r = self._run("SELECT COUNT(*) AS cnt FROM invoices WHERE invoice_number LIKE ?", (f"INV-{ym}-%",))
        return f"INV-{ym}-{(r[0]['cnt']+1):04d}"

    def create_invoice(self, client_id, job_id=None, quote_id=None, items=None, notes="", tax_rate=0):
        items_list = items or []
        subtotal, tr, tax_amt, total = self._calc_totals(items_list, tax_rate)
        inv_num = self._next_invoice_number()
        return self._run("""INSERT INTO invoices (job_id,quote_id,client_id,invoice_number,items,subtotal,tax_rate,tax_amount,total,notes)
                          VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (job_id, quote_id, client_id, inv_num, json.dumps(items_list), subtotal, tr, tax_amt, total, notes))

    def get_invoices(self, search=""):
        if search:
            return self._run("""SELECT i.*, c.name AS client_name FROM invoices i
                             JOIN clients c ON i.client_id=c.id WHERE c.name LIKE ? OR i.invoice_number LIKE ? ORDER BY i.date DESC""",
                           (f"%{search}%", f"%{search}%"))
        return self._run("""SELECT i.*, c.name AS client_name FROM invoices i
                          JOIN clients c ON i.client_id=c.id ORDER BY i.date DESC""")

    def get_invoice(self, iid):
        r = self._run("""SELECT i.*, c.name AS client_name FROM invoices i
                       JOIN clients c ON i.client_id=c.id WHERE i.id=?""", (iid,))
        if r:
            r[0]["items"] = json.loads(r[0]["items"])
            return r[0]
        return None

    def mark_paid(self, iid, method=""):
        inv = self.get_invoice(iid)
        if inv and not inv.get("paid"):
            self._run("UPDATE invoices SET paid=1, payment_method=?, payment_date=datetime('now','localtime') WHERE id=?", (method, iid))
            return True
        return False

    def record_partial(self, iid, amount, method=""):
        self._run("UPDATE invoices SET partial_paid=partial_paid+?, payment_method=? WHERE id=?", (amount, method, iid))

    def delete_invoice(self, iid):
        self._run("DELETE FROM invoices WHERE id=?", (iid,))

    # ── Hours ──
    def log_hours(self, employee, date_str, hours, description="", job_id=None, rate=0):
        hr = float(rate) if rate else 0
        return self._run("INSERT INTO hours (job_id,employee,date,hours,description,rate) VALUES (?,?,?,?,?,?)",
                        (job_id, employee, date_str, hours, description, hr))

    def get_hours(self, employee="", job_id=None, days=30):
        sql = "SELECT h.*, j.name AS job_name FROM hours h LEFT JOIN jobs j ON h.job_id=j.id WHERE 1=1"
        params = []
        if employee:
            sql += " AND h.employee=?"
            params.append(employee)
        if job_id:
            sql += " AND h.job_id=?"
            params.append(job_id)
        sql += f" AND h.date>=date('now',?||' days') ORDER BY h.date DESC"
        params.append(f"-{days}")
        rows = self._run(sql, params)
        for r in rows:
            r["pay"] = round(r["hours"] * float(r.get("rate", 0) or 0), 2)
        return rows

    def get_hours_summary(self, days=30):
        rows = self._run("""SELECT h.employee, SUM(h.hours) AS total_hours,
                          COUNT(DISTINCT h.date) AS days_worked,
                          AVG(h.rate) AS avg_rate
                          FROM hours h WHERE h.date>=date('now',?||' days')
                          GROUP BY h.employee ORDER BY h.employee""",
                        (f"-{days}",))
        for r in rows:
            r["total_pay"] = round(r["total_hours"] * float(r.get("avg_rate", 0) or 0), 2)
        return rows

    def get_single_hours(self, hid):
        r = self._run("SELECT * FROM hours WHERE id=?", (hid,))
        return r[0] if r else None

    def update_hours(self, hid, employee, date_str, hours, rate=0, description=""):
        self._run("UPDATE hours SET employee=?,date=?,hours=?,rate=?,description=? WHERE id=?",
                  (employee, date_str, hours, float(rate or 0), description, hid))

    def delete_hours(self, hid):
        self._run("DELETE FROM hours WHERE id=?", (hid,))

    # ── Expenses ──
    def add_expense(self, category, amount, description="", date_str="", job_id=None):
        d = date_str or datetime.now().strftime("%Y-%m-%d")
        return self._run("INSERT INTO expenses (job_id,category,date,amount,description) VALUES (?,?,?,?,?)",
                        (job_id, category, d, amount, description))

    def get_expenses(self, category="", job_id=None, days=30):
        sql = "SELECT e.*, j.name AS job_name FROM expenses e LEFT JOIN jobs j ON e.job_id=j.id WHERE 1=1"
        params = []
        if category:
            sql += " AND e.category=?"
            params.append(category)
        if job_id:
            sql += " AND e.job_id=?"
            params.append(job_id)
        sql += f" AND e.date>=date('now',?||' days') ORDER BY e.date DESC"
        params.append(f"-{days}")
        return self._run(sql, params)

    def get_expenses_by_category(self, days=30):
        return self._run("""SELECT e.category, SUM(e.amount) AS total, COUNT(*) AS count
                          FROM expenses e WHERE e.date>=date('now',?||' days')
                          GROUP BY e.category ORDER BY total DESC""",
                        (f"-{days}",))

    def get_single_expense(self, eid):
        r = self._run("SELECT * FROM expenses WHERE id=?", (eid,))
        return r[0] if r else None

    def update_expense(self, eid, category, amount, description="", date_str=""):
        d = date_str or datetime.now().strftime("%Y-%m-%d")
        self._run("UPDATE expenses SET category=?,amount=?,date=?,description=? WHERE id=?",
                  (category, amount, d, description, eid))

    def delete_expense(self, eid):
        self._run("DELETE FROM expenses WHERE id=?", (eid,))

    # ── Local Rates ──
    def get_local_rates(self, category=""):
        if category:
            return self._run("SELECT * FROM local_rates WHERE category=? ORDER BY item_name", (category,))
        return self._run("SELECT * FROM local_rates ORDER BY category, item_name")

    def get_rate_categories(self):
        r = self._run("SELECT DISTINCT category FROM local_rates ORDER BY category")
        return [x["category"] for x in r]

    def add_local_rate(self, category, item_name, unit, rate, description=""):
        return self._run("INSERT INTO local_rates (category,item_name,unit,rate,description) VALUES (?,?,?,?,?)",
                        (category, item_name, unit, rate, description))

    def delete_local_rate(self, rid):
        self._run("DELETE FROM local_rates WHERE id=?", (rid,))

    def update_local_rate(self, rid, category, item_name, unit, rate, description=""):
        self._run("UPDATE local_rates SET category=?,item_name=?,unit=?,rate=?,description=? WHERE id=?",
                  (category, item_name, unit, rate, description, rid))

    # ── Social / Leads ──
    def add_lead(self, name, phone="", email="", description="", source=""):
        return self._run("INSERT INTO leads (name,phone,email,description,source) VALUES (?,?,?,?,?)",
                        (name, phone, email, description, source))

    def get_leads(self, status="", days=90):
        sql = "SELECT * FROM leads WHERE date(created_at)>=date('now',?||' days')"
        params = [f"-{days}"]
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        return self._run(sql, params)

    def update_lead_status(self, lid, status):
        self._run("UPDATE leads SET status=? WHERE id=?", (status, lid))

    def update_lead(self, lid, name, phone="", email="", description=""):
        self._run("UPDATE leads SET name=?,phone=?,email=?,description=? WHERE id=?",
                  (name, phone, email, description, lid))

    def delete_lead(self, lid):
        self._run("DELETE FROM leads WHERE id=?", (lid,))

    # ── CSV Export ──
    def export_csv(self, table):
        mapper = {
            "clients": ("SELECT * FROM clients ORDER BY name", []),
            "quotes": ("SELECT q.*, c.name AS client_name FROM quotes q JOIN clients c ON q.client_id=c.id ORDER BY q.date DESC", []),
            "invoices": ("SELECT i.*, c.name AS client_name FROM invoices i JOIN clients c ON i.client_id=c.id ORDER BY i.date DESC", []),
            "hours": ("SELECT h.*, j.name AS job_name FROM hours h LEFT JOIN jobs j ON h.job_id=j.id ORDER BY h.date DESC", []),
            "expenses": ("SELECT e.*, j.name AS job_name FROM expenses e LEFT JOIN jobs j ON e.job_id=j.id ORDER BY e.date DESC", []),
            "jobs": ("SELECT j.*, c.name AS client_name FROM jobs j JOIN clients c ON j.client_id=c.id ORDER BY j.created_at DESC", []),
            "local_rates": ("SELECT * FROM local_rates ORDER BY category, item_name", []),
            "leads": ("SELECT * FROM leads ORDER BY created_at DESC", []),
        }
        if table not in mapper:
            return None
        sql, params = mapper[table]
        rows = self._run(sql, params)
        if not rows:
            return None
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
        return out.getvalue()

    # ── Dashboard ──
    def dashboard(self):
        unpaid = self._run("SELECT COALESCE(SUM(total),0) AS v FROM invoices WHERE paid=0")
        paid = self._run("SELECT COALESCE(SUM(total),0) AS v FROM invoices WHERE paid=1 AND date>=date('now','-30 days')")
        expenses = self._run("SELECT COALESCE(SUM(amount),0) AS v FROM expenses WHERE date>=date('now','-30 days')")
        hours = self._run("SELECT COALESCE(SUM(hours),0) AS v FROM hours WHERE date>=date('now','-30 days')")
        active_jobs = self._run("SELECT COUNT(*) AS v FROM jobs WHERE status='active'")
        total_clients = self._run("SELECT COUNT(*) AS v FROM clients")
        recent_invoices = self._run("""SELECT i.*, c.name AS client_name FROM invoices i
                                    JOIN clients c ON i.client_id=c.id ORDER BY i.date DESC LIMIT 5""")
        recent_quotes = self._run("""SELECT q.*, c.name AS client_name FROM quotes q
                                  JOIN clients c ON q.client_id=c.id ORDER BY q.date DESC LIMIT 5""")
        expense_cats = self._run("""SELECT e.category, SUM(e.amount) AS total, COUNT(*) AS count
                                 FROM expenses e WHERE e.date>=date('now','-30 days')
                                 GROUP BY e.category ORDER BY total DESC""")
        top_expense = expense_cats[0] if expense_cats else None
        net = (paid[0]["v"] if paid else 0) - (expenses[0]["v"] if expenses else 0)
        return {
            "outstanding": round(unpaid[0]["v"], 2) if unpaid else 0,
            "paid_30d": round(paid[0]["v"], 2) if paid else 0,
            "expenses_30d": round(expenses[0]["v"], 2) if expenses else 0,
            "hours_30d": round(hours[0]["v"], 2) if hours else 0,
            "active_jobs": active_jobs[0]["v"] if active_jobs else 0,
            "total_clients": total_clients[0]["v"] if total_clients else 0,
            "net_30d": round(net, 2),
            "recent_invoices": recent_invoices,
            "recent_quotes": recent_quotes,
            "expense_categories": expense_cats,
            "top_expense": top_expense,
        }

    # ── AI Estimate Generation ──
    def generate_estimate(self, description, brain=None):
        rates = self._run("SELECT category, item_name, unit, rate, description FROM local_rates ORDER BY category")
        rates_str = "\n".join(
            f"  [{r['category']}] {r['item_name']} — ${r['rate']:.2f}/{r['unit']}"
            for r in rates
        )
        prompt = f"""You are an estimator for Vision Works General Contracting in Poplar Bluff, MO.
Generate a detailed quote estimate as a JSON array of line items.

Available local rates for reference (use these as a guide):
{rates_str}

Job description: {description}

Return ONLY a JSON array of objects with these fields:
- "desc": item description (be specific)
- "qty": quantity (number)
- "rate": unit rate in dollars (number)
- "unit": unit label - use varied units ("hour", "sq ft", "linear ft", "each", "load", "day", "sq yd") as appropriate
- "type": one of "Labor", "Material", "Subcontractor", "Equipment", "Permit", "Transportation"
- "total": qty * rate (number)

Include ALL types of costs: labor, materials, subcontractors, equipment rental, permits, disposal, transportation.
Be realistic about quantities for Poplar Bluff, MO. Use local rates where applicable.
Return valid JSON ONLY, no other text."""

        if brain is None:
            try:
                from kai_prime.web.server import brain as server_brain
                if server_brain is not None:
                    brain = server_brain
            except Exception:
                pass

        chain = None
        if brain is not None:
            chain = getattr(brain, "_provider_chain", None)
        if chain is None or not chain.available_providers:
            try:
                from kai_prime.brain.provider_chain import ProviderChain
                chain = ProviderChain(WORKSPACE)
            except Exception:
                chain = None
        if chain is None:
            return None, "AI service is not available right now."
        if not chain.has_cloud_provider:
            return None, ("AI isn't set up on the server yet. Add an Environment variable GROQ_API_KEY "
                          "(your Groq API key) in Render, then Deploy Latest Commit. "
                          "For now, use + New Quote to build one by hand.")

        messages = [
            {"role": "system", "content": "You are an expert construction estimator for Vision Works General Contracting in Poplar Bluff, MO. Always respond with valid JSON only — never use markdown, never add commentary. Produce a JSON array of line items."},
            {"role": "user", "content": prompt},
        ]

        try:
            resp = chain.chat(messages, temperature=0.2, max_tokens=3000)
        except Exception as ex:
            return None, f"AI error: {ex}"

        items = self._parse_estimate(resp)
        if not items:
            messages.append({"role": "user", "content": "Your last reply could not be read as a JSON array. Reply with ONLY the raw JSON array — no markdown code fences, no extra words."})
            try:
                resp = chain.chat(messages, temperature=0.0, max_tokens=3000)
            except Exception:
                resp = None
            items = self._parse_estimate(resp)
        if not items:
            if not resp:
                return None, "AI didn't respond — the service may be busy. Please try again in a minute."
            return None, "The AI answer couldn't be turned into line items. Try a more detailed description, or build the quote by hand with + New Quote."
        return items, None

    def _parse_estimate(self, text):
        if not text:
            return None
        text = text.strip()
        fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
        if fence:
            text = fence.group(1).strip()
        candidates = []
        arr = re.search(r'\[[\s\S]*\]', text)
        if arr:
            candidates.append(arr.group())
        obj = re.search(r'\{[\s\S]*\}', text)
        if obj:
            candidates.append(obj.group())
        for cand in candidates:
            try:
                data = json.loads(cand)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                for key in ("items", "line_items", "lines", "estimate", "data", "results"):
                    if isinstance(data.get(key), list):
                        data = data[key]
                        break
            if not isinstance(data, list):
                data = [data]
            cleaned = []
            for i in data:
                if not isinstance(i, dict):
                    continue
                desc = i.get("desc") or i.get("description") or ""
                try:
                    qty = float(i.get("qty", 1))
                except (TypeError, ValueError):
                    qty = 1
                try:
                    rate = float(i.get("rate", 0))
                except (TypeError, ValueError):
                    rate = 0
                if desc and rate > 0:
                    cleaned.append({
                        "desc": desc, "qty": qty, "rate": rate,
                        "unit": i.get("unit", ""), "type": i.get("type", "Labor"),
                        "total": round(qty * rate, 2)
                    })
            if cleaned:
                return cleaned
        return None


_biz = None
def get_business():
    global _biz
    if _biz is None:
        _biz = BusinessManager()
    return _biz
