# app_v2.py
from datetime import datetime, date
import streamlit as st
import pandas as pd
import io

from database_v2 import (
    init_clean_database, get_parties_df, save_party,
    get_financial_openings_df, save_financial_opening,
    save_purchase_invoice, get_purchase_invoices_df, get_party_dues_summary,
    record_balance_correction, get_adjustment_logs,
    record_distributor_payment, get_distributor_payments_df,
    bulk_save_parties, bulk_save_purchase_invoices,
    extract_payment_from_image
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
# 3. FRONT-PAGE DASHBOARD SECTIONS
# ==========================================

# --- SECTION 1: SHOW OUTSTANDINGS TOGGLE ---
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
            opening_as_on = party_row["opening_as_on"]

            expander_label = f"🏢 **{p_name}** | Total Due: **₹{total_due:,.2f}** — {urgency}"
            
            with st.expander(expander_label):
                st.markdown(f"🔹 **Opening Balance Due:** ₹{opening_bal:,.2f} *(Baseline As on: {opening_as_on})*")
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


# --- SECTION 2: ADD NEW BILLS & FEED DAILY BILL PAID (AI VISION) ---
col_op1, col_op2 = st.columns(2)

with col_op1:
    with st.container(border=True):
        st.subheader("📥 Bulk Add New Bills (Excel)")
        st.markdown("Upload billing software export with columns: `party_name`, `invoice_number`, `invoice_date`, `bill_amount`.")
        uploaded_inv_file = st.file_uploader("Upload Purchase Bills Excel/CSV", type=["xlsx", "xls", "csv"], key="dash_inv_up")
        
        if uploaded_inv_file:
            try:
                df_inv_upload = pd.read_csv(uploaded_inv_file) if uploaded_inv_file.name.endswith('.csv') else pd.read_excel(uploaded_inv_file)
                if st.button("🚀 Process & Import Bills"):
                    count, errors = bulk_save_purchase_invoices(df_inv_upload)
                    if count > 0: st.success(f"Imported {count} bills successfully!")
                    if errors: st.warning(f"Encountered {len(errors)} issues.")
                    if count > 0: st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")

with col_op2:
    with st.container(border=True):
        st.subheader("🤖 AI Scan Daily Finance / Bill Paid")
        st.markdown("Upload image of daily finance sheet or payment receipt to extract & feed payment.")
        uploaded_slip = st.file_uploader("Upload Payment Slip / Finance Image", type=["png", "jpg", "jpeg"], key="ai_slip_up")
        
        if uploaded_slip:
            st.image(uploaded_slip, caption="Uploaded Finance Slip", width=250)
            if st.button("🔍 Extract & Record Payment via AI"):
                with st.spinner("Gemini AI is analyzing the slip..."):
                    extracted = extract_payment_from_image(uploaded_slip)
                    if "error" in extracted:
                        st.error(f"AI Extraction Error: {extracted['error']}")
                    else:
                        st.success("Extracted Data Successfully!")
                        st.json(extracted)
                        
                        # Match party and record payment automatically
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
                            else:
                                st.warning("Extracted amount was 0 or invalid.")
                        else:
                            st.error(f"Party '{extracted.get('party_name')}' not found in Master List. Please register them first.")


# --- SECTION 3: EXPORT DATA TO EXCEL ---
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
# --- Replace party management section in app_v2.py ---

with st.expander("🛠️ Manage Existing Purchase Parties (Edit / Delete)"):
    df_parties_mgmt = get_parties_df()
    if not df_parties_mgmt.empty:
        selected_party_name = st.selectbox("Select Party to Edit or Delete", df_parties_mgmt["party_name"].tolist(), key="mgmt_party_sel")
        party_record = df_parties_mgmt[df_parties_mgmt["party_name"] == selected_party_name].iloc[0]
        party_id = int(party_record["party_id"])
        
        edit_tab, delete_tab = st.tabs(["✏️ Edit Party Details", "🗑️ Delete Party"])
        
        with edit_tab:
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
                    
        with delete_tab:
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
