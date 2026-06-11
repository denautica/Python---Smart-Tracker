import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime
import vertexai
from vertexai.generative_models import GenerativeModel, Part
import json

# --- SETUP ---
PROJECT_ID = "contr-tracker" 
LOCATION = "us-central1"
UPLOAD_DIR = "stored_contracts"
DB_FILE = "contracts_v5.db"
os.makedirs(UPLOAD_DIR, exist_ok=True)

try:
    vertexai.init(project=PROJECT_ID, location=LOCATION)
except: pass

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT, property_name TEXT, vendor_name TEXT, document_type TEXT,
            status TEXT, description TEXT, short_summary TEXT, is_recurring TEXT,
            billing_interval TEXT, interval_amount TEXT, deposit_required TEXT,
            contract_date TEXT, term_end TEXT, term_notice TEXT, cancel_deadline TEXT,
            file_name TEXT, date_added TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- AI CORE ---
def ai_analyze_file(file_path, mime_type):
    # Ensure your prompt returns valid JSON
    prompt = "Extract contract data into JSON: project_name, property_name, vendor_name, document_type, status, short_summary, description, is_recurring, billing_interval, interval_amount, deposit_required, contract_date, term_end, term_notice, cancel_deadline."
    try:
        with open(file_path, "rb") as f:
            data = Part.from_data(data=f.read(), mime_type=mime_type)
        model = GenerativeModel("gemini-1.5-flash") # Use 1.5-flash for speed
        response = model.generate_content([data, prompt])
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_text)
    except Exception as e:
        return {"project_name": "Error - Manual Entry Required"}

# --- UI ---
st.set_page_config(layout="wide", page_title="Contract Pro Manager")
st.title("📂 Contract Pro Management System")

if "bulk_ai_data" not in st.session_state: st.session_state.bulk_ai_data = {}

# Sidebar Upload
with st.sidebar:
    st.header("➕ Upload Documents")
    uploaded_files = st.file_uploader("Upload PDFs or Images", accept_multiple_files=True, key="main_uploader")
    
    if uploaded_files:
        for f_item in uploaded_files:
            if f_item.name not in st.session_state.bulk_ai_data:
                path = os.path.join(UPLOAD_DIR, f_item.name)
                with open(path, "wb") as f: f.write(f_item.getbuffer())
                
                with st.spinner(f"AI Scanning {f_item.name}..."):
                    mime = "application/pdf" if f_item.name.lower().endswith(".pdf") else "image/jpeg"
                    st.session_state.bulk_ai_data[f_item.name] = ai_analyze_file(path, mime)

# Main Area - Preview & Form
if st.session_state.bulk_ai_data:
    fname = list(st.session_state.bulk_ai_data.keys())[0]
    data = st.session_state.bulk_ai_data[fname]
    
    st.subheader(f"🔍 Previewing: {fname}")
    path = os.path.join(UPLOAD_DIR, fname)
    if fname.lower().endswith(('.png', '.jpg', '.jpeg')):
        st.image(path, use_container_width=True)
    else:
        st.info("PDF Preview: Download the file to view details.")

    # Form in Sidebar
    with st.sidebar.form("entry_form"):
        st.header("📋 Data Entry Form")
        p_name = st.text_input("Project Name", value=data.get("project_name", ""))
        vendor = st.text_input("Vendor", value=data.get("vendor_name", ""))
        status = st.selectbox("Status", ["Active", "Expired", "Superseded"])
        
        if st.form_submit_button("Commit to Database"):
            conn = sqlite3.connect(DB_FILE)
            conn.execute("INSERT INTO contracts (project_name, vendor_name, status, file_name) VALUES (?,?,?,?)", 
                         (p_name, vendor, status, fname))
            conn.commit()
            conn.close()
            del st.session_state.bulk_ai_data[fname]
            st.rerun()
else:
    st.write("No files pending review.")
