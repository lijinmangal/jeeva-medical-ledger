# app_v2.py
import streamlit as st

st.set_page_config(page_title="Jeeva Medical Store V2 (Cloud)", page_icon="💊", layout="wide")

try:
    from datetime import datetime, date
    import pandas as pd
    import io
    from database_v2 import (
        test_database_connection, init_clean_database, get_parties_df, save_party, update_party, delete_party,
        save_purchase_invoice, delete_multiple_purchase_invoices, get_purchase_invoices_df, get_party_dues_summary,
        record_distributor_payment, bulk_save_distributor_payments, delete_multiple_distributor_payments, get_distributor_payments_df,
        bulk_save_parties, bulk_save_purchase_invoices,
        extract_invoice_from_image, extract_payment_from_image, safe_float, safe_int
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
    st.success("✅ Supabase Cloud Connected")
    st.markdown("---")
    menu_choice = st.radio("Select Module", [
        "📊 Dashboard & Market Dues", 
        "📥 Add Purchase Bills", 
        "📋 Party Master", 
        "💸 Payments", 
        "💾 Data Exports (Excel)"
    ], label_visibility="collapsed")
    st.markdown("---")
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in_user = None
        st.rerun()

rc = st.session_state.reset_counter

# =====================================================================
# SMART FIFO LEDGER ENGINE: Auto-deducts payments from oldest bills
# =====================================================================
def get_dynamic_active_bills():
    df_parties = get_parties_df()
    df_invoices = get_purchase_invoices_df()
    df_payments = get_distributor_payments_df()
    
    active_bills_list = []
    old_dues_list = []
    
    if df_parties.empty: return pd.DataFrame(), pd.DataFrame()
        
    for _, r in df_parties.iterrows():
        p_name = r['party_name']
        p_id = r['party_id']
        opening_bal = safe_float(r['opening_balance'])
        
        # Calculate total payments made to this specific party
        total_pays = 0.0
        if not df_payments.empty and 'party_id' in df_payments.columns:
            party_pays = df_payments[df_payments['party_id'] == p_id]
            if not party_pays.empty: total_pays = party_pays['amount_paid'].sum()
            
        pool = total_pays
        
        # 1. Deduct from Opening Balance First
        if pool >= opening_bal:
            pool -= opening_bal
            rem_old = 0.0
        else:
            rem_old = opening_bal - pool
            pool = 0.0
            
        if rem_old > 0:
            old_dues_list.append({"party_id": p_id, "Party Name": p_name, "Old Dues (₹)": rem_old, "As On Date": r['as_on_date']})
            
        # 2. Deduct remaining payment pool from oldest bills (FIFO)
        if not df_invoices.empty and 'party_id' in df_invoices.columns:
            p_invs = df_invoices[df_invoices['party_id'] == p_id].sort_values('invoice_date')
            for _, bill in p_invs.iterrows():
                b_amt = safe_float(bill['bill_amount'])
                if pool >= b_amt:
                    pool -= b_amt
                    rem_b = 0.0
                else:
                    rem_b = b_amt - pool
                    pool = 0.0
                    
                if rem_b > 0:
                    active_bills_list.append({
                        "invoice_id": bill['invoice_id'],
                        "party_id": p_id,
                        "party_name": p_name,
                        "invoice_number": bill['invoice_number'],
                        "invoice_date": bill['invoice_date'],
                        "due_date": bill['due_date'],
                        "bill_amount": rem_b, # Dynamic remaining amount
                    })
                    
    return pd.DataFrame(active_bills_list), pd.DataFrame(old_dues_list)

df_active_bills, df_old_dues = get_dynamic_active_bills()
# =====================================================================

# --- MODULE 1: DASHBOARD ---
if menu_choice == "📊 Dashboard & Market Dues":
    df_dues = get_party_dues_summary()

    if not df_dues.empty:
        total_net_dues = df_dues['total_due_amount'].sum()
        total_old_dues = df_old_dues['Old Dues (₹)'].sum() if not df_old_dues.empty else 0.0
        
        # 1. TOTAL OUTSTANDING (Centered Box)
        st.markdown(f"""
        <div style="text-align:center; padding:20px; border:2px solid #4a90e2; border-radius:10px; background-color:#f8fbff; margin-bottom:25px;">
            <h3 style="margin:0; color:#333; font-family:sans-serif;">Total Outstanding</h3>
            <p style="margin:0; color:#666; font-size:14px; margin-bottom:10px;">(opening dues + total bills - payment done)</p>
            <h1 style="margin:0; color:#0056b3; font-size:46px;">₹ {total_net_dues:,.2f}</h1>
        </div>
        """, unsafe_allow_html=True)
        
        due_today = pd.DataFrame()
        due_tomorrow = pd.DataFrame()
        due_overdue = pd.DataFrame()
        due_upcoming = pd.DataFrame()
        
        if not df_active_bills.empty:
            today = date.today()
            df_active_bills["days_left"] = df_active_bills["due_date"].apply(lambda d: (datetime.strptime(str(d), "%Y-%m-%d").date() - today).days)
            
            due_today = df_active_bills[df_active_bills["days_left"] == 0].copy()
            due_tomorrow = df_active_bills[df_active_bills["days_left"] == 1].copy()
            due_overdue = df_active_bills[df_active_bills["days_left"] < 0].copy()
            due_upcoming = df_active_bills[(df_active_bills["days_left"] > 1) & (df_active_bills["days_left"] <= 7)].copy()

        def display_due_tab(df_bills, label):
            if df_bills.empty:
                st.success(f"No {label} bills found!")
                return
            party_totals = df_bills.groupby("party_name")["bill_amount"].sum().reset_index()
            party_totals.rename(columns={"party_name": "Party Name", "bill_amount": "Total Due (₹)"}, inplace=True)
            
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown("##### Party-wise Total")
                st.dataframe(party_totals, hide_index=True, use_container_width=True)
            with col2:
                st.markdown("##### Detailed Bills List")
                display_df = df_bills[["party_name", "days_left", "invoice_date", "due_date", "bill_amount"]].copy()
                display_df.rename(columns={
                    "party_name": "Party Name", "days_left": "Days Left", 
                    "invoice_date": "Invoice Date", "due_date": "Due Date", "bill_amount": "Bill Total (₹)"
                }, inplace=True)
                st.dataframe(display_df, hide_index=True, use_container_width=True)

        # 2. CLICKABLE TABS (Dues Timeline)
        tab_old, tab_od, tab_tod, tab_tom, tab_upc = st.tabs([
            f"🟣 Old Dues (₹{total_old_dues:,.0f})",
            f"🔴 Overdue (₹{due_overdue['bill_amount'].sum() if not due_overdue.empty else 0:,.0f})",
            f"🟠 Today's Due (₹{due_today['bill_amount'].sum() if not due_today.empty else 0:,.0f})",
            f"🟡 Tomorrow's Due (₹{due_tomorrow['bill_amount'].sum() if not due_tomorrow.empty else 0:,.0f})",
            f"🟢 Upcoming 7 Days (₹{due_upcoming['bill_amount'].sum() if not due_upcoming.empty else 0:,.0f})"
        ])
        
        with tab_old:
            if not df_old_dues.empty:
                st.markdown("##### Party-wise Old Opening Dues")
                st.dataframe(df_old_dues[["Party Name", "Old Dues (₹)", "As On Date"]], hide_index=True, use_container_width=True)
            else:
                st.success("No pending old opening dues!")
                
        with tab_od: display_due_tab(due_overdue, "overdue")
        with tab_tod: display_due_tab(due_today, "today's")
        with tab_tom: display_due_tab(due_tomorrow, "tomorrow's")
        with tab_upc: display_due_tab(due_upcoming, "upcoming")
        
        st.divider()
        
        # 3. INDIVIDUAL PARTY LEDGERS
        st.markdown("#### 🏢 Individual Party Ledgers")
        search_party = st.text_input("🔍 Search Party Name to view specific ledger:")
        filtered_dues = df_dues[df_dues["party_name"].str.contains(search_party, case=False, na=False)] if search_party else df_dues

        for _, party_row in filtered_dues.iterrows():
            with st.expander(f"**{party_row['party_name']}** | Net Due: **₹{party_row['total_due_amount']:,.2f}** — {party_row['Payment_Urgency']}"):
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"🔹 **Opening:** ₹{party_row['opening_balance']:,.2f} *(As on {party_row['opening_as_on']})*")
                c2.markdown(f"📦 **Bills:** ₹{party_row['total_bills']:,.2f}")
                c3.markdown(f"💸 **Paid:** ₹{party_row['total_payments']:,.2f}")
                
                if not df_active_bills.empty:
                    party_bills = df_active_bills[df_active_bills["party_name"] == party_row['party_name']]
                    if not party_bills.empty:
                        st.dataframe(party_bills[["invoice_number", "invoice_date", "due_date", "bill_amount"]], hide_index=True, use_container_width=True)
    else:
        st.info("No parties or purchase dues found yet.")

