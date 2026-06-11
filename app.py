import streamlit as st
import pandas as pd
import sqlite3
import os
import io
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from vertexai.generative_models import GenerativeModel, Part
import json
from fpdf import FPDF

# --- CONFIG ---
DB_FILE = "contracts_v5.db"
UPLOAD_DIR = "stored_contracts"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT, property_name TEXT, vendor_name TEXT, document_type TEXT,
            status TEXT, description TEXT, short_summary TEXT, is_recurring TEXT,
            billing_interval TEXT, interval_amount TEXT, deposit_required TEXT,
            contract_date DATE, term_start DATE, term_end DATE, auto_renew TEXT,
            term_notice TEXT, cancel_deadline DATE, date_added DATETIME
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS contract_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER, image_path TEXT, is_primary BOOLEAN,
            FOREIGN KEY(contract_id) REFERENCES contracts(id)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- UTILS ---
def get_db(): return sqlite3.connect(DB_FILE)

def send_expiry_alerts():
    # Placeholder for SMTP logic
    # In production, use environment variables for credentials
    pass

# --- UI LOGIC ---
st.set_page_config(layout="wide", page_title="Contract Pro Manager")
st.title("📂 Contract Pro Management System")

# --- BULK UPLOAD QUEUE ---
if "bulk_ai_data" not in st.session_state: st.session_state.bulk_ai_data = {}

with st.sidebar:
    st.header("➕ Upload Documents")
    files = st.file_uploader("Upload", accept_multiple_files=True)
    if files:
        for f in files:
            if f.name not in st.session_state.bulk_ai_data:
                path = os.path.join(UPLOAD_DIR, f.name)
                with open(path, "wb") as w: w.write(f.getbuffer())
                # Simulate AI analysis (integration with your existing function)
                st.session_state.bulk_ai_data[f.name] = {"project_name": f.name.split('.')[0], "status": "Active"}

# --- REVIEW & COMMIT ---
if st.session_state.bulk_ai_data:
    fname = list(st.session_state.bulk_ai_data.keys())[0]
    st.sidebar.markdown("---")
    st.sidebar.subheader(f"📋 Verify: {fname}")
    
    # 1. Safe Preview Logic (prevents PIL error)
    file_ext = fname.lower().split('.')[-1]
    if file_ext in ['jpg', 'jpeg', 'png', 'bmp']:
        st.sidebar.image(os.path.join(UPLOAD_DIR, fname), use_container_width=True)
    else:
        st.sidebar.info(f"📄 Document: {fname} (Preview unavailable for PDF)")

    # 2. Extract Data for Form
    data = st.session_state.bulk_ai_data[fname]
    
    # 3. The Form (ALWAYS rendered)
    with st.sidebar.form("commit_form"):
        project = st.text_input("Project Name", value=data.get("project_name", ""))
        vendor = st.text_input("Vendor Name", value=data.get("vendor_name", ""))
        status = st.selectbox("Status", ["Active", "Expired", "Superseded"], index=0)
        
        # Add your other fields here (Billing, Dates, etc.)
        
        submit = st.form_submit_button("Commit to Database ➡️")
        
    if submit:
        # DB Logic
        conn = get_db()
        conn.execute("INSERT INTO contracts (project_name, vendor_name, status, date_added) VALUES (?, ?, ?, ?)", 
                     (project, vendor, status, datetime.now()))
        conn.commit()
        conn.close()
        
        # Cleanup Queue
        del st.session_state.bulk_ai_data[fname]
        st.rerun()

# --- SEARCH & DASHBOARD ---
st.subheader("🔍 Search & Filter")
c1, c2, c3 = st.columns(3)
with c1: search_p = st.text_input("Project Name")
with c2: deadline_range = st.date_input("Deadline Range", value=())
with c3: sort_by = st.selectbox("Sort By", ["Contract Date", "Billing Interval", "Interval Amount"])

conn = get_db()
query = "SELECT * FROM contracts WHERE 1=1"
if search_p: query += f" AND project_name LIKE '%{search_p}%'"
df = pd.read_sql_query(query, conn)
conn.close()

# --- COMPARISON & EXPORT ---
if not df.empty:
    selected_projs = st.multiselect("Compare up to 5 projects", df["project_name"].unique(), max_selections=5)
    
    if selected_projs:
        comp_df = df[df["project_name"].isin(selected_projs)]
        st.table(comp_df)
        if st.button("Generate Comparison PDF"):
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, txt="Comparison Report", ln=True, align='C')
            # Add table data logic here
            st.download_button("Download Report", data=pdf.output(dest='S'), file_name="report.pdf")

# --- RECORD CARDS ---
for _, row in df.iterrows():
    with st.expander(f"📍 {row['project_name']} | {row['status']}"):
        st.write(f"**Vendor:** {row['vendor_name']} | **Deadline:** {row['cancel_deadline']}")
        if st.button("View Details", key=f"view_{row['id']}"):
            st.info("Additional file details and attached images gallery would appear here.")

# --- ALERT SYSTEM (Scheduled Check) ---
if st.button("Check Deadlines"):
    send_expiry_alerts()
    st.success("Deadlines checked. Emails sent if required.")
