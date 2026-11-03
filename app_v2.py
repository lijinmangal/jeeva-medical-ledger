# app_v2.py
import streamlit as st

# THIS MUST BE THE ABSOLUTE FIRST COMMAND to prevent blank screens
st.set_page_config(page_title="Jeeva Medical Store V2 (Cloud)", page_icon="💊", layout="wide")

try:
    from datetime import datetime, date
    import pandas as pd
    import io
    from database_v2 import (
        test_database_connection, init_clean_database, get_parties_df, save_party, update_party, delete_party,
        save_purchase_invoice, get_purchase_invoices_df, get_party_dues_summary,
        record_distributor_payment, delete_distributor_payment, get_distributor_payments_df,
        bulk_save_parties, bulk_save_purchase_invoices,
        extract_invoice_from_image, extract_payment_from_image,
        safe_float, safe_int
    )
except Exception as e:
    st.error(f"🚨 **Startup Import Error:** {e}")
    st.stop()

# --- SAFE CONNECTION & TABLE INITIALIZATION CHECK ---
with st.spinner("Connecting to Supabase Cloud Database..."):
    conn_ok, conn_msg = test_database_connection()
    if not conn_ok:
        st.error(f"❌ **Database Connection Error:** {conn_msg}")
        st.info("Check your Streamlit Secrets and ensure your password has special characters URL-encoded.")
        st.stop()
    else:
        try:
            init_clean_database()
        except Exception as e:
            st.error(f"❌ Failed to initialize database tables: {e}")
            st.stop()

USERS = {
    "admin": {"pin": "1234", "role": "Owner"},
    "staff1": {"pin": "1111", "role": "Counter Staff"},
    "accounts": {"pin": "2222", "role": "Accountant"}
}

if "logged_in_user" not in st.session_state:
    st.session_state.logged_in_user = None

if "reset_counter" not in st.session_state:
    st.session_state.reset_counter = 0

if not st.session_state.logged_in_user:
    st.title("🔐 Jeeva Medical Store - Secure Portal")
    col1, col2 = st.columns(2)
    with col1:
        username = st.selectbox("Select User", list(USERS.keys()))
        pin = st.text_input("Enter PIN (Default admin: 1234)", type="password")
        if st.button("Login", type="primary"):
            if USERS[username]["pin"] == pin:
                st.session_state.logged_in_user = username
                st.rerun()
            else:
                st.error("Invalid PIN")
    st.stop()

current_user = st.session_state.logged_in_user
user_role = USERS[current_user]["role"]

