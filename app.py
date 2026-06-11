import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime
import vertexai
from vertexai.generative_models import GenerativeModel, Part
import json
import io

# ==========================================
# --- AI SETUP & CONFIGURATION ---
# ==========================================
PROJECT_ID = "contr-tracker" 
LOCATION = "us-central1" 

try:
    vertexai.init(project=PROJECT_ID, location=LOCATION)
except Exception as e:
    st.error(f"Cloud Initialization Warning: {str(e)}")

UPLOAD_DIR = "stored_contracts"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

DB_FILE = "contracts_database_v4.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT, property_name TEXT, vendor_name TEXT,
            document_type TEXT, status TEXT, description TEXT,
            short_summary TEXT, is_recurring TEXT, billing_interval TEXT,
            interval_amount TEXT, deposit_required TEXT, contract_date TEXT,
            file_name TEXT, term_start TEXT, term_end TEXT, auto_renew TEXT,
            term_notice TEXT, cancel_deadline TEXT, date_added TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def ai_analyze_file(file_path, mime_type):
    prompt = """Analyze this document and return a raw JSON string (no markdown ticks) with these keys: 
    project_name, property_name, vendor_name, document_type, status, short_summary, description, 
    is_recurring, billing_interval, interval_amount, deposit_required, contract_date, term_end, 
    term_notice, cancel_deadline."""
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        document_part = Part.from_data(data=file_bytes, mime_type=mime_type)
        model = GenerativeModel("gemini-2.5-flash")
        response = model.generate_content([document_part, prompt])
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"AI Extraction failed: {str(e)}")
        return None

def convert_df_to_excel(dataframe):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Contracts Report")
    return output.getvalue()

# ==========================================
# --- STREAMLIT UI ---
# ==========================================
st.set_page_config(page_title="AI Contract Database", layout="wide")
st.title("📂 Smart Project Contract & Estimate Database")

# --- Sidebar Upload & AI Processing ---
st.sidebar.header("➕ Bulk Document Upload")
uploaded_files = st.sidebar.file_uploader("Drop your PDFs or Images here", type=["pdf", "jpg", "jpeg", "png"], accept_multiple_files=True)

if "bulk_ai_data" not in st.session_state: st.session_state.bulk_ai_data = {}
if "review_queue_index" not in st.session_state: st.session_state.review_queue_index = 0

if uploaded_files:
    for f_item in uploaded_files:
        if f_item.name not in st.session_state.bulk_ai_data:
            file_path = os.path.abspath(os.path.join(UPLOAD_DIR, f_item.name))
            with open(file_path, "wb") as f: f.write(f_item.getbuffer())
            with st.sidebar.spinner(f"AI Scanning {f_item.name}..."):
                ext = f_item.name.lower().split(".")[-1]
                mime = "application/pdf" if ext == "pdf" else f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else 'png'}"
                data = ai_analyze_file(file_path, mime)
                st.session_state.bulk_ai_data[f_item.name] = data if data else {"project_name": "New Record"}

# --- SIDEBAR: Advanced Filters ---
st.sidebar.markdown("---")
st.sidebar.header("🔍 Advanced Filters")

conn = sqlite3.connect(DB_FILE)
df_all = pd.read_sql_query("SELECT * FROM contracts", conn)
conn.close()

with st.sidebar.form("filter_form"):
    project_search = st.text_input("Search Project Name")
    intervals = st.multiselect("Filter by Billing Interval", options=df_all["billing_interval"].dropna().unique() if not df_all.empty else [])
    date_type = st.selectbox("Select Date Field", ["contract_date", "cancel_deadline", "term_end"])
    start_date = st.date_input("Start Date", value=None)
    end_date = st.date_input("End Date", value=None)
    apply_filters = st.form_submit_button("Apply Filters")

# --- DATABASE QUERY ---
query = "SELECT * FROM contracts WHERE 1=1"
params = []

if apply_filters:
    if project_search:
        query += " AND project_name LIKE ?"
        params.append(f"%{project_search}%")
    if intervals:
        placeholders = ','.join(['?'] * len(intervals))
        query += f" AND billing_interval IN ({placeholders})"
        params.extend(intervals)
    if start_date and end_date:
        query += f" AND {date_type} BETWEEN ? AND ?"
        params.extend([start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")])

conn = sqlite3.connect(DB_FILE)
df = pd.read_sql_query(query, conn, params=params)
conn.close()

# --- DISPLAY & EXPORT ---
if not df.empty:
    df.columns = ["ID", "Project/Task", "Property", "Vendor", "Type", "Status", "Description", 
                  "Short Summary", "Recurring", "Billing Interval", "Interval Amount", "Deposit Status", 
                  "Doc Date", "File Name", 'Term Start', "Term End", "Auto-Renew", "Notice Period", "Cancel Deadline", "Date Added"]
    
    excel_stream = convert_df_to_excel(df)
    st.download_button("📊 Export Results to Excel", excel_stream, f"contracts_export_{datetime.now().strftime('%Y-%m-%d')}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
    for index, row in df.iterrows():
        with st.expander(f"{row['Project/Task']} — {row['Vendor']}"):
            st.write(f"**Overview:** {row['Short Summary']}")
            # ... (Paste your existing detailed display and edit logic here)
else:
    st.info("No records found matching your filters.")
