# app_v2.py
import streamlit as st

st.set_page_config(page_title="Jeeva Medical Store V2 (Cloud)", page_icon="💊", layout="wide")

try:
    from datetime import datetime, date
    import pandas as pd
    import io
    from database_v2 import (
        test_database_connection, init_clean_database, get_parties_df, save_party, update_party, delete_party,
        save_purchase_invoice, delete_purchase_invoice, get_purchase_invoices_df, get_party_dues_summary,
        record_distributor_payment, delete_distributor_payment, get_distributor_payments_df,
        bulk_save_parties, bulk_save_purchase_invoices, safe_float
    )
except Exception as e:
    st.error(f"🚨 **Startup Import Error:** {e}")
    st.stop()

with st.spinner("Connecting securely..."):
    conn_ok, conn_msg = test_database_connection()
    if not conn_ok:
        st.error(f"❌ **Database Connection Error:** {conn_msg}")
        st.stop()
    else:
        init_clean_database()

USERS = {"admin": {"pin": "1234", "role": "Owner"}, "staff1": {"pin": "1111", "role": "Counter Staff"}}

if "logged_in_user" not in st.session_state: st.session_state.logged_in_user = None
if "reset_counter" not in st.session_state: st.session_state.reset_counter = 0

if not st.session_state.logged_in_user:
    st.title("🔐 Jeeva Medical Store - Secure Portal")
    col1, col2 = st.columns(2)
    with col1:
        username = st.selectbox("Select User", list(USERS.keys()))
        pin = st.text_input("Enter PIN", type="password")
        if st.button("Login", type="primary"):
            if USERS[username]["pin"] == pin:
                st.session_state.logged_in_user = username
                st.rerun()
            else: st.error("Invalid PIN")
    st.stop()

current_user = st.session_state.logged_in_user

with st.sidebar:
    st.markdown(f"### 👤 {current_user.upper()}")
    st.success("✅ Supabase Cloud Connected (High Speed)")
    st.markdown("---")
    menu_choice = st.radio("Select Module", ["📊 Dashboard & Market Dues", "📥 Add Purchase Bills", "📋 Party Master", "💸 Payments"], label_visibility="collapsed")
    st.markdown("---")
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in_user = None
        st.rerun()

rc = st.session_state.reset_counter

# --- MODULE 1: DASHBOARD ---
if menu_choice == "📊 Dashboard & Market Dues":
    st.markdown("### 📊 Market Outstandings & Payment Reminders")
    df_dues = get_party_dues_summary()
    if not df_dues.empty:
        st.metric("Total Market Dues Payable", f"₹{df_dues['total_due_amount'].sum():,.2f}")
        st.divider()
        search_party = st.text_input("🔍 Search Party Name:")
        filtered_dues = df_dues[df_dues["party_name"].str.contains(search_party, case=False, na=False)] if search_party else df_dues

        for _, party_row in filtered_dues.iterrows():
            with st.expander(f"🏢 **{party_row['party_name']}** | Net Due: **₹{party_row['total_due_amount']:,.2f}**"):
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"🔹 **Opening:** ₹{party_row['opening_balance']:,.2f}")
                c2.markdown(f"📦 **Bills:** ₹{party_row['total_bills']:,.2f}")
                c3.markdown(f"💸 **Paid:** ₹{party_row['total_payments']:,.2f}")
    else:
        st.info("No parties or purchase dues found yet.")