with st.sidebar:
    st.markdown("### 💊 Jeeva Medical Store")
    st.markdown(
        f"""
        <div style="background-color: #e2efda; color: #375623; padding: 6px 10px; border-radius: 8px; font-size: 13px; font-weight: bold; margin-bottom: 15px;">
            👤 {current_user.upper()} ({user_role})
        </div>
        """, 
        unsafe_allow_html=True
    )
    st.success("✅ Supabase Cloud Connected")
    
    st.markdown("---")
    st.markdown("### 📌 Navigation Ribbon")
    
    menu_choice = st.radio(
        "Select Module",
        [
            "📊 Dashboard & Market Dues",
            "📥 Add Purchase Bills & AI Pay",
            "📋 Party Master & Setup",
            "💸 Payments & Bill Clearing",
            "💾 Data Exports (Excel)"
        ],
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in_user = None
        st.rerun()

rc = st.session_state.reset_counter

# --- MODULE 1: DASHBOARD & MARKET DUES ---
if menu_choice == "📊 Dashboard & Market Dues":
    st.markdown("### 📊 Market Outstandings & Payment Reminders")
    df_dues = get_party_dues_summary()
    df_invoices = get_purchase_invoices_df()

    if not df_dues.empty:
        total_market_dues = df_dues["total_due_amount"].sum()
        st.metric("Total Market Dues Payable", f"₹{total_market_dues:,.2f}")
        st.divider()

        st.markdown("#### 🚨 Manager's Payment Reminders & Date-wise Urgency")
        if not df_invoices.empty:
            unpaid_invoices = df_invoices[df_invoices["status"] == "UNPAID"].copy()
            if not unpaid_invoices.empty:
                today = date.today()
                
                def get_days_diff(due_date_str):
                    due_dt = datetime.strptime(due_date_str, "%Y-%m-%d").date()
                    return (due_dt - today).days

                unpaid_invoices["days_left"] = unpaid_invoices["due_date"].apply(get_days_diff)

                due_today = unpaid_invoices[unpaid_invoices["days_left"] == 0]
                due_tomorrow = unpaid_invoices[unpaid_invoices["days_left"] == 1]
                due_overdue = unpaid_invoices[unpaid_invoices["days_left"] < 0]
                due_upcoming = unpaid_invoices[(unpaid_invoices["days_left"] > 1) & (unpaid_invoices["days_left"] <= 7)]

                col_r1, col_r2, col_r3, col_r4 = st.columns(4)
                with col_r1: st.error(f"🔴 **Overdue ({len(due_overdue)})**\n\nAmt: ₹{due_overdue['bill_amount'].sum():,.2f}")
                with col_r2: st.warning(f"🟠 **Due Today ({len(due_today)})**\n\nAmt: ₹{due_today['bill_amount'].sum():,.2f}")
                with col_r3: st.info(f"🟡 **Due Tomorrow ({len(due_tomorrow)})**\n\nAmt: ₹{due_tomorrow['bill_amount'].sum():,.2f}")
                with col_r4: st.success(f"🟢 **Next 7 Days ({len(due_upcoming)})**\n\nAmt: ₹{due_upcoming['bill_amount'].sum():,.2f}")

                with st.expander("🔍 View Detailed Date-Wise Pending Bills Breakdown"):
                    reminder_tab_od, reminder_tab_tod, reminder_tab_tom, reminder_tab_fut = st.tabs(["🔴 Overdue", "🟠 Today", "🟡 Tomorrow", "🟢 Upcoming (7d)"])
                    
                    with reminder_tab_od:
                        if not due_overdue.empty: st.dataframe(due_overdue[["party_name", "invoice_number", "invoice_date", "due_date", "bill_amount"]], use_container_width=True, hide_index=True)
                        else: st.success("No overdue bills!")
                    with reminder_tab_tod:
                        if not due_today.empty: st.dataframe(due_today[["party_name", "invoice_number", "invoice_date", "due_date", "bill_amount"]], use_container_width=True, hide_index=True)
                        else: st.info("No bills due today.")
                    with reminder_tab_tom:
                        if not due_tomorrow.empty: st.dataframe(due_tomorrow[["party_name", "invoice_number", "invoice_date", "due_date", "bill_amount"]], use_container_width=True, hide_index=True)
                        else: st.info("No bills due tomorrow.")
                    with reminder_tab_fut:
                        if not due_upcoming.empty: st.dataframe(due_upcoming[["party_name", "invoice_number", "invoice_date", "due_date", "bill_amount"]], use_container_width=True, hide_index=True)
                        else: st.info("No upcoming bills in the next 7 days.")
            else:
                st.success("🎉 All purchase bills are fully paid!")
        
        st.divider()

        col_exp1, col_exp2 = st.columns([2, 3])
        with col_exp1:
            output_summary = io.BytesIO()
            with pd.ExcelWriter(output_summary, engine='openpyxl') as writer:
                summary_export_df = df_dues[[
                    "party_name", "opening_balance", "opening_as_on", 
                    "total_bills", "total_payments", "total_due_amount", "Payment_Urgency"
                ]].copy()
                total_row = pd.DataFrame([{
                    "party_name": "GRAND TOTAL", "opening_balance": df_dues["opening_balance"].sum(),
                    "opening_as_on": "-", "total_bills": df_dues["total_bills"].sum(),
                    "total_payments": df_dues["total_payments"].sum(), "total_due_amount": df_dues["total_due_amount"].sum(),
                    "Payment_Urgency": "-"
                }])
                summary_export_df = pd.concat([summary_export_df, total_row], ignore_index=True)
                summary_export_df.to_excel(writer, index=False, sheet_name='Party Ledger Summary')
                
            st.download_button("📥 Download Summary Excel", output_summary.getvalue(), file_name="party_ledger_summary_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

        search_party = st.text_input("🔍 Search Party Name:", key="search_party_dash")
        filtered_dues = df_dues
        if search_party:
            filtered_dues = df_dues[df_dues["party_name"].str.contains(search_party, case=False, na=False)]

        st.markdown("---")
        for _, party_row in filtered_dues.iterrows():
            p_name = party_row["party_name"]
            total_due = party_row["total_due_amount"]
            urgency = party_row["Payment_Urgency"]
            
            with st.expander(f"🏢 **{p_name}** | Net Due: **₹{total_due:,.2f}** — {urgency}"):
                c_s1, c_s2, c_s3 = st.columns(3)
                c_s1.markdown(f"🔹 **Opening Balance:** ₹{party_row['opening_balance']:,.2f} *(As on {party_row['opening_as_on']})*")
                c_s2.markdown(f"📦 **Total Bills:** ₹{party_row['total_bills']:,.2f}")
                c_s3.markdown(f"💸 **Total Paid:** ₹{party_row['total_payments']:,.2f}")
                
                if not df_invoices.empty:
                    party_bills = df_invoices[df_invoices["party_name"] == p_name]
                    if not party_bills.empty:
                        today = date.today()
                        def calc_bill_urgency(row):
                            if row["status"] == "PAID": return "✅ PAID"
                            due_dt = datetime.strptime(row["due_date"], "%Y-%m-%d").date()
                            days_left = (due_dt - today).days
                            if days_left < 0: return f"🔴 OVERDUE"
                            elif days_left == 0: return f"🟠 TODAY"
                            return f"🟢 {days_left}d left"
                        party_bills["Urgency"] = party_bills.apply(calc_bill_urgency, axis=1)
                        st.dataframe(party_bills[["invoice_number", "invoice_date", "due_date", "bill_amount", "status", "Urgency"]], use_container_width=True, hide_index=True)
    else:
        st.info("No parties or purchase dues found yet.")

# --- MODULE 2: ADD PURCHASE BILLS & AI PAYMENT SCANNER ---
elif menu_choice == "📥 Add Purchase Bills & AI Pay":
    st.markdown("### 📥 Add Purchase Bills & AI Finance Scanner")
    col_op1, col_op2 = st.columns(2)

    with col_op1:
        with st.container(border=True):
            st.subheader("📥 Add New Purchase Bills")
            bill_tab_ai, bill_tab_excel, bill_tab_manual = st.tabs(["🤖 AI Image Scan", "📊 Bulk Excel", "✍️ Manual Entry"])
            
            with bill_tab_ai:
                uploaded_bill_img = st.file_uploader("Upload Purchase Bill Image", type=["png", "jpg", "jpeg"], key=f"ai_bill_{rc}")
                if uploaded_bill_img:
                    st.image(uploaded_bill_img, width=220)
                    if st.button("🔍 Extract & Save"):
                        with st.spinner("Scanning..."):
                            extracted_bill = extract_invoice_from_image(uploaded_bill_img)
                            if "error" in extracted_bill:
                                st.error(extracted_bill['error'])
                            else:
                                df_parties = get_parties_df()
                                matched_party = df_parties[df_parties["party_name"].str.contains(extracted_bill.get("party_name", ""), case=False, na=False)]
                                if not matched_party.empty:
                                    save_purchase_invoice(
                                        int(matched_party.iloc[0]["party_id"]),
                                        str(extracted_bill.get("invoice_number", "INV-AI")),
                                        str(extracted_bill.get("invoice_date", date.today().strftime("%Y-%m-%d"))),
                                        int(matched_party.iloc[0]["credit_period_days"]),
                                        float(extracted_bill.get("bill_amount", 0.0)),
                                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                    )
                                    st.success("✅ Bill saved!")
                                    st.session_state.reset_counter += 1
                                    st.rerun()
                                else:
                                    st.error("Party not found in Master List.")

            with bill_tab_excel:
                uploaded_inv_file = st.file_uploader("Upload Excel Bills", type=["xlsx", "csv"], key=f"excel_bill_{rc}")
                if uploaded_inv_file:
                    df_inv_upload = pd.read_csv(uploaded_inv_file) if uploaded_inv_file.name.endswith('.csv') else pd.read_excel(uploaded_inv_file, engine='openpyxl')
                    df_inv_upload.columns = [str(c).strip().lower().replace(" ", "_") for c in df_inv_upload.columns]
                    st.dataframe(df_inv_upload.head())
                    if st.button("🚀 Import Bills"):
                        count, errors = bulk_save_purchase_invoices(df_inv_upload)
                        if count > 0:
                            st.success(f"Imported {count} bills!")
                            st.session_state.reset_counter += 1
                            st.rerun()
                        for err in errors: st.warning(err)

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

    with col_op2:
        with st.container(border=True):
            st.subheader("🤖 AI Scan Daily Finance")
            uploaded_slip = st.file_uploader("Upload Payment Slip", type=["png", "jpg", "jpeg"], key=f"ai_slip_{rc}")
            if uploaded_slip:
                st.image(uploaded_slip, width=220)
                if st.button("🔍 Extract Payment"):
                    with st.spinner("Analyzing..."):
                        extracted = extract_payment_from_image(uploaded_slip)
                        if "error" in extracted:
                            st.error(extracted['error'])
                        else:
                            df_parties = get_parties_df()
                            matched_party = df_parties[df_parties["party_name"].str.contains(extracted.get("party_name", ""), case=False, na=False)]
                            if not matched_party.empty:
                                record_distributor_payment(
                                    int(matched_party.iloc[0]["party_id"]), [], float(extracted.get("amount_paid", 0.0)),
                                    extracted.get("payment_mode", "CASH"), date.today().strftime("%Y-%m-%d"), extracted.get("notes", "AI"), current_user
                                )
                                st.success("✅ Payment recorded!")
                                st.session_state.reset_counter += 1
                                st.rerun()
                            else:
                                st.error("Party not found.")

# --- MODULE 3: PARTY MASTER & SETUP ---
elif menu_choice == "📋 Party Master & Setup":
    st.markdown("### 📋 Purchase Parties Master Setup")
    with st.container(border=True):
        add_tab, bulk_party_tab, edit_del_tab = st.tabs(["➕ Add Single", "📤 Bulk Upload", "🛠️ Edit / Delete"])
        
        with add_tab:
            with st.form("party_form", clear_on_submit=True):
                p_name = st.text_input("Party Name *")
                c4, c5, c6 = st.columns(3)
                p_credit = c4.number_input("Credit Period (Days)", min_value=0, value=15)
                p_opening = c5.number_input("Opening Balance (₹)", min_value=0.0)
                p_as_on_date = c6.date_input("As on Date", value=date.today())

                if st.form_submit_button("💾 Save Party") and p_name:
                    save_party(p_name.strip().title(), "", "", p_credit, p_opening, p_as_on_date.strftime("%Y-%m-%d"), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                    st.success("✅ Saved!")
                    st.session_state.reset_counter += 1
                    st.rerun()

        with bulk_party_tab:
            uploaded_party_file = st.file_uploader("Upload Party Excel", type=["xlsx", "csv"], key=f"party_upl_{rc}")
            if uploaded_party_file:
                df_party_upload = pd.read_csv(uploaded_party_file) if uploaded_party_file.name.endswith('.csv') else pd.read_excel(uploaded_party_file, engine='openpyxl')
                if st.button("🚀 Import Parties"):
                    count, errors = bulk_save_parties(df_party_upload)
                    st.success(f"Imported {count} parties!")
                    st.session_state.reset_counter += 1
                    st.rerun()

        with edit_del_tab:
            df_parties_mgmt = get_parties_df()
            if not df_parties_mgmt.empty:
                selected_party_name = st.selectbox("Select Party", df_parties_mgmt["party_name"].tolist())
                party_id = int(df_parties_mgmt[df_parties_mgmt["party_name"] == selected_party_name].iloc[0]["party_id"])
                
                if st.button("🗑️ Permanently Delete Party", type="primary"):
                    delete_party(party_id)
                    st.success("✅ Deleted.")
                    st.session_state.reset_counter += 1
                    st.rerun()

# --- MODULE 4: PAYMENTS & BILL CLEARING ---
elif menu_choice == "💸 Payments & Bill Clearing":
    st.markdown("### 💸 Record Daily Distributor Payment")
    df_parties_pay = get_parties_df()
    if not df_parties_pay.empty:
        pay_party = st.selectbox("Select Distributor to Pay", df_parties_pay["party_name"].tolist())
        party_id = int(df_parties_pay[df_parties_pay["party_name"] == pay_party].iloc[0]["party_id"])

        with st.form("dash_payment_form", clear_on_submit=True):
            pay_amount = st.number_input("Amount Paid (₹) *", min_value=0.0, step=100.0)
            pay_mode = st.selectbox("Mode", ["CASH", "UPI", "BANK_TRANSFER", "CHEQUE"])
            pay_date = st.date_input("Date *", value=date.today())
            if st.form_submit_button("✅ Record Payment") and pay_amount > 0:
                record_distributor_payment(party_id, [], pay_amount, pay_mode, pay_date.strftime("%Y-%m-%d"), "", current_user)
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
