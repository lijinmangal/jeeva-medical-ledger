# app_v2.py
from datetime import datetime, date
import streamlit as st
import pandas as pd
import io

from database_v2 import (
    init_clean_database, get_parties_df, save_party, update_party, delete_party,
    save_purchase_invoice, get_purchase_invoices_df, get_party_dues_summary,
    record_distributor_payment, delete_distributor_payment, get_distributor_payments_df,
    bulk_save_parties, bulk_save_purchase_invoices,
    extract_invoice_from_image, extract_payment_from_image
)

st.set_page_config(page_title="Jeeva Medical Store V2", page_icon="💊", layout="wide")
init_clean_database()

USERS = {
    "admin": {"pin": "1234", "role": "Owner"},
    "staff1": {"pin": "1111", "role": "Counter Staff"},
    "accounts": {"pin": "2222", "role": "Accountant"}
}

# ==========================================
# 1. LOGIN SCREEN
# ==========================================
if "logged_in_user" not in st.session_state:
    st.session_state.logged_in_user = None

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

# ==========================================
# 2. COMPACT TOP-LEFT TITLE & TOP-RIGHT BADGE
# ==========================================
current_user = st.session_state.logged_in_user
user_role = USERS[current_user]["role"]

header_col1, header_col2 = st.columns([4, 1])

with header_col1:
    st.markdown("### 💊 Jeeva Medical Store Management")

with header_col2:
    st.markdown(
        f"""
        <div style="text-align: right; padding-top: 5px;">
            <span style="background-color: #e2efda; color: #375623; padding: 3px 8px; border-radius: 10px; font-size: 12px; font-weight: bold;">
                👤 {current_user.upper()} ({user_role})
            </span>
        </div>
        """, 
        unsafe_allow_html=True
    )
    if st.button("🚪 Logout", key="top_logout_btn", use_container_width=True):
        st.session_state.logged_in_user = None
        st.rerun()

st.divider()

# ==========================================
# SECTION 1: SHOW OUTSTANDINGS TOGGLE
# ==========================================
with st.expander("📊 Show Market Outstandings & Collapsible Party Breakdown", expanded=False):
    df_dues = get_party_dues_summary()
    df_invoices = get_purchase_invoices_df()

    if not df_dues.empty:
        total_market_dues = df_dues["total_due_amount"].sum()
        st.metric("Total Market Dues Payable", f"₹{total_market_dues:,.2f}")
        st.divider()

        search_party = st.text_input("🔍 Search Party Name:", key="search_party_dash")
        filtered_dues = df_dues
        if search_party:
            filtered_dues = df_dues[df_dues["party_name"].str.contains(search_party, case=False, na=False)]

        for _, party_row in filtered_dues.iterrows():
            p_name = party_row["party_name"]
            total_due = party_row["total_due_amount"]
            urgency = party_row["Payment_Urgency"]
            opening_bal = party_row["opening_balance"]
            total_bills = party_row["total_bills"]
            total_pays = party_row["total_payments"]
            opening_as_on = party_row["opening_as_on"]

            expander_label = f"🏢 **{p_name}** | Net Due: **₹{total_due:,.2f}** — {urgency}"
            
            with st.expander(expander_label):
                c_s1, c_s2, c_s3 = st.columns(3)
                c_s1.markdown(f"🔹 **Opening:** ₹{opening_bal:,.2f} *(As on {opening_as_on})*")
                c_s2.markdown(f"📦 **Total Bills:** ₹{total_bills:,.2f}")
                c_s3.markdown(f"💸 **Total Paid:** ₹{total_pays:,.2f}")
                
                if not df_invoices.empty:
                    party_bills = df_invoices[(df_invoices["party_name"] == p_name) & (df_invoices["status"] == "UNPAID")]
                    if not party_bills.empty:
                        st.markdown("#### 📦 Unpaid Purchase Invoices:")
                        today = date.today()
                        def calc_bill_urgency(row):
                            due_dt = datetime.strptime(row["due_date"], "%Y-%m-%d").date()
                            days_left = (due_dt - today).days
                            if days_left < 0: return f"🔴 OVERDUE ({row['due_date']})"
                            elif days_left <= 3: return f"🟡 Due Soon ({row['due_date']}, {days_left}d)"
                            else: return f"🟢 Safe ({row['due_date']}, {days_left}d)"

                        party_bills["Bill_Urgency"] = party_bills.apply(calc_bill_urgency, axis=1)
                        st.dataframe(party_bills[["invoice_number", "invoice_date", "due_date", "bill_amount", "Bill_Urgency"]], use_container_width=True, hide_index=True)
                    else:
                        st.info("No unpaid purchase bills recorded.")
    else:
        st.info("No parties or purchase dues found yet.")

