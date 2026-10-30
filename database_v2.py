# database_v2.py
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

DB_FILE = "medical_store_v2.db"

def init_clean_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. Parties Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parties (
            party_id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_name TEXT UNIQUE NOT NULL,
            phone TEXT,
            gstin TEXT,
            credit_period_days INTEGER DEFAULT 15,
            opening_balance REAL DEFAULT 0.0,
            as_on_date TEXT,
            created_at TEXT
        )
    """)

    # 2. Purchase Invoices Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_invoices (
            invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id INTEGER,
            invoice_number TEXT NOT NULL,
            invoice_date TEXT NOT NULL,
            due_date TEXT NOT NULL,
            bill_amount REAL NOT NULL,
            status TEXT DEFAULT 'UNPAID',
            created_at TEXT,
            FOREIGN KEY (party_id) REFERENCES parties (party_id)
        )
    """)

    # 3. Financial Openings Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_openings (
            opening_id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_category TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL,
            entry_nature TEXT NOT NULL,
            created_at TEXT
        )
    """)

    # 4. Outstanding Adjustments Audit Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS outstanding_adjustments (
            adjustment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id INTEGER,
            previous_balance REAL,
            new_balance REAL,
            reason TEXT NOT NULL,
            adjusted_by TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (party_id) REFERENCES parties (party_id)
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def get_parties_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM parties ORDER BY party_name ASC", conn)
    conn.close()
    return df

def save_party(name, phone, gstin, credit_days, opening_bal, as_on_date, created_date):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO parties (party_name, phone, gstin, credit_period_days, opening_balance, as_on_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(party_name) DO UPDATE SET
        phone=excluded.phone,
        gstin=excluded.gstin,
        credit_period_days=excluded.credit_period_days,
        opening_balance=excluded.opening_balance,
        as_on_date=excluded.as_on_date
    """, (name, phone, gstin, credit_days, opening_bal, as_on_date, created_date))
    conn.commit()
    conn.close()

def save_purchase_invoice(party_id, inv_no, inv_date, credit_days, amount, created_date):
    inv_dt = datetime.strptime(inv_date, "%Y-%m-%d")
    due_dt = inv_dt + timedelta(days=credit_days)
    due_date_str = due_dt.strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO purchase_invoices (party_id, invoice_number, invoice_date, due_date, bill_amount, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'UNPAID', ?)
    """, (party_id, inv_no, inv_date, due_date_str, amount, created_date))
    conn.commit()
    conn.close()

def get_purchase_invoices_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    query = """
        SELECT 
            i.invoice_id,
            p.party_id,
            p.party_name,
            i.invoice_number,
            i.invoice_date,
            i.due_date,
            i.bill_amount,
            i.status
        FROM purchase_invoices i
        JOIN parties p ON i.party_id = p.party_id
        ORDER BY i.due_date ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def record_balance_correction(party_id, new_opening_balance, reason, admin_user):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT opening_balance FROM parties WHERE party_id = ?", (party_id,))
    row = cursor.fetchone()
    prev_bal = row[0] if row else 0.0

    cursor.execute("UPDATE parties SET opening_balance = ? WHERE party_id = ?", (new_opening_balance, party_id))
    cursor.execute("""
        INSERT INTO outstanding_adjustments (party_id, previous_balance, new_balance, reason, adjusted_by, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (party_id, prev_bal, new_opening_balance, reason, admin_user, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def get_adjustment_logs() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    query = """
        SELECT 
            a.adjustment_id,
            p.party_name,
            a.previous_balance,
            a.new_balance,
            a.reason,
            a.adjusted_by,
            a.timestamp
        FROM outstanding_adjustments a
        JOIN parties p ON a.party_id = p.party_id
        ORDER BY a.adjustment_id DESC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def get_party_dues_summary() -> pd.DataFrame:
    parties_df = get_parties_df()
    if parties_df.empty:
        return pd.DataFrame()

    invoices_df = get_purchase_invoices_df()
    summary_list = []
    today = datetime.now().date()

    for _, party in parties_df.iterrows():
        p_id = party["party_id"]
        p_name = party["party_name"]
        opening_bal = party["opening_balance"]
        as_on = party["as_on_date"]

        unpaid_inv_total = 0.0
        earliest_due = None

        if not invoices_df.empty:
            party_invs = invoices_df[(invoices_df["party_id"] == p_id) & (invoices_df["status"] == "UNPAID")]
            if not party_invs.empty:
                unpaid_inv_total = party_invs["bill_amount"].sum()
                earliest_due = party_invs["due_date"].min()

        total_due = opening_bal + unpaid_inv_total
        urgency = "🟢 Safe"
        ref_date_str = earliest_due if earliest_due else as_on

        if ref_date_str:
            try:
                ref_dt = datetime.strptime(str(ref_date_str), "%Y-%m-%d").date()
                days_left = (ref_dt - today).days
                if days_left < 0:
                    urgency = f"🔴 OVERDUE (Due: {ref_date_str})"
                elif days_left <= 3:
                    urgency = f"🟡 Due Soon (Due: {ref_date_str}, {days_left}d left)"
                else:
                    urgency = f"🟢 Safe (Due: {ref_date_str}, {days_left}d left)"
            except Exception:
                pass

        summary_list.append({
            "party_name": p_name,
            "opening_balance": opening_bal,
            "opening_as_on": as_on,
            "unpaid_bills_total": unpaid_inv_total,
            "total_due_amount": total_due,
            "earliest_due_date": earliest_due if earliest_due else "Opening Balance Only",
            "Payment_Urgency": urgency
        })

    return pd.DataFrame(summary_list).sort_values(by="total_due_amount", ascending=False)

def get_financial_openings_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM financial_openings ORDER BY opening_id DESC", conn)
    conn.close()
    return df

def save_financial_opening(category, desc, amount, nature, created_date):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO financial_openings (item_category, description, amount, entry_nature, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (category, desc, amount, nature, created_date))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_clean_database()

# --- Add to database_v2.py ---

def record_distributor_payment(party_id, invoice_ids_to_clear, payment_amount, payment_mode, notes, recorded_by):
    """Records a payment to a distributor, marks selected bills as PAID, and logs the transaction."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. Insert into payment records table (we can create a table or store it in an audit log / payments table)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS distributor_payments (
            payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            party_id INTEGER,
            amount_paid REAL NOT NULL,
            payment_mode TEXT,
            notes TEXT,
            recorded_by TEXT,
            timestamp TEXT,
            FOREIGN KEY (party_id) REFERENCES parties (party_id)
        )
    """)

    cursor.execute("""
        INSERT INTO distributor_payments (party_id, amount_paid, payment_mode, notes, recorded_by, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (party_id, payment_amount, payment_mode, notes, recorded_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    # 2. If specific bills were selected to be cleared, update their status to PAID
    if invoice_ids_to_clear:
        placeholders = ','.join(['?'] * len(invoice_ids_to_clear))
        cursor.execute(f"""
            UPDATE purchase_invoices 
            SET status = 'PAID' 
            WHERE invoice_id IN ({placeholders})
        """, invoice_ids_to_clear)

    conn.commit()
    conn.close()

def get_distributor_payments_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    query = """
        SELECT 
            dp.payment_id,
            p.party_name,
            dp.amount_paid,
            dp.payment_mode,
            dp.notes,
            dp.recorded_by,
            dp.timestamp
        FROM distributor_payments dp
        JOIN parties p ON dp.party_id = p.party_id
        ORDER BY dp.payment_id DESC
    """
    try:
        df = pd.read_sql_query(query, conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df
