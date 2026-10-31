# database_v2.py
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import os
import streamlit as st

# Safe AI Imports (prevents app crashes if package is missing)
try:
    from google import genai
    from PIL import Image
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

DB_FILE = "medical_store_v2.db"

def init_clean_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

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

    conn.commit()
    conn.close()

def safe_int(val, default=15):
    if pd.isna(val) or str(val).strip() == "" or str(val).strip().lower() == "nan":
        return default
    try:
        return int(float(val))
    except Exception:
        return default

def safe_float(val, default=0.0):
    if pd.isna(val) or str(val).strip() == "" or str(val).strip().lower() == "nan":
        return default
    try:
        return float(val)
    except Exception:
        return default

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

def update_party(party_id, name, phone, gstin, credit_days, opening_bal, as_on_date):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE parties 
        SET party_name = ?, phone = ?, gstin = ?, credit_period_days = ?, opening_balance = ?, as_on_date = ?
        WHERE party_id = ?
    """, (name, phone, gstin, credit_days, opening_bal, as_on_date, party_id))
    conn.commit()
    conn.close()

def delete_party(party_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM purchase_invoices WHERE party_id = ?", (party_id,))
    cursor.execute("DELETE FROM distributor_payments WHERE party_id = ?", (party_id,))
    cursor.execute("DELETE FROM parties WHERE party_id = ?", (party_id,))
    conn.commit()
    conn.close()

def bulk_save_parties(df_parties):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    df_parties.columns = [str(c).strip().lower().replace(" ", "_") for c in df_parties.columns]
    success_count = 0
    errors = []
    
    for idx, row in df_parties.iterrows():
        try:
            name = str(row.get('party_name', '')).strip().title()
            if not name or name == "Nan" or pd.isna(row.get('party_name')):
                continue
            phone = str(row.get('phone', '')).strip()
            if phone == "nan" or pd.isna(row.get('phone')): phone = ""
            gstin = str(row.get('gstin', '')).strip().upper()
            if gstin == "NAN" or pd.isna(row.get('gstin')): gstin = ""
            
            credit_days = safe_int(row.get('credit_period_days'), 15)
            opening_bal = safe_float(row.get('opening_balance'), 0.0)
            as_on_date = str(row.get('as_on_date', datetime.now().strftime("%Y-%m-%d"))).strip()[:10]
            if as_on_date == "nan" or not as_on_date: as_on_date = datetime.now().strftime("%Y-%m-%d")
            
            cursor.execute("""
                INSERT INTO parties (party_name, phone, gstin, credit_period_days, opening_balance, as_on_date, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(party_name) DO UPDATE SET
                phone=excluded.phone,
                gstin=excluded.gstin,
                credit_period_days=excluded.credit_period_days,
                opening_balance=excluded.opening_balance,
                as_on_date=excluded.as_on_date
            """, (name, phone, gstin, credit_days, opening_bal, as_on_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            success_count += 1
        except Exception as e:
            errors.append(f"Row {idx+2}: {e}")
    conn.commit()
    conn.close()
    return success_count, errors

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

def bulk_save_purchase_invoices(df_invoices):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    df_invoices.columns = [str(c).strip().lower().replace(" ", "_") for c in df_invoices.columns]
    success_count = 0
    errors = []
    
    for idx, row in df_invoices.iterrows():
        try:
            party_name = str(row.get('party_name', '')).strip().title()
            inv_no = str(row.get('invoice_number', '')).strip()
            inv_date = str(row.get('invoice_date', '')).strip()[:10]
            amount = safe_float(row.get('bill_amount'), 0.0)
            
            if not party_name or party_name == "Nan" or not inv_no or amount <= 0:
                continue
            
            cursor.execute("SELECT party_id, credit_period_days FROM parties WHERE party_name = ?", (party_name,))
            party_row = cursor.fetchone()
            
            if party_row:
                p_id, credit_days = party_row[0], party_row[1]
                inv_dt = datetime.strptime(inv_date, "%Y-%m-%d")
                due_dt = inv_dt + timedelta(days=int(credit_days))
                due_date_str = due_dt.strftime("%Y-%m-%d")
                
                cursor.execute("""
                    INSERT INTO purchase_invoices (party_id, invoice_number, invoice_date, due_date, bill_amount, status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'UNPAID', ?)
                """, (p_id, inv_no, inv_date, due_date_str, amount, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                success_count += 1
            else:
                errors.append(f"Row {idx+2}: Party '{party_name}' not found in Master List.")
        except Exception as e:
            errors.append(f"Row {idx+2}: {e}")
    conn.commit()
    conn.close()
    return success_count, errors

def get_purchase_invoices_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    query = """
        SELECT i.invoice_id, p.party_id, p.party_name, i.invoice_number, i.invoice_date, i.due_date, i.bill_amount, i.status
        FROM purchase_invoices i
        JOIN parties p ON i.party_id = p.party_id
        ORDER BY i.due_date ASC
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def get_party_dues_summary() -> pd.DataFrame:
    parties_df = get_parties_df()
    if parties_df.empty: return pd.DataFrame()
    invoices_df = get_purchase_invoices_df()
    summary_list = []
    today = datetime.now().date()

    for _, party in parties_df.iterrows():
        p_id, p_name = party["party_id"], party["party_name"]
        opening_bal, as_on = party["opening_balance"], party["as_on_date"]
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
                if days_left < 0: urgency = f"🔴 OVERDUE ({ref_date_str})"
                elif days_left <= 3: urgency = f"🟡 Due Soon ({ref_date_str}, {days_left}d)"
                else: urgency = f"🟢 Safe ({ref_date_str}, {days_left}d)"
            except Exception: pass

        summary_list.append({
            "party_name": p_name, "opening_balance": opening_bal, "opening_as_on": as_on,
            "unpaid_bills_total": unpaid_inv_total, "total_due_amount": total_due,
            "earliest_due_date": earliest_due if earliest_due else "Opening Only",
            "Payment_Urgency": urgency
        })
    return pd.DataFrame(summary_list).sort_values(by="total_due_amount", ascending=False)

def record_distributor_payment(party_id, invoice_ids_to_clear, payment_amount, payment_mode, notes, recorded_by):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO distributor_payments (party_id, amount_paid, payment_mode, notes, recorded_by, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (party_id, payment_amount, payment_mode, notes, recorded_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    
    if invoice_ids_to_clear:
        placeholders = ','.join(['?'] * len(invoice_ids_to_clear))
        cursor.execute(f"UPDATE purchase_invoices SET status = 'PAID' WHERE invoice_id IN ({placeholders})", invoice_ids_to_clear)
    conn.commit()
    conn.close()

def get_distributor_payments_df() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    try:
        df = pd.read_sql_query("""
            SELECT dp.payment_id, p.party_name, dp.amount_paid, dp.payment_mode, dp.notes, dp.recorded_by, dp.timestamp
            FROM distributor_payments dp JOIN parties p ON dp.party_id = p.party_id
            ORDER BY dp.payment_id DESC
        """, conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df

def extract_invoice_from_image(image_file):
    if not AI_AVAILABLE:
        return {"error": "google-genai package not installed."}
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"error": "Gemini API key not found in environment or secrets."}
    try:
        client = genai.Client(api_key=api_key)
        image = Image.open(image_file)
        prompt = """
        Analyze this distributor purchase invoice or bill image. 
        Extract the following details in valid JSON format:
        {
            "party_name": "Name of the supplier, distributor, or pharma company",
            "invoice_number": "Invoice or bill number string",
            "invoice_date": "Date of invoice in YYYY-MM-DD format",
            "bill_amount": 0.0
        }
        Return ONLY valid JSON without any markdown formatting or extra text.
        """
        response = client.models.generate_content(model='gemini-3.8-flash', contents=[image, prompt])
        import json
        text_resp = response.text.strip()
        if text_resp.startswith("```json"): text_resp = text_resp[7:-3].strip()
        elif text_resp.startswith("```"): text_resp = text_resp[3:-3].strip()
        return json.loads(text_resp)
    except Exception as e:
        return {"error": str(e)}

def extract_payment_from_image(image_file):
    if not AI_AVAILABLE:
        return {"error": "google-genai package not installed."}
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"error": "Gemini API key not found in environment or secrets."}
    try:
        client = genai.Client(api_key=api_key)
        image = Image.open(image_file)
        prompt = """
        Analyze this daily finance sheet, payment receipt, or distributor payment slip. 
        Extract the following details in valid JSON format:
        {
            "party_name": "Name of the distributor or party paid",
            "amount_paid": 0.0,
            "payment_mode": "CASH / UPI / BANK_TRANSFER / CHEQUE",
            "notes": "Any reference number or notes mentioned"
        }
        Return ONLY valid JSON without any markdown formatting or extra text.
        """
        response = client.models.generate_content(model='gemini-3.8-flash', contents=[image, prompt])
        import json
        text_resp = response.text.strip()
        if text_resp.startswith("```json"): text_resp = text_resp[7:-3].strip()
        elif text_resp.startswith("```"): text_resp = text_resp[3:-3].strip()
        return json.loads(text_resp)
    except Exception as e:
        return {"error": str(e)}
