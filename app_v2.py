# app_v2.py
from datetime import datetime, date
import streamlit as st
import pandas as pd

from database_v2 import (
    init_clean_database, get_parties_df, save_party,
    get_financial_openings_df, save_financial_opening,
    save_purchase_invoice, get_purchase_invoices_df, get_party_dues_summary,
    record_balance_correction, get_adjustment_logs
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
# 2. SIDEBAR
# ==========================================
current_user = st.session_state.logged_in_user
user_role = USERS[current_user]["role"]
st.sidebar.success(f"User: **{current_user.upper()}** ({user_role})")

if st.sidebar.button("Logout"):
    st.session_state.logged_in_user = None
    st.rerun()

# ==========================================
# 3. MAIN TABS
# ==========================================
st.title("💊 Jeeva Medical Store Management System")

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 1. Purchase Parties Setup", 
    "💰 2. Daily Finance Initial Setup",
    "📦 3. Purchase Bills & Due Alerts",
    "📊 4. Party-Wise Total Dues"
])

# ------------------------------------------
# TAB 1: PURCHASE PARTIES SETUP & ADMIN CORRECTIONS
# ------------------------------------------
with tab1:
    st.subheader("Distributor / Purchase Parties Master Setup")
    with st.form("party_form"):
        c1, c2, c3 = st.columns(3)
        p_name = c1.text_input("Party / Distributor Name *")
        p_phone = c2.text_input("Phone Number")
        p_gstin = c3.text_input("GSTIN Number")

        c4, c5, c6 = st.columns(3)
        p_credit = c4.number_input("Credit Period (Days)", min_value=0, value=15)
        p_opening = c5.number_input("Opening Balance (₹)", min_value=0.0, step=100.0)
        p_as_on_date = c6.date_input("Opening Balance As on Date", value=date.today())

        if st.form_submit_button("💾 Save / Update Party") and p_name:
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

    st.divider()
    st.write("### Registered Purchase Parties")
    df_parties = get_parties_df()
    if not df_parties.empty:
        st.dataframe(df_parties, use_container_width=True, hide_index=True)
    else:
        st.info("No parties registered yet.")

    if user_role == "Owner":
        st.divider()
        st.subheader("🛠️ Admin Outstanding Balance Correction (Audit Logged)")
        if not df_parties.empty:
            with st.form("correction_form"):
                cc1, cc2 = st.columns(2)
                corr_party = cc1.selectbox("Select Party to Correct", df_parties["party_name"].tolist())
                corr_amount = cc2.number_input("Corrected Opening Balance (₹)", min_value=0.0, step=100.0)
                corr_reason = st.text_input("Mandatory Reason for Correction *")

                if st.form_submit_button("🔒 Apply Balance Correction"):
                    if corr_reason.strip():
                        party_row = df_parties[df_parties["party_name"] == corr_party].iloc[0]
                        record_balance_correction(
                            party_id=int(party_row["party_id"]),
                            new_opening_balance=corr_amount,
                            reason=corr_reason.strip(),
                            admin_user=current_user
                        )
                        st.success(f"Successfully corrected opening balance for {corr_party}!")
                        st.rerun()
                    else:
                        st.error("Please provide a mandatory reason for the correction audit trail.")

            st.write("### 📜 Admin Balance Correction Audit Trail")
            df_logs = get_adjustment_logs()
            if not df_logs.empty:
                st.dataframe(df_logs, use_container_width=True, hide_index=True)

