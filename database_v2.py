# database_v2.py
import pandas as pd
from datetime import datetime, timedelta
import os
import streamlit as st
from sqlalchemy import create_engine, text

try:
    from google import genai
    from PIL import Image
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

@st.cache_resource(show_spinner=False)
def get_engine():
    db_url = ""
    if "SUPABASE_DB_URL" in st.secrets:
        db_url = st.secrets["SUPABASE_DB_URL"]
    if not db_url:
        db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        raise ValueError("SUPABASE_DB_URL is missing from Streamlit secrets.")
        
    db_url = db_url.strip()
    if db_url.startswith("postgresql://") and "+psycopg2" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        
    return create_engine(db_url, pool_pre_ping=True, connect_args={'sslmode': 'require', 'connect_timeout': 10})

def test_database_connection():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Connected successfully to Supabase!"
    except Exception as e:
        return False, str(e)

def init_clean_database():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS parties (
                party_id SERIAL PRIMARY KEY, party_name TEXT UNIQUE NOT NULL, phone TEXT, gstin TEXT,
                credit_period_days INTEGER DEFAULT 15, opening_balance REAL DEFAULT 0.0, as_on_date TEXT, created_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS purchase_invoices (
                invoice_id SERIAL PRIMARY KEY, party_id INTEGER REFERENCES parties(party_id) ON DELETE CASCADE,
                invoice_number TEXT NOT NULL, invoice_date TEXT NOT NULL, due_date TEXT NOT NULL,
                bill_amount REAL NOT NULL, status TEXT DEFAULT 'UNPAID', created_at TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS distributor_payments (
                payment_id SERIAL PRIMARY KEY, party_id INTEGER REFERENCES parties(party_id) ON DELETE CASCADE,
                amount_paid REAL NOT NULL, payment_mode TEXT, payment_date TEXT, notes TEXT, recorded_by TEXT, timestamp TEXT
            )
        """))

def safe_int(val, default=15):
    if pd.isna(val) or str(val).strip() == "" or str(val).strip().lower() == "nan": return default
    try: return int(float(val))
    except Exception: return default

def safe_float(val, default=0.0):
    if pd.isna(val) or str(val).strip() == "" or str(val).strip().lower() == "nan": return default
    try: return float(val)
    except Exception: return default

def parse_date(val):
    if pd.isna(val) or str(val).strip() == "" or str(val).strip().lower() == "nan": return datetime.now().strftime("%Y-%m-%d")
    if isinstance(val, (datetime, pd.Timestamp)): return val.strftime("%Y-%m-%d")
    val_str = str(val).strip()
    if len(val_str) >= 10 and val_str[4] == '-' and val_str[7] == '-': return val_str[:10]
    for fmt in ["%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]:
        try: return datetime.strptime(val_str, fmt).strftime("%Y-%m-%d")
        except ValueError: continue
    return datetime.now().strftime("%Y-%m-%d")

def get_parties_df() -> pd.DataFrame:
    try: return pd.read_sql("SELECT * FROM parties ORDER BY party_name ASC", get_engine())
    except Exception: return pd.DataFrame()

def save_party(name, phone, gstin, credit_days, opening_bal, as_on_date, created_date):
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO parties (party_name, phone, gstin, credit_period_days, opening_balance, as_on_date, created_at)
            VALUES (:name, :phone, :gstin, :credit_days, :opening_bal, :as_on_date, :created_date)
            ON CONFLICT (party_name) DO UPDATE SET phone = EXCLUDED.phone, gstin = EXCLUDED.gstin, credit_period_days = EXCLUDED.credit_period_days, opening_balance = EXCLUDED.opening_balance, as_on_date = EXCLUDED.as_on_date
        """), {"name": name, "phone": phone, "gstin": gstin, "credit_days": credit_days, "opening_bal": opening_bal, "as_on_date": as_on_date, "created_date": created_date})