# --- MODULE 2: ADD PURCHASE BILLS ---
elif menu_choice == "📥 Add Purchase Bills":
    st.markdown("### 📥 Add Purchase Bills & Manage Entries")
    bill_tab_excel, bill_tab_manual, bill_tab_ai, bill_tab_manage = st.tabs(["📊 Bulk Excel Upload", "✍️ Manual Entry", "🤖 AI Image Scan", "🗑️ Manage & Delete Bills"])
    
    with bill_tab_excel:
        uploaded_inv_file = st.file_uploader("Upload Excel Bills", type=["xlsx", "csv"], key=f"excel_bill_{rc}")
        if uploaded_inv_file:
            df_inv = pd.read_csv(uploaded_inv_file) if uploaded_inv_file.name.endswith('.csv') else pd.read_excel(uploaded_inv_file, engine='openpyxl')
            df_inv.columns = [str(c).strip().lower().replace(" ", "_") for c in df_inv.columns]
            df_master = get_parties_df()
            existing_parties = set(df_master["party_name"].str.strip().str.title().tolist()) if not df_master.empty else set()
            
            df_inv["Validation_Status"] = df_inv.apply(lambda r: "✅ Valid" if str(r.get('party_name', '')).strip().title() in existing_parties else "❌ Party Not Found", axis=1)
            st.dataframe(df_inv.style.map(lambda v: "background-color: #e2efda; color: #375623;" if "✅" in str(v) else "background-color: #ffcccc; color: #c00000;", subset=['Validation_Status']), use_container_width=True)
            
            if (df_inv["Validation_Status"] != "✅ Valid").sum() > 0:
                st.error("⚠️ Import Blocked! Fix mismatched rows in your file or add the missing parties first.")
            else:
                if st.button("🚀 Confirm & Import All"):
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
                m_inv_date = st.date_input("Invoice Date (As on Date) *", value=date.today())
                m_amt = st.number_input("Amount (₹) *", min_value=0.0)
                if st.form_submit_button("💾 Save Bill") and m_inv_no and m_amt > 0:
                    p_row = df_parties_manual[df_parties_manual["party_name"] == m_party].iloc[0]
                    save_purchase_invoice(int(p_row["party_id"]), m_inv_no, m_inv_date.strftime("%Y-%m-%d"), int(p_row["credit_period_days"]), m_amt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    st.success("✅ Saved manually!")
                    st.session_state.reset_counter += 1
                    st.rerun()
                    
    with bill_tab_ai:
        uploaded_bill_img = st.file_uploader("Upload Purchase Bill Image", type=["png", "jpg", "jpeg"], key=f"ai_bill_{rc}")
        if uploaded_bill_img:
            st.image(uploaded_bill_img, width=220)
            if st.button("🔍 Extract & Save"):
                with st.spinner("Scanning..."):
                    extracted = extract_invoice_from_image(uploaded_bill_img)
                    if "error" in extracted: st.error(extracted['error'])
                    else:
                        df_parties = get_parties_df()
                        matched_party = df_parties[df_parties["party_name"].str.contains(extracted.get("party_name", ""), case=False, na=False)]
                        if not matched_party.empty:
                            save_purchase_invoice(int(matched_party.iloc[0]["party_id"]), str(extracted.get("invoice_number", "INV-AI")), str(extracted.get("invoice_date", date.today().strftime("%Y-%m-%d"))), int(matched_party.iloc[0]["credit_period_days"]), float(extracted.get("bill_amount", 0.0)), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            st.success("✅ Bill saved!")
                            st.session_state.reset_counter += 1
                            st.rerun()
                        else: st.error("Party not found in Master List.")

    with bill_tab_manage:
        df_all_invs = get_purchase_invoices_df() # Uses raw DB for accurate original deletions
        if not df_all_invs.empty:
            filter_date = st.date_input("Select Invoice Date to Filter", value=date.today(), key=f"del_date_{rc}")
            filtered_invs = df_all_invs[df_all_invs["invoice_date"] == filter_date.strftime("%Y-%m-%d")]
            if not filtered_invs.empty:
                st.dataframe(filtered_invs[["invoice_id", "party_name", "invoice_number", "bill_amount", "status"]], use_container_width=True, hide_index=True)
                options = filtered_invs.apply(lambda r: f"ID: {r['invoice_id']} | {r['party_name']} | Bill: {r['invoice_number']} | ₹{r['bill_amount']}", axis=1).tolist()
                invs_to_delete = st.multiselect("Select Invoice(s) to Delete", options, key=f"multi_del_sel_{rc}")
                if st.button("🗑️ Permanently Delete Selected Bills", type="primary"):
                    if invs_to_delete:
                        inv_ids_val = [int(item.split("|")[0].replace("ID:", "").strip()) for item in invs_to_delete]
                        delete_multiple_purchase_invoices(inv_ids_val)
                        st.success(f"✅ {len(inv_ids_val)} Bill(s) deleted successfully!")
                        st.session_state.reset_counter += 1
                        st.rerun()
                    else:
                        st.error("Please select at least one bill from the dropdown to delete.")
            else: st.info(f"No bills found for {filter_date.strftime('%Y-%m-%d')}.")

# --- MODULE 3: PARTY MASTER ---
elif menu_choice == "📋 Party Master":
    st.markdown("### 📋 Purchase Parties Master Setup")
    add_tab, bulk_party_tab, edit_del_tab = st.tabs(["➕ Add Single", "📤 Bulk Upload", "🛠️ Edit / Delete"])
    
    with add_tab:
        with st.form("party_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            p_name = c1.text_input("Party Name *")
            p_phone = c2.text_input("Phone Number")
            p_gstin = c3.text_input("GSTIN Number")
            c4, c5, c6 = st.columns(3)
            p_credit = c4.number_input("Credit Period (Days)", min_value=0, value=15)
            p_opening = c5.number_input("Opening Balance (₹)", min_value=0.0)
            p_as_on_date = c6.date_input("Opening Balance 'As on Date'", value=date.today())
            if st.form_submit_button("💾 Save Party") and p_name:
                save_party(p_name.strip().title(), p_phone.strip(), p_gstin.strip().upper(), p_credit, p_opening, p_as_on_date.strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
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

    with edit_del_tab:
        df_parties_mgmt = get_parties_df()
        if not df_parties_mgmt.empty:
            selected_party_name = st.selectbox("Select Party to Edit or Delete", df_parties_mgmt["party_name"].tolist())
            party_record = df_parties_mgmt[df_parties_mgmt["party_name"] == selected_party_name].iloc[0]
            party_id = int(party_record["party_id"])
            
            sub_edit_tab, sub_del_tab = st.tabs(["✏️ Edit Party Details", "🗑️ Delete Party"])
            with sub_edit_tab:
                with st.form(f"edit_party_form_{party_id}"):
                    e_name = st.text_input("Party Name", value=str(party_record.get("party_name", "")))
                    e_phone = st.text_input("Phone Number", value=str(party_record.get("phone", "")) if pd.notna(party_record.get("phone")) else "")
                    e_gstin = st.text_input("GSTIN Number", value=str(party_record.get("gstin", "")) if pd.notna(party_record.get("gstin")) else "")
                    e_credit = st.number_input("Credit Period (Days)", min_value=0, value=safe_int(party_record.get("credit_period_days", 15), 15))
                    e_opening = st.number_input("Opening Balance (₹)", min_value=0.0, value=max(0.0, safe_float(party_record.get("opening_balance", 0.0), 0.0)))
                    e_date = st.date_input("As on Date", value=datetime.strptime(str(party_record.get("as_on_date", date.today().strftime("%Y-%m-%d"))), "%Y-%m-%d"))
                    
                    if st.form_submit_button("💾 Save Changes"):
                        update_party(party_id, e_name.strip().title(), e_phone.strip(), e_gstin.strip().upper(), e_credit, e_opening, e_date.strftime("%Y-%m-%d"))
                        st.success("✅ Updated!")
                        st.session_state.reset_counter += 1
                        st.rerun()
            with sub_del_tab:
                st.warning(f"⚠️ Deleting {selected_party_name} will remove all associated purchase and payment records.")
                confirm_del = st.checkbox("I confirm I want to delete", key="confirm_del")
                if st.button("🗑️ Permanently Delete Party", type="primary") and confirm_del:
                    delete_party(party_id)
                    st.success("✅ Deleted.")
                    st.session_state.reset_counter += 1
                    st.rerun()

# --- MODULE 4: PAYMENTS ---
elif menu_choice == "💸 Payments":
    st.markdown("### 💸 Record & Manage Distributor Payments")
    pay_tab_record, pay_tab_bulk, pay_tab_manage = st.tabs(["💸 Record Single", "📊 Bulk Upload", "🗑️ Manage & Delete"])
    
    with pay_tab_record:
        df_parties_pay = get_parties_df()
        if not df_parties_pay.empty:
            pay_party = st.selectbox("Select Distributor to Pay", df_parties_pay["party_name"].tolist())
            party_id = int(df_parties_pay[df_parties_pay["party_name"] == pay_party].iloc[0]["party_id"])

            unpaid_party_bills = pd.DataFrame()
            if not df_active_bills.empty:
                unpaid_party_bills = df_active_bills[df_active_bills["party_id"] == party_id]

            selected_invoice_ids = []
            if not unpaid_party_bills.empty:
                with st.expander(f"📦 Select Active Bills to Clear for {pay_party} (Optional)"):
                    for _, bill in unpaid_party_bills.iterrows():
                        checked = st.checkbox(
                            f"Invoice: **{bill['invoice_number']}** | Date: {bill['invoice_date']} | Due: {bill['due_date']} | Remaining Amt: **₹{bill['bill_amount']:,.2f}**", 
                            key=f"dash_inv_chk_{bill['invoice_id']}_{rc}"
                        )
                        if checked:
                            selected_invoice_ids.append(int(bill['invoice_id']))
            else:
                st.info(f"ℹ️ No active unpaid invoices found for {pay_party}. Payment will be recorded as an advance adjustment.")

            with st.form("dash_payment_form", clear_on_submit=True):
                pay_amount = st.number_input("Amount Paid (₹) *", min_value=0.0, step=100.0)
                pay_mode = st.selectbox("Mode", ["CASH", "UPI", "BANK_TRANSFER", "CHEQUE"])
                pay_date = st.date_input("Payment Date *", value=date.today())
                pay_notes = st.text_input("Payment Notes / Reference No. (Optional)")
                
                if st.form_submit_button("✅ Record Payment") and pay_amount > 0:
                    record_distributor_payment(party_id, selected_invoice_ids, pay_amount, pay_mode, pay_date.strftime("%Y-%m-%d"), pay_notes.strip(), current_user)
                    st.success("✅ Payment saved! Active bills reduced automatically.")
                    st.session_state.reset_counter += 1
                    st.rerun()
        else:
            st.warning("Please register at least one purchase party first.")

    with pay_tab_bulk:
        st.info("💡 **Format Required:** Your Excel file must contain these exact column names: `party_name`, `amount_paid`, `payment_date`, `payment_mode`, `notes`")
        
        template_df = pd.DataFrame({
            "party_name": ["Example Pharma", "Health Care Distributors"],
            "amount_paid": [5000.0, 12500.0],
            "payment_date": [date.today().strftime("%Y-%m-%d"), date.today().strftime("%Y-%m-%d")],
            "payment_mode": ["CASH", "UPI"],
            "notes": ["Advance", "Bill 1234"]
        })
        t_io = io.BytesIO()
        with pd.ExcelWriter(t_io, engine='openpyxl') as w: template_df.to_excel(w, index=False)
        st.download_button("📥 Download Excel Template", t_io.getvalue(), file_name="payment_import_template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        
        uploaded_pay_file = st.file_uploader("Upload Payment Excel/CSV", type=["xlsx", "csv"], key=f"pay_upl_{rc}")
        if uploaded_pay_file:
            df_pay_upl = pd.read_csv(uploaded_pay_file) if uploaded_pay_file.name.endswith('.csv') else pd.read_excel(uploaded_pay_file, engine='openpyxl')
            df_pay_upl.columns = [str(c).strip().lower().replace(" ", "_") for c in df_pay_upl.columns]
            
            required_cols = ["party_name", "amount_paid"]
            missing_cols = [c for c in required_cols if c not in df_pay_upl.columns]
            
            if missing_cols:
                st.error(f"❌ Missing required columns in your file: **{', '.join(missing_cols)}**. Please download the template above.")
            else:
                df_master = get_parties_df()
                existing_parties = set(df_master["party_name"].str.strip().str.title().tolist()) if not df_master.empty else set()
                
                df_pay_upl["Validation_Status"] = df_pay_upl.apply(lambda r: "✅ Valid" if str(r.get('party_name', '')).strip().title() in existing_parties else "❌ Party Not Found", axis=1)
                st.dataframe(df_pay_upl.style.map(lambda v: "background-color: #e2efda; color: #375623;" if "✅" in str(v) else "background-color: #ffcccc; color: #c00000;", subset=['Validation_Status']), use_container_width=True)
                
                if (df_pay_upl["Validation_Status"] != "✅ Valid").sum() > 0:
                    st.error("⚠️ Import Blocked! Fix the misspelled party names in your Excel file or add the missing parties to your Party Master first.")
                else:
                    if st.button("🚀 Confirm & Import All Payments"):
                        count, errors = bulk_save_distributor_payments(df_pay_upl)
                        if errors:
                            for err in errors: st.error(err)
                        elif count > 0:
                            st.success(f"✅ Imported all {count} payments successfully!")
                            st.session_state.reset_counter += 1
                            st.rerun()

    with pay_tab_manage:
        df_all_pays = get_distributor_payments_df()
        if not df_all_pays.empty:
            st.markdown("#### Filter by Date to Find and Delete Payments")
            filter_pay_date = st.date_input("Select Payment Date", value=date.today(), key=f"del_pay_date_{rc}")
            
            filtered_pays = df_all_pays[df_all_pays["payment_date"] == filter_pay_date.strftime("%Y-%m-%d")]
            
            if not filtered_pays.empty:
                st.dataframe(filtered_pays[["payment_id", "party_name", "amount_paid", "payment_mode", "payment_date", "notes"]], use_container_width=True, hide_index=True)
                
                options = filtered_pays.apply(lambda r: f"ID: {r['payment_id']} | {r['party_name']} | ₹{r['amount_paid']} | Mode: {r['payment_mode']}", axis=1).tolist()
                pays_to_delete = st.multiselect("Select Payment(s) to Delete", options, key=f"multi_del_pay_{rc}")
                
                if st.button("🗑️ Permanently Delete Selected Payments", type="primary"):
                    if pays_to_delete:
                        pay_ids_val = [int(item.split("|")[0].replace("ID:", "").strip()) for item in pays_to_delete]
                        delete_multiple_distributor_payments(pay_ids_val)
                        st.success(f"✅ {len(pay_ids_val)} Payment(s) deleted successfully! Market dues updated.")
                        st.session_state.reset_counter += 1
                        st.rerun()
                    else:
                        st.error("Please select at least one payment from the dropdown to delete.")
            else:
                st.info(f"No payments found for {filter_pay_date.strftime('%Y-%m-%d')}.")
        else:
            st.info("No payments have been recorded yet.")

# --- MODULE 5: DATA EXPORTS ---
elif menu_choice == "💾 Data Exports (Excel)":
    st.markdown("### 💾 Download System Data & Legacy Backup")
    if st.button("⚙️ Generate Master Legacy Backup"):
        try:
            master_output = io.BytesIO()
            with pd.ExcelWriter(master_output, engine='openpyxl') as writer:
                df_p = get_parties_df()
                df_i = get_purchase_invoices_df()
                df_pay = get_distributor_payments_df()
                if not df_p.empty: df_p.to_excel(writer, index=False, sheet_name='Parties')
                if not df_i.empty: df_i.to_excel(writer, index=False, sheet_name='Invoices')
                if not df_pay.empty: df_pay.to_excel(writer, index=False, sheet_name='Payments')
            st.download_button("📥 Download Master Backup (.xlsx)", master_output.getvalue(), file_name=f"jeeva_ledger_backup_{date.today().strftime('%Y-%m-%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
        except Exception as e: st.error(f"Error generating backup: {e}")