# --- MODULE 2: ADD PURCHASE BILLS ---
elif menu_choice == "📥 Add Purchase Bills":
    st.markdown("### 📥 Add Purchase Bills & Manage Entries")
    bill_tab_excel, bill_tab_manual, bill_tab_manage = st.tabs(["📊 Bulk Excel Upload", "✍️ Manual Entry", "🗑️ Manage & Delete Bills"])
    
    with bill_tab_excel:
        uploaded_inv_file = st.file_uploader("Upload Excel Bills", type=["xlsx", "csv"], key=f"excel_bill_{rc}")
        if uploaded_inv_file:
            df_inv = pd.read_csv(uploaded_inv_file) if uploaded_inv_file.name.endswith('.csv') else pd.read_excel(uploaded_inv_file, engine='openpyxl')
            df_inv.columns = [str(c).strip().lower().replace(" ", "_") for c in df_inv.columns]
            
            df_master = get_parties_df()
            existing_parties = set(df_master["party_name"].str.strip().str.title().tolist()) if not df_master.empty else set()
            
            def validate_row(row):
                p_name = str(row.get('party_name', '')).strip().title()
                if not p_name or p_name == "Nan": return "❌ Missing Party"
                if p_name in existing_parties: return "✅ Valid"
                return "❌ Party Not Found"
                
            df_inv["Validation_Status"] = df_inv.apply(validate_row, axis=1)
            
            def style_status(val):
                return "background-color: #e2efda; color: #375623;" if "✅" in str(val) else "background-color: #ffcccc; color: #c00000;"
                
            st.markdown("#### Step 1: Review Name Matches")
            st.dataframe(df_inv.style.map(style_status, subset=['Validation_Status']), use_container_width=True)
            
            invalid_count = (df_inv["Validation_Status"] != "✅ Valid").sum()
            if invalid_count > 0:
                st.error(f"⚠️ Import Blocked! Found {invalid_count} mismatched or invalid rows. You must fix these in your file or add the missing parties first. No data has been saved.")
            else:
                st.success("✨ All rows valid! Ready for import.")
                if st.button("🚀 Step 2: Confirm & Import All"):
                    count, errors = bulk_save_purchase_invoices(df_inv)
                    if errors:
                        for err in errors: st.error(err)
                    elif count > 0:
                        st.success(f"✅ Imported all {count} bills successfully!")
                        st.session_state.reset_counter += 1
                        st.rerun()

    with bill_tab_manual:
        df_parties_manual = get_parties_df()
        if not df_parties_manual.empty:
            with st.form("manual_bill_form", clear_on_submit=True):
                m_party = st.selectbox("Distributor *", df_parties_manual["party_name"].tolist())
                m_inv_no = st.text_input("Invoice Number *")
                m_inv_date = st.date_input("Invoice Date", value=date.today())
                m_amt = st.number_input("Amount (₹) *", min_value=0.0)
                if st.form_submit_button("💾 Save Bill") and m_inv_no and m_amt > 0:
                    p_row = df_parties_manual[df_parties_manual["party_name"] == m_party].iloc[0]
                    save_purchase_invoice(int(p_row["party_id"]), m_inv_no, m_inv_date.strftime("%Y-%m-%d"), int(p_row["credit_period_days"]), m_amt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    st.success("✅ Saved manually!")
                    st.session_state.reset_counter += 1
                    st.rerun()

    with bill_tab_manage:
        df_all_invs = get_purchase_invoices_df()
        if not df_all_invs.empty:
            st.markdown("#### Filter by Date to Find and Delete Entries")
            filter_date = st.date_input("Select Invoice Date", value=date.today(), key=f"del_date_{rc}")
            filtered_invs = df_all_invs[df_all_invs["invoice_date"] == filter_date.strftime("%Y-%m-%d")]
            
            if not filtered_invs.empty:
                st.dataframe(filtered_invs[["invoice_id", "party_name", "invoice_number", "bill_amount", "status"]], use_container_width=True, hide_index=True)
                
                inv_to_delete = st.selectbox(
                    "Select Invoice to Delete", 
                    filtered_invs.apply(lambda r: f"ID: {r['invoice_id']} | {r['party_name']} | Bill: {r['invoice_number']} | ₹{r['bill_amount']}", axis=1).tolist()
                )
                
                if st.button("🗑️ Permanently Delete Selected Bill", type="primary"):
                    inv_id_val = int(inv_to_delete.split("|")[0].replace("ID:", "").strip())
                    delete_purchase_invoice(inv_id_val)
                    st.success("✅ Bill deleted successfully! Market dues updated.")
                    st.session_state.reset_counter += 1
                    st.rerun()
            else:
                st.info(f"No bills found for {filter_date.strftime('%Y-%m-%d')}.")
        else:
            st.info("No purchase bills have been recorded yet.")

# --- MODULE 3: PARTY MASTER ---
elif menu_choice == "📋 Party Master":
    st.markdown("### 📋 Purchase Parties Master Setup")
    add_tab, bulk_party_tab = st.tabs(["➕ Add Single", "📤 Bulk Upload"])
    
    with add_tab:
        with st.form("party_form", clear_on_submit=True):
            p_name = st.text_input("Party Name *")
            c1, c2 = st.columns(2)
            p_credit = c1.number_input("Credit Period (Days)", min_value=0, value=15)
            p_opening = c2.number_input("Opening Balance (₹)", min_value=0.0)
            if st.form_submit_button("💾 Save Party") and p_name:
                save_party(p_name.strip().title(), "", "", p_credit, p_opening, date.today().strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                st.success("✅ Saved!")
                st.session_state.reset_counter += 1
                st.rerun()
                
    with bulk_party_tab:
        uploaded_party_file = st.file_uploader("Upload Party Excel", type=["xlsx", "csv"], key=f"party_upl_{rc}")
        if uploaded_party_file:
            df_party_upload = pd.read_csv(uploaded_party_file) if uploaded_party_file.name.endswith('.csv') else pd.read_excel(uploaded_party_file, engine='openpyxl')
            if st.button("🚀 Import Parties (All or Nothing)"):
                count, errors = bulk_save_parties(df_party_upload)
                if errors:
                    for err in errors: st.error(err)
                elif count > 0:
                    st.success(f"Imported all {count} parties!")
                    st.session_state.reset_counter += 1
                    st.rerun()

# --- MODULE 4: PAYMENTS ---
elif menu_choice == "💸 Payments":
    st.markdown("### 💸 Record Daily Distributor Payment")
    df_parties_pay = get_parties_df()
    if not df_parties_pay.empty:
        pay_party = st.selectbox("Select Distributor to Pay", df_parties_pay["party_name"].tolist())
        party_id = int(df_parties_pay[df_parties_pay["party_name"] == pay_party].iloc[0]["party_id"])

        with st.form("dash_payment_form", clear_on_submit=True):
            pay_amount = st.number_input("Amount Paid (₹) *", min_value=0.0, step=100.0)
            pay_mode = st.selectbox("Mode", ["CASH", "UPI", "BANK_TRANSFER", "CHEQUE"])
            if st.form_submit_button("✅ Record Payment") and pay_amount > 0:
                record_distributor_payment(party_id, [], pay_amount, pay_mode, date.today().strftime("%Y-%m-%d"), "", current_user)
                st.success("✅ Payment saved!")
                st.session_state.reset_counter += 1
                st.rerun()

        with st.expander("📜 View & Manage Payment History"):
            df_payments = get_distributor_payments_df()
            if not df_payments.empty:
                st.dataframe(df_payments[["payment_id", "party_name", "amount_paid", "payment_mode", "payment_date"]], hide_index=True)
                sel_pay = st.selectbox("Select Payment ID to Remove", df_payments["payment_id"].tolist())
                if st.button("🗑️ Delete Payment", type="primary"):
                    delete_distributor_payment(sel_pay)
                    st.success("✅ Deleted!")
                    st.session_state.reset_counter += 1
                    st.rerun()
