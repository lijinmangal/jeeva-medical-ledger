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

SUPABASE_URL = os.environ.get("SUPABASE_DB_URL") or st.secrets.get("SUPABASE_DB_URL", "")

def get_engine():
    if not SUPABASE_URL:
        st.error("⚠️ SUPABASE_DB_URL is missing from Streamlit secrets or environment variables.")
        st.stop()
    
    # Explicitly prefix with postgresql+psycopg2:// so SQLAlchemy uses psycopg2
    db_url = SUPABASE_URL
    if db_url.startswith("postgresql://") and "+psycopg2" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        
    return create_engine(db_url)

def init_clean_database():
    """Initializes PostgreSQL tables in Supabase if they don't already exist."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS parties (
                party_id SERIAL PRIMARY KEY,
                party_name TEXT UNIQUE NOT NULL,
                phone TEXT,
                gstin TEXT,
                credit_period_days INTEGER DEFAULT 15,
                opening_balance REAL DEFAULT 0.0,
                as_on_date TEXT,
                created_at TEXT
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS purchase_invoices (
                invoice_id SERIAL PRIMARY KEY,
                party_id INTEGER REFERENCES parties(party_id) ON DELETE CASCADE,
                invoice_number TEXT NOT NULL,
                invoice_date TEXT NOT NULL,
                due_date TEXT NOT NULL,
                bill_amount REAL NOT NULL,
                status TEXT DEFAULT 'UNPAID',
                created_at TEXT
            )
        """))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS distributor_payments (
                payment_id SERIAL PRIMARY KEY,
                party_id INTEGER REFERENCES parties(party_id) ON DELETE CASCADE,
                amount_paid REAL NOT NULL,
                payment_mode TEXT,
                payment_date TEXT,
                notes TEXT,
                recorded_by TEXT,
                timestamp TEXT
            )
        """))

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

def parse_date(val):
    if pd.isna(val) or str(val).strip() == "" or str(val).strip().lower() == "nan":
        return datetime.now().strftime("%Y-%m-%d")
    if isinstance(val, (datetime, pd.Timestamp)):
        return val.strftime("%Y-%m-%d")
    val_str = str(val).strip()
    if len(val_str) >= 10 and val_str[4] == '-' and val_str[7] == '-':
        return val_str[:10]
    formats = ["%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d-%b-%y"]
    for fmt in formats:
        try:
            dt = datetime.strptime(val_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.now().strftime("%Y-%m-%d")

def get_parties_df() -> pd.DataFrame:
    engine = get_engine()
    try:
        df = pd.read_sql("SELECT * FROM parties ORDER BY party_name ASC", engine)
    except Exception:
        df = pd.DataFrame()
    return df

def save_party(name, phone, gstin, credit_days, opening_bal, as_on_date, created_date):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO parties (party_name, phone, gstin, credit_period_days, opening_balance, as_on_date, created_at)
            VALUES (:name, :phone, :gstin, :credit_days, :opening_bal, :as_on_date, :created_date)
            ON CONFLICT (party_name) DO UPDATE SET
            phone = EXCLUDED.phone,
            gstin = EXCLUDED.gstin,
            credit_period_days = EXCLUDED.credit_period_days,
            opening_balance = EXCLUDED.opening_balance,
            as_on_date = EXCLUDED.as_on_date
        """), {
            "name": name, "phone": phone, "gstin": gstin, 
            "credit_days": credit_days, "opening_bal": opening_bal, 
            "as_on_date": as_on_date, "created_date": created_date
        })