# ==========================================
# SECTION 2: ADD NEW BILLS & AI PAYMENT SCANNER
# ==========================================
col_op1, col_op2 = st.columns(2)

with col_op1:
    with st.container(border=True):
        st.subheader("📥 Add New Purchase Bills")
        bill_tab_ai, bill_tab_excel, bill_tab_manual = st.tabs(["🤖 AI Image Scan", "📊 Bulk Excel", "✍️ Manual Entry"])
        
        with bill_tab_ai:
            st.markdown("Upload photo of distributor purchase bill/invoice to extract & save.")
            uploaded_bill_img = st.file_uploader("Upload Purchase Bill Image", type=["png", "jpg", "jpeg"], key="ai_bill_up")
            
            if uploaded_bill_img:
                st.image(uploaded_bill_img, caption="Uploaded Purchase Bill", width=220)
                if st.button("🔍 Extract & Save Bill via AI"):
                    with st.spinner("Gemini AI is scanning invoice..."):
                        extracted_bill = extract_invoice_from_image(uploaded_bill_img)
                        if "error" in extracted_bill:
                            st.error(f"AI Error: {extracted_bill['error']}")
                        else:
                            st.success("Extracted Successfully!")
                            st.json(extracted_bill)
                            
                            df_parties = get_parties_df()
                            p_name_raw = str(extracted_bill.get("party_name", "")).strip()
                            matched_party = df_parties[df_parties["party_name"].str.contains(p_name_raw, case=False, na=False)]
                            
                            if not matched_party.empty:
                                p_id = int(matched_party.iloc[0]["party_id"])
                                credit_days = int(matched_party.iloc[0]["credit_period_days"])
                                inv_amt = float(extracted_bill.get("bill_amount", 0.0))
                                inv_no = str(extracted_bill.get("invoice_number", "INV-AI"))
                                inv_date = str(extracted_bill.get("invoice_date", date.today().strftime("%Y-%m-%d")))
                                
                                if inv_amt > 0:
                                    save_purchase_invoice(p_id, inv_no, inv_date, credit_days, inv_amt, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                                    st.success(f"Saved Bill **{inv_no}** (₹{inv_amt:,.2f}) for {matched_party.iloc[0]['party_name']}!")
                                    st.rerun()
                                else:
                                    st.warning("Invalid bill amount.")
                            else:
                                st.error(f"Party '{p_name_raw}' not found in Master List.")

        with bill_tab_excel:
            st.markdown("Upload Excel/CSV with columns: `party_name`, `invoice_number`, `invoice_date`, `bill_amount`.")
            uploaded_inv_file = st.file_uploader("Upload Purchase Bills Excel/CSV", type=["xlsx", "xls", "csv"], key="dash_inv_up")
            
            if uploaded_inv_file:
                try:
                    df_inv_upload = pd.read_csv(uploaded_inv_file) if uploaded_inv_file.name.endswith('.csv') else pd.read_excel(uploaded_inv_file)
                    st.dataframe(df_inv_upload.head(3), use_container_width=True)
                    if st.button("🚀 Process & Import Bills in Bulk"):
                        count, errors = bulk_save_purchase_invoices(df_inv_upload)
                        if count > 0: st.success(f"Imported {count} bills successfully!")
                        if errors:
                            st.error(f"Encountered {len(errors)} issues:")
                            for err in errors[:5]: st.warning(err)
                        if count > 0: st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        with bill_tab_manual:
            st.markdown("Manually enter purchase bill details.")
            df_parties_manual = get_parties_df()
            if not df_parties_manual.empty:
                with st.form("manual_bill_form"):
                    m_party = st.selectbox("Select Distributor *", df_parties_manual["party_name"].tolist(), key="manual_party_sel")
                    m_inv_no = st.text_input("Invoice Number *", key="manual_inv_no")
                    m_inv_date = st.date_input("Invoice Date", value=date.today(), key="manual_inv_date")
                    m_amt = st.number_input("Bill Amount (₹) *", min_value=0.0, step=100.0, key="manual_amt")
                    
                    if st.form_submit_button("💾 Save Manual Bill") and m_inv_no and m_amt > 0:
                        party_row = df_parties_manual[df_parties_manual["party_name"] == m_party].iloc[0]
                        save_purchase_invoice(
                            party_id=int(party_row["party_id"]),
                            inv_no=m_inv_no.strip(),
                            inv_date=m_inv_date.strftime("%Y-%m-%d"),
                            credit_days=int(party_row["credit_period_days"]),
                            amount=m_amt,
                            created_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        )
                        st.success(f"Successfully saved bill **{m_inv_no}** for {m_party}!")
                        st.rerun()
            else:
                st.warning("Please register at least one purchase party first.")

with col_op2:
    with st.container(border=True):
        st.subheader("🤖 AI Scan Daily Finance / Bill Paid")
        st.markdown("Upload image of payment receipt or daily finance sheet to record payment.")
        uploaded_slip = st.file_uploader("Upload Payment Slip / Finance Image", type=["png", "jpg", "jpeg"], key="ai_slip_up")
        
        if uploaded_slip:
            st.image(uploaded_slip, caption="Uploaded Finance Slip", width=220)
            if st.button("🔍 Extract & Record Payment via AI"):
                with st.spinner("Gemini AI is analyzing slip..."):
                    extracted = extract_payment_from_image(uploaded_slip)
                    if "error" in extracted:
                        st.error(f"AI Error: {extracted['error']}")
                    else:
                        st.success("Extracted Successfully!")
                        st.json(extracted)
                        
                        df_parties = get_parties_df()
                        matched_party = df_parties[df_parties["party_name"].str.contains(extracted.get("party_name", ""), case=False, na=False)]
                        
                        if not matched_party.empty:
                            p_id = int(matched_party.iloc[0]["party_id"])
                            amt = float(extracted.get("amount_paid", 0.0))
                            if amt > 0:
                                record_distributor_payment(
                                    party_id=p_id,
                                    invoice_ids_to_clear=[],
                                    payment_amount=amt,
                                    payment_mode=extracted.get("payment_mode", "CASH"),
                                    notes=extracted.get("notes", "AI Extracted Slip"),
                                    recorded_by=current_user
                                )
                                st.success(f"Recorded payment of ₹{amt:,.2f} for {matched_party.iloc[0]['party_name']}!")
                                st.rerun()
                            else:
                                st.warning("Invalid payment amount.")
                        else:
                            st.error(f"Party '{extracted.get('party_name')}' not found.")

# ==========================================
# SECTION 3: PARTY SETUP & EDIT/DELETE MANAGEMENT
# ==========================================
with st.container(border=True):
    st.subheader("📋 Purchase Parties Master Setup & Management")
    
    add_tab, bulk_party_tab, edit_del_tab = st.tabs(["➕ Add Single Party", "📤 Bulk Upload Parties", "🛠️ Edit / Delete Party"])
    
    with add_tab:
        with st.form("party_form"):
            c1, c2, c3 = st.columns(3)
            p_name = c1.text_input("Party / Distributor Name *")
            p_phone = c2.text_input("Phone Number")
            p_gstin = c3.text_input("GSTIN Number")

            c4, c5, c6 = st.columns(3)
            p_credit = c4.number_input("Credit Period (Days)", min_value=0, value=15)
            p_opening = c5.number_input("Opening Balance (₹)", min_value=0.0, step=100.0)
            p_as_on_date = c6.date_input("Opening Balance As on Date", value=date.today())

            if st.form_submit_button("💾 Save Party") and p_name:
                save_party(
                    name=p_name.strip().title(),
                    phone=p_phone.strip(),
                    gstin=p_gstin.strip().upper(),
                    credit_days=p_credit,
                    opening_bal=p_opening,
                    as_on_date=p_as_on_date.strftime("%Y-%m-%d"),
                    created_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                st.success(f"Successfully saved party: **{p_name.strip().title()}**!")
                st.rerun()

    with bulk_party_tab:
        uploaded_party_file = st.file_uploader("Upload Party Excel/CSV", type=["xlsx", "xls", "csv"], key="party_uploader")
        if uploaded_party_file:
            try:
                df_party_upload = pd.read_csv(uploaded_party_file) if uploaded_party_file.name.endswith('.csv') else pd.read_excel(uploaded_party_file)
                st.dataframe(df_party_upload.head(), use_container_width=True)
                if st.button("🚀 Process & Import Parties"):
                    count, errors = bulk_save_parties(df_party_upload)
                    if count > 0: st.success(f"Successfully imported {count} parties!")
                    if errors:
                        st.error(f"Encountered {len(errors)} issues:")
                        for err in errors[:5]: st.warning(err)
                    if count > 0: st.rerun()
            except Exception as e:
                st.error(f"Error reading file: {e}")

    with edit_del_tab:
        df_parties_mgmt = get_parties_df()
        if not df_parties_mgmt.empty:
            selected_party_name = st.selectbox("Select Party to Edit or Delete", df_parties_mgmt["party_name"].tolist(), key="mgmt_party_sel")
            party_record = df_parties_mgmt[df_parties_mgmt["party_name"] == selected_party_name].iloc[0]
            party_id = int(party_record["party_id"])
            
            sub_edit_tab, sub_del_tab = st.tabs(["✏️ Edit Party Details", "🗑️ Delete Party"])
            
            with sub_edit_tab:
                with st.form("edit_party_form"):
                    e_name = st.text_input("Party Name", value=party_record["party_name"])
                    e_phone = st.text_input("Phone Number", value=str(party_record.get("phone", "")) if pd.notna(party_record.get("phone")) else "")
                    e_gstin = st.text_input("GSTIN Number", value=str(party_record.get("gstin", "")) if pd.notna(party_record.get("gstin")) else "")
                    e_credit = st.number_input("Credit Period (Days)", min_value=0, value=int(party_record.get("credit_period_days", 15)))
                    e_opening = st.number_input("Opening Balance (₹)", min_value=0.0, value=float(party_record.get("opening_balance", 0.0)), step=100.0)
                    
                    if st.form_submit_button("💾 Save Changes"):
                        if e_name.strip():
                            update_party(
                                party_id=party_id,
                                name=e_name.strip().title(),
                                phone=e_phone.strip(),
                                gstin=e_gstin.strip().upper(),
                                credit_days=e_credit,
                                opening_bal=e_opening,
                                as_on_date=str(party_record.get("as_on_date", date.today().strftime("%Y-%m-%d")))
                            )
                            st.success(f"Successfully updated details for **{e_name.strip().title()}**!")
                            st.rerun()
                        else:
                            st.error("Party name cannot be empty.")
                        
            with sub_del_tab:
                st.warning(f"⚠️ Deleting **{selected_party_name}** will also remove all associated purchase invoices and payment records permanently.")
                confirm_del = st.checkbox(f"I confirm I want to delete {selected_party_name}", key="confirm_delete_chk")
                if st.button("🗑️ Permanently Delete Party", type="primary", key="btn_del_party"):
                    if confirm_del:
                        delete_party(party_id)
                        st.success(f"Successfully deleted {selected_party_name}.")
                        st.rerun()
                    else:
                        st.error("Please check the confirmation box to enable deletion.")
        else:
            st.info("No parties registered in the system yet.")

# ==========================================
# SECTION 4: EXPORT DATA TO EXCEL
# ==========================================
with st.container(border=True):
    st.subheader("💾 Download System Data as Excel")
    col_dl1, col_dl2, col_dl3 = st.columns(3)
    
    with col_dl1:
        df_p = get_parties_df()
        if not df_p.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_p.to_excel(writer, index=False, sheet_name='Parties')
            st.download_button("📥 Download Parties Excel", output.getvalue(), file_name="parties_master.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
    with col_dl2:
        df_i = get_purchase_invoices_df()
        if not df_i.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_i.to_excel(writer, index=False, sheet_name='Invoices')
            st.download_button("📥 Download Invoices Excel", output.getvalue(), file_name="purchase_invoices.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with col_dl3:
        df_pay = get_distributor_payments_df()
        if not df_pay.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_pay.to_excel(writer, index=False, sheet_name='Payments')
            st.download_button("📥 Download Payments Excel", output.getvalue(), file_name="distributor_payments.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ==========================================
# SECTION 5: DAILY PAYMENT RECORDING & DELETION MANAGER
# ==========================================
with st.container(border=True):
    st.subheader("💸 Record Daily Distributor Payment & Manage History")
    st.markdown("Quickly log daily payments made to suppliers, clear specific bills, or remove wrongly recorded entries.")

    df_parties_pay = get_parties_df()
    if not df_parties_pay.empty:
        pay_party = st.selectbox("Select Distributor to Pay *", df_parties_pay["party_name"].tolist(), key="dash_pay_party_sel")
        party_row = df_parties_pay[df_parties_pay["party_name"] == pay_party].iloc[0]
        party_id = int(party_row["party_id"])

        df_invoices = get_purchase_invoices_df()
        unpaid_party_bills = pd.DataFrame()
        if not df_invoices.empty:
            unpaid_party_bills = df_invoices[(df_invoices["party_id"] == party_id) & (df_invoices["status"] == "UNPAID")]

        selected_invoice_ids = []
        if not unpaid_party_bills.empty:
            with st.expander(f"📦 Select Unpaid Bills to Clear for {pay_party} (Optional)"):
                for _, bill in unpaid_party_bills.iterrows():
                    checked = st.checkbox(
                        f"Invoice: **{bill['invoice_number']}** | Date: {bill['invoice_date']} | Due: {bill['due_date']} | Amount: **₹{bill['bill_amount']:,.2f}**", 
                        key=f"dash_inv_chk_{bill['invoice_id']}"
                    )
                    if checked:
                        selected_invoice_ids.append(int(bill['invoice_id']))
        else:
            st.info(f"ℹ️ No specific unpaid invoices found for {pay_party}. Payment will be recorded as a general credit/advance adjustment.")

        with st.form("dash_payment_form"):
            pc1, pc2 = st.columns(2)
            pay_amount = pc1.number_input("Payment Amount Paid (₹) *", min_value=0.0, step=100.0, key="dash_pay_amt")
            pay_mode = pc2.selectbox("Payment Mode", ["CASH", "UPI", "BANK_TRANSFER", "CHEQUE"], key="dash_pay_mode")
            pay_notes = st.text_input("Payment Notes / Reference No. (Optional)", key="dash_pay_notes")

            if st.form_submit_button("✅ Confirm & Record Payment"):
                if pay_amount > 0:
                    record_distributor_payment(
                        party_id=party_id,
                        invoice_ids_to_clear=selected_invoice_ids,
                        payment_amount=pay_amount,
                        payment_mode=pay_mode,
                        notes=pay_notes.strip(),
                        recorded_by=current_user
                    )
                    st.success(f"Successfully recorded payment of ₹{pay_amount:,.2f} to **{pay_party}**!")
                    st.rerun()
                else:
                    st.error("Please enter a valid payment amount greater than 0.")

        with st.expander("📜 View & Manage Payment History (Delete Wrong Entries)"):
            df_payments = get_distributor_payments_df()
            if not df_payments.empty:
                st.dataframe(df_payments[["payment_id", "party_name", "amount_paid", "payment_mode", "timestamp", "recorded_by", "notes"]], use_container_width=True, hide_index=True)
                
                st.markdown("---")
                st.markdown("##### 🗑️ Delete Wrongly Recorded Payment")
                
                payment_options = df_payments.apply(
                    lambda r: f"ID: {r['payment_id']} | Party: {r['party_name']} | ₹{r['amount_paid']:,.2f} | Date: {r['timestamp']}", 
                    axis=1
                ).tolist()
                
                selected_pay_to_del = st.selectbox("Select Payment Entry to Remove", payment_options, key="del_pay_sel")
                
                if st.button("🗑️ Delete Selected Payment", type="primary", key="btn_del_payment"):
                    try:
                        p_id_extracted = int(selected_pay_to_del.split("|")[0].replace("ID:", "").strip())
                        delete_distributor_payment(p_id_extracted)
                        st.success(f"Successfully deleted payment entry (ID: {p_id_extracted}) and restored outstandings!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting payment: {e}")
            else:
                st.info("No distributor payments recorded yet.")
    else:
        st.warning("Please register at least one purchase party first.")