# ------------------------------------------
# TAB 2: DAILY FINANCE INITIAL SETUP
# ------------------------------------------
with tab2:
    st.subheader("Daily Finance Initial Setup & Opening Balances")
    with st.form("finance_opening_form"):
        fc1, fc2, fc3 = st.columns(3)
        item_cat = fc1.selectbox("Category", ["Previous Closing Balance", "Cash Credit / Loan", "Customer Credit (Due)", "Salary Pending", "Other Debit / Credit"])
        nature = fc2.selectbox("Nature", ["CREDIT (+)", "DEBIT (-)"])
        amount = fc3.number_input("Amount (₹)", min_value=0.0, step=100.0)
        desc = st.text_input("Description / Notes")

        if st.form_submit_button("💾 Save Initial Financial Entry") and amount > 0:
            save_financial_opening(item_cat, desc.strip(), amount, nature, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            st.success("Successfully recorded opening financial item!")
            st.rerun()

    st.divider()
    df_openings = get_financial_openings_df()
    if not df_openings.empty:
        st.dataframe(df_openings, use_container_width=True, hide_index=True)
    else:
        st.info("No financial opening records added yet.")

# ------------------------------------------
# TAB 3: PURCHASE BILLS & DUE ALERTS
# ------------------------------------------
with tab3:
    st.subheader("📦 Purchase Invoices & Payment Due Alerts")
    df_parties = get_parties_df()
    if df_parties.empty:
        st.warning("Please register at least one Purchase Party in Tab 1 before adding bills.")
    else:
        with st.form("invoice_form"):
            ic1, ic2 = st.columns(2)
            selected_party = ic1.selectbox("Select Distributor", df_parties["party_name"].tolist())
            inv_no = ic2.text_input("Invoice / Bill Number *")

            ic3, ic4 = st.columns(2)
            inv_date = ic3.date_input("Invoice Date", value=date.today())
            bill_amt = ic4.number_input("Bill Total Amount (₹)", min_value=0.0, step=100.0)

            if st.form_submit_button("📥 Save Purchase Bill") and inv_no and bill_amt > 0:
                party_row = df_parties[df_parties["party_name"] == selected_party].iloc[0]
                save_purchase_invoice(
                    party_id=int(party_row["party_id"]),
                    inv_no=inv_no.strip(),
                    inv_date=inv_date.strftime("%Y-%m-%d"),
                    credit_days=int(party_row["credit_period_days"]),
                    amount=bill_amt,
                    created_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                st.success(f"Invoice {inv_no} saved successfully for {selected_party}!")
                st.rerun()

        st.divider()
        st.write("### Active Purchase Bills & Due Date Status")
        df_invoices = get_purchase_invoices_df()
        if not df_invoices.empty:
            today = date.today()
            def calculate_urgency(row):
                due_dt = datetime.strptime(row["due_date"], "%Y-%m-%d").date()
                days_left = (due_dt - today).days
                if days_left < 0:
                    return f"🔴 OVERDUE (Due: {row['due_date']})"
                elif days_left <= 3:
                    return f"🟡 Due Soon (Due: {row['due_date']}, {days_left}d left)"
                else:
                    return f"🟢 Safe (Due: {row['due_date']}, {days_left}d left)"

            df_invoices["Payment_Urgency"] = df_invoices.apply(calculate_urgency, axis=1)
            display_df = df_invoices[["party_name", "invoice_number", "invoice_date", "credit_period_days", "due_date", "bill_amount", "Payment_Urgency"]]
            
            def color_urgency(val):
                if "OVERDUE" in val:
                    return "background-color: #ffcccc; color: #990000; font-weight: bold;"
                elif "Due Soon" in val:
                    return "background-color: #fff2cc; color: #b26b00; font-weight: bold;"
                else:
                    return "background-color: #d9ead3; color: #274e13;"

            st.dataframe(display_df.style.map(color_urgency, subset=["Payment_Urgency"]), use_container_width=True, hide_index=True)
        else:
            st.info("No purchase bills logged yet.")

# ------------------------------------------
# TAB 4: PARTY-WISE TOTAL DUES (COLLAPSIBLE)
# ------------------------------------------
with tab4:
    st.subheader("📊 Party-Wise Total Dues & Bill-wise Breakdown")
    df_dues = get_party_dues_summary()
    df_invoices = get_purchase_invoices_df()

    if not df_dues.empty:
        total_market_dues = df_dues["total_due_amount"].sum()
        st.metric("Total Market Dues Payable", f"₹{total_market_dues:,.2f}")
        st.divider()

        search_party = st.text_input("🔍 Search Party Name:")
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
                            if days_left < 0:
                                return f"🔴 OVERDUE (Due: {row['due_date']})"
                            elif days_left <= 3:
                                return f"🟡 Due Soon (Due: {row['due_date']}, {days_left}d left)"
                            else:
                                return f"🟢 Safe (Due: {row['due_date']}, {days_left}d left)"

                        party_bills["Bill_Urgency"] = party_bills.apply(calc_bill_urgency, axis=1)
                        bill_display = party_bills[["invoice_number", "invoice_date", "credit_period_days", "due_date", "bill_amount", "Bill_Urgency"]]
                        
                        def color_urgency(val):
                            if "OVERDUE" in val:
                                return "background-color: #ffcccc; color: #990000; font-weight: bold;"
                            elif "Due Soon" in val:
                                return "background-color: #fff2cc; color: #b26b00; font-weight: bold;"
                            else:
                                return "background-color: #d9ead3; color: #274e13;"

                        st.dataframe(
                            bill_display.style.map(color_urgency, subset=["Bill_Urgency"]),
                            use_container_width=True,
                            hide_index=True
                        )
                    else:
                        st.info("No unpaid purchase bills recorded for this party.")
                else:
                    st.info("No purchase invoices found in the system.")
    else:
        st.info("No parties or purchase dues found yet. Add parties in Tab 1.")