def update_party(party_id, name, phone, gstin, credit_days, opening_bal, as_on_date):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE parties 
            SET party_name = :name, phone = :phone, gstin = :gstin, 
                credit_period_days = :credit_days, opening_balance = :opening_bal, as_on_date = :as_on_date
            WHERE party_id = :party_id
        """), {
            "name": name, "phone": phone, "gstin": gstin, 
            "credit_days": credit_days, "opening_bal": opening_bal, 
            "as_on_date": as_on_date, "party_id": party_id
        })

def delete_party(party_id):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM purchase_invoices WHERE party_id = :party_id"), {"party_id": party_id})
        conn.execute(text("DELETE FROM distributor_payments WHERE party_id = :party_id"), {"party_id": party_id})
        conn.execute(text("DELETE FROM parties WHERE party_id = :party_id"), {"party_id": party_id})

def bulk_save_parties(df_parties):
    engine = get_engine()
    df_parties.columns = [str(c).strip().lower().replace(" ", "_") for c in df_parties.columns]
    success_count = 0
    errors = []
    
    with engine.begin() as conn:
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
                as_on_date = parse_date(row.get('as_on_date'))
                
                conn.execute(text("""
                    INSERT INTO parties (party_name, phone, gstin, credit_period_days, opening_balance, as_on_date, created_at)
                    VALUES (:name, :phone, :gstin, :credit_days, :opening_bal, :as_on_date, :created_at)
                    ON CONFLICT (party_name) DO UPDATE SET
                    phone = EXCLUDED.phone,
                    gstin = EXCLUDED.gstin,
                    credit_period_days = EXCLUDED.credit_period_days,
                    opening_balance = EXCLUDED.opening_balance,
                    as_on_date = EXCLUDED.as_on_date
                """), {
                    "name": name, "phone": phone, "gstin": gstin, "credit_days": credit_days,
                    "opening_bal": opening_bal, "as_on_date": as_on_date, 
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                success_count += 1
            except Exception as e:
                errors.append(f"Row {idx+2}: {e}")
    return success_count, errors

def save_purchase_invoice(party_id, inv_no, inv_date, credit_days, amount, created_date):
    inv_dt = datetime.strptime(inv_date, "%Y-%m-%d")
    due_dt = inv_dt + timedelta(days=credit_days)
    due_date_str = due_dt.strftime("%Y-%m-%d")

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO purchase_invoices (party_id, invoice_number, invoice_date, due_date, bill_amount, status, created_at)
            VALUES (:party_id, :inv_no, :inv_date, :due_date, :amount, 'UNPAID', :created_date)
        """), {
            "party_id": party_id, "inv_no": inv_no, "inv_date": inv_date,
            "due_date": due_date_str, "amount": amount, "created_date": created_date
        })