def update_party(party_id, name, phone, gstin, credit_days, opening_bal, as_on_date):
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE parties SET party_name = :name, phone = :phone, gstin = :gstin, credit_period_days = :credit_days, opening_balance = :opening_bal, as_on_date = :as_on_date WHERE party_id = :party_id"), {"name": name, "phone": phone, "gstin": gstin, "credit_days": credit_days, "opening_bal": opening_bal, "as_on_date": as_on_date, "party_id": party_id})

def delete_party(party_id):
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM purchase_invoices WHERE party_id = :party_id"), {"party_id": party_id})
        conn.execute(text("DELETE FROM distributor_payments WHERE party_id = :party_id"), {"party_id": party_id})
        conn.execute(text("DELETE FROM parties WHERE party_id = :party_id"), {"party_id": party_id})

def bulk_save_parties(df_parties):
    df_parties.columns = [str(c).strip().lower().replace(" ", "_") for c in df_parties.columns]
    errors, valid_rows = [], []
    for idx, row in df_parties.iterrows():
        name = str(row.get('party_name', '')).strip().title()
        if not name or name == "Nan":
            errors.append(f"Row {idx+2}: Missing Party Name")
            continue
        valid_rows.append({
            "name": name, "phone": str(row.get('phone', '')).strip(), "gstin": str(row.get('gstin', '')).strip().upper(),
            "credit_days": safe_int(row.get('credit_period_days'), 15), "opening_bal": safe_float(row.get('opening_balance'), 0.0), 
            "as_on_date": parse_date(row.get('as_on_date')), "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    if errors: return 0, errors 
    if valid_rows:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO parties (party_name, credit_period_days, opening_balance, as_on_date, created_at)
                VALUES (:name, :credit_days, :opening_bal, :as_on_date, :created_at)
                ON CONFLICT (party_name) DO NOTHING
            """), valid_rows)
    return len(valid_rows), []

def save_purchase_invoice(party_id, inv_no, inv_date, credit_days, amount, created_date):
    due_date_str = (datetime.strptime(inv_date, "%Y-%m-%d") + timedelta(days=credit_days)).strftime("%Y-%m-%d")
    with get_engine().begin() as conn:
        conn.execute(text("INSERT INTO purchase_invoices (party_id, invoice_number, invoice_date, due_date, bill_amount, status, created_at) VALUES (:p, :no, :dt, :due, :amt, 'UNPAID', :crt)"), {"p": party_id, "no": inv_no, "dt": inv_date, "due": due_date_str, "amt": amount, "crt": created_date})

def delete_multiple_purchase_invoices(invoice_ids):
    if not invoice_ids: return
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM purchase_invoices WHERE invoice_id = ANY(:inv_ids)"), {"inv_ids": invoice_ids})

def bulk_save_purchase_invoices(df_invoices):
    parties_df = get_parties_df()
    party_dict = {str(row['party_name']).strip().title(): (row['party_id'], row['credit_period_days']) for _, row in parties_df.iterrows()}
    df_invoices.columns = [str(c).strip().lower().replace(" ", "_") for c in df_invoices.columns]
    errors, valid_rows = [], []
    for idx, row in df_invoices.iterrows():
        party_name, inv_no, amt = str(row.get('party_name', '')).strip().title(), str(row.get('invoice_number', '')).strip(), safe_float(row.get('bill_amount'), 0.0)
        if not party_name or party_name == "Nan" or not inv_no or amt <= 0:
            errors.append(f"Row {idx+2}: Missing fields or invalid amount.")
            continue
        if party_name not in party_dict:
            errors.append(f"Row {idx+2}: Party '{party_name}' not found in Master List.")
            continue
        p_id, credit_days = party_dict[party_name]
        inv_date = parse_date(row.get('invoice_date'))
        due = (datetime.strptime(inv_date, "%Y-%m-%d") + timedelta(days=int(credit_days))).strftime("%Y-%m-%d")
        valid_rows.append({"p": p_id, "no": inv_no, "dt": inv_date, "due": due, "amt": amt, "crt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    if errors: return 0, errors 
    if valid_rows:
        with get_engine().begin() as conn:
            conn.execute(text("INSERT INTO purchase_invoices (party_id, invoice_number, invoice_date, due_date, bill_amount, status, created_at) VALUES (:p, :no, :dt, :due, :amt, 'UNPAID', :crt)"), valid_rows)
    return len(valid_rows), []

def get_purchase_invoices_df() -> pd.DataFrame:
    try: return pd.read_sql("SELECT i.invoice_id, p.party_id, p.party_name, i.invoice_number, i.invoice_date, i.due_date, i.bill_amount, i.status FROM purchase_invoices i JOIN parties p ON i.party_id = p.party_id ORDER BY i.due_date ASC", get_engine())
    except Exception: return pd.DataFrame()

def record_distributor_payment(party_id, invoice_ids_to_clear, payment_amount, payment_mode, payment_date, notes, recorded_by):
    with get_engine().begin() as conn:
        conn.execute(text("INSERT INTO distributor_payments (party_id, amount_paid, payment_mode, payment_date, notes, recorded_by, timestamp) VALUES (:p, :amt, :mode, :dt, :notes, :by, :ts)"), {"p": party_id, "amt": payment_amount, "mode": payment_mode, "dt": payment_date, "notes": notes, "by": recorded_by, "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        if invoice_ids_to_clear: conn.execute(text("UPDATE purchase_invoices SET status = 'PAID' WHERE invoice_id = ANY(:inv_ids)"), {"inv_ids": invoice_ids_to_clear})

def delete_multiple_distributor_payments(payment_ids):
    if not payment_ids: return
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM distributor_payments WHERE payment_id = ANY(:p_ids)"), {"p_ids": payment_ids})

def bulk_save_distributor_payments(df_payments):
    parties_df = get_parties_df()
    party_dict = {str(row['party_name']).strip().title(): row['party_id'] for _, row in parties_df.iterrows()}
    df_payments.columns = [str(c).strip().lower().replace(" ", "_") for c in df_payments.columns]
    errors, valid_rows = [], []
    for idx, row in df_payments.iterrows():
        party_name = str(row.get('party_name', '')).strip().title()
        amt = safe_float(row.get('amount_paid'), 0.0)
        if not party_name or party_name == "Nan" or amt <= 0:
            errors.append(f"Row {idx+2}: Missing fields or invalid amount.")
            continue
        if party_name not in party_dict:
            errors.append(f"Row {idx+2}: Party '{party_name}' not found in Master List.")
            continue
        p_id = party_dict[party_name]
        pay_date = parse_date(row.get('payment_date'))
        mode = str(row.get('payment_mode', 'CASH')).strip().upper()
        if mode not in ["CASH", "UPI", "BANK_TRANSFER", "CHEQUE"]: mode = "CASH"
        notes = str(row.get('notes', '')).strip()
        if notes == "Nan": notes = ""
        
        valid_rows.append({
            "p": p_id, "amt": amt, "mode": mode, "dt": pay_date, 
            "notes": notes, "by": "Bulk Import", "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    if errors: return 0, errors 
    if valid_rows:
        with get_engine().begin() as conn:
            conn.execute(text("INSERT INTO distributor_payments (party_id, amount_paid, payment_mode, payment_date, notes, recorded_by, timestamp) VALUES (:p, :amt, :mode, :dt, :notes, :by, :ts)"), valid_rows)
    return len(valid_rows), []

def get_distributor_payments_df() -> pd.DataFrame:
    try: return pd.read_sql("SELECT dp.payment_id, dp.party_id, p.party_name, dp.amount_paid, dp.payment_mode, dp.payment_date, dp.notes, dp.recorded_by, dp.timestamp FROM distributor_payments dp JOIN parties p ON dp.party_id = p.party_id ORDER BY dp.payment_id DESC", get_engine())
    except Exception: return pd.DataFrame()

def get_party_dues_summary() -> pd.DataFrame:
    parties_df = get_parties_df()
    if parties_df.empty: return pd.DataFrame()
    invoices_df = get_purchase_invoices_df()
    payments_df = get_distributor_payments_df()
    summary_list = []
    today = datetime.now().date()
    
    for _, party in parties_df.iterrows():
        p_id, p_name, opening_bal, as_on = party["party_id"], party["party_name"], party["opening_balance"], party["as_on_date"]
        
        total_bills, earliest_due = 0.0, None
        if not invoices_df.empty:
            party_invs = invoices_df[invoices_df["party_id"] == p_id]
            if not party_invs.empty:
                total_bills = party_invs["bill_amount"].sum()
                unpaid = party_invs[party_invs["status"] == "UNPAID"]
                if not unpaid.empty: earliest_due = unpaid["due_date"].min()

        total_payments = 0.0
        if not payments_df.empty and "party_id" in payments_df.columns:
            party_pays = payments_df[payments_df["party_id"] == p_id]
            if not party_pays.empty: total_payments = party_pays["amount_paid"].sum()

        # RULE ENFORCEMENT: Total Outstanding = Opening Dues + Bills - Paid
        total_due = opening_bal + total_bills - total_payments
        urgency = "🟢 Safe"
        ref_date_str = earliest_due if earliest_due else as_on

        if ref_date_str:
            try:
                ref_dt = datetime.strptime(str(ref_date_str), "%Y-%m-%d").date()
                days_left = (ref_dt - today).days
                if days_left < 0: urgency = f"🔴 OVERDUE ({ref_date_str})"
                elif days_left <= 3: urgency = f"🟡 Due Soon ({ref_date_str})"
                else: urgency = f"🟢 Safe ({ref_date_str})"
            except: pass

        summary_list.append({
            "party_name": p_name, "opening_balance": opening_bal, "opening_as_on": as_on,
            "total_bills": total_bills, "total_payments": total_payments,
            "total_due_amount": total_due, "Payment_Urgency": urgency
        })
    return pd.DataFrame(summary_list).sort_values(by="total_due_amount", ascending=False)

def extract_invoice_from_image(image_file):
    if not AI_AVAILABLE: return {"error": "google-genai package not installed."}
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")
    if not api_key: return {"error": "Gemini API key not found in environment or secrets."}
    try:
        client = genai.Client(api_key=api_key)
        image = Image.open(image_file)
        prompt = """Analyze this distributor purchase invoice or bill image. 
        Extract the following details in valid JSON format:
        { "party_name": "Name of the supplier, distributor, or pharma company", "invoice_number": "Invoice or bill number string", "invoice_date": "Date of invoice in YYYY-MM-DD format", "bill_amount": 0.0 }
        Return ONLY valid JSON without any markdown formatting or extra text."""
        response = client.models.generate_content(model='gemini-2.5-flash', contents=[image, prompt])
        import json
        text_resp = response.text.strip()
        if text_resp.startswith("```json"): text_resp = text_resp[7:-3].strip()
        elif text_resp.startswith("```"): text_resp = text_resp[3:-3].strip()
        return json.loads(text_resp)
    except Exception as e: return {"error": str(e)}

def extract_payment_from_image(image_file):
    if not AI_AVAILABLE: return {"error": "google-genai package not installed."}
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", "")
    if not api_key: return {"error": "Gemini API key not found in environment or secrets."}
    try:
        client = genai.Client(api_key=api_key)
        image = Image.open(image_file)
        prompt = """Analyze this daily finance sheet, payment receipt, or distributor payment slip. 
        Extract the following details in valid JSON format:
        { "party_name": "Name of the distributor or party paid", "amount_paid": 0.0, "payment_mode": "CASH / UPI / BANK_TRANSFER / CHEQUE", "notes": "Any reference number or notes mentioned" }
        Return ONLY valid JSON without any markdown formatting or extra text."""
        response = client.models.generate_content(model='gemini-2.5-flash', contents=[image, prompt])
        import json
        text_resp = response.text.strip()
        if text_resp.startswith("```json"): text_resp = text_resp[7:-3].strip()
        elif text_resp.startswith("```"): text_resp = text_resp[3:-3].strip()
        return json.loads(text_resp)
    except Exception as e: return {"error": str(e)}