def bulk_save_purchase_invoices(df_invoices):
    engine = get_engine()
    df_invoices.columns = [str(c).strip().lower().replace(" ", "_") for c in df_invoices.columns]
    success_count = 0
    errors = []
    
    with engine.begin() as conn:
        for idx, row in df_invoices.iterrows():
            try:
                party_name = str(row.get('party_name', '')).strip().title()
                inv_no = str(row.get('invoice_number', '')).strip()
                inv_date = parse_date(row.get('invoice_date'))
                amount = safe_float(row.get('bill_amount'), 0.0)
                
                if not party_name or party_name == "Nan" or not inv_no or amount <= 0:
                    continue
                
                res = conn.execute(text("SELECT party_id, credit_period_days FROM parties WHERE party_name = :p_name"), {"p_name": party_name}).fetchone()
                
                if res:
                    p_id, credit_days = res[0], res[1]
                    inv_dt = datetime.strptime(inv_date, "%Y-%m-%d")
                    due_dt = inv_dt + timedelta(days=int(credit_days))
                    due_date_str = due_dt.strftime("%Y-%m-%d")
                    
                    conn.execute(text("""
                        INSERT INTO purchase_invoices (party_id, invoice_number, invoice_date, due_date, bill_amount, status, created_at)
                        VALUES (:p_id, :inv_no, :inv_date, :due_date, :amount, 'UNPAID', :created_at)
                    """), {
                        "p_id": p_id, "inv_no": inv_no, "inv_date": inv_date,
                        "due_date": due_date_str, "amount": amount,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    success_count += 1
                else:
                    errors.append(f"Row {idx+2}: Party '{party_name}' not found in Master List.")
            except Exception as e:
                errors.append(f"Row {idx+2}: {e}")
    return success_count, errors

def get_purchase_invoices_df() -> pd.DataFrame:
    engine = get_engine()
    query = """
        SELECT i.invoice_id, p.party_id, p.party_name, i.invoice_number, i.invoice_date, i.due_date, i.bill_amount, i.status
        FROM purchase_invoices i
        JOIN parties p ON i.party_id = p.party_id
        ORDER BY i.due_date ASC
    """
    try:
        df = pd.read_sql(query, engine)
    except Exception:
        df = pd.DataFrame()
    return df

def record_distributor_payment(party_id, invoice_ids_to_clear, payment_amount, payment_mode, payment_date, notes, recorded_by):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO distributor_payments (party_id, amount_paid, payment_mode, payment_date, notes, recorded_by, timestamp)
            VALUES (:party_id, :amount_paid, :payment_mode, :payment_date, :notes, :recorded_by, :timestamp)
        """), {
            "party_id": party_id, "amount_paid": payment_amount, "payment_mode": payment_mode,
            "payment_date": payment_date, "notes": notes, "recorded_by": recorded_by,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
        if invoice_ids_to_clear:
            conn.execute(
                text("UPDATE purchase_invoices SET status = 'PAID' WHERE invoice_id = ANY(:inv_ids)"),
                {"inv_ids": invoice_ids_to_clear}
            )

def delete_distributor_payment(payment_id):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM distributor_payments WHERE payment_id = :payment_id"), {"payment_id": payment_id})

def get_distributor_payments_df() -> pd.DataFrame:
    engine = get_engine()
    try:
        df = pd.read_sql("""
            SELECT dp.payment_id, dp.party_id, p.party_name, dp.amount_paid, dp.payment_mode, dp.payment_date, dp.notes, dp.recorded_by, dp.timestamp
            FROM distributor_payments dp JOIN parties p ON dp.party_id = p.party_id
            ORDER BY dp.payment_id DESC
        """, engine)
    except Exception:
        df = pd.DataFrame()
    return df

def get_party_dues_summary() -> pd.DataFrame:
    parties_df = get_parties_df()
    if parties_df.empty: return pd.DataFrame()
    invoices_df = get_purchase_invoices_df()
    payments_df = get_distributor_payments_df()
    summary_list = []
    today = datetime.now().date()

    for _, party in parties_df.iterrows():
        p_id, p_name = party["party_id"], party["party_name"]
        opening_bal, as_on = party["opening_balance"], party["as_on_date"]
        
        total_bills = 0.0
        earliest_due = None
        if not invoices_df.empty:
            party_invs = invoices_df[invoices_df["party_id"] == p_id]
            if not party_invs.empty:
                total_bills = party_invs["bill_amount"].sum()
                unpaid_party_invs = party_invs[party_invs["status"] == "UNPAID"]
                if not unpaid_party_invs.empty:
                    earliest_due = unpaid_party_invs["due_date"].min()

        total_payments = 0.0
        if not payments_df.empty and "party_id" in payments_df.columns:
            party_pays = payments_df[payments_df["party_id"] == p_id]
            if not party_pays.empty:
                total_payments = party_pays["amount_paid"].sum()

        total_due = opening_bal + total_bills - total_payments
        
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
            "party_name": p_name, 
            "opening_balance": opening_bal, 
            "opening_as_on": as_on,
            "total_bills": total_bills,
            "total_payments": total_payments,
            "total_due_amount": total_due,
            "earliest_due_date": earliest_due if earliest_due else "Opening Only",
            "Payment_Urgency": urgency
        })
    return pd.DataFrame(summary_list).sort_values(by="total_due_amount", ascending=False)

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
        response = client.models.generate_content(model='gemini-2.5-flash', contents=[image, prompt])
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
        response = client.models.generate_content(model='gemini-2.5-flash', contents=[image, prompt])
        import json
        text_resp = response.text.strip()
        if text_resp.startswith("```json"): text_resp = text_resp[7:-3].strip()
        elif text_resp.startswith("```"): text_resp = text_resp[3:-3].strip()
        return json.loads(text_resp)
    except Exception as e:
        return {"error": str(e)}
