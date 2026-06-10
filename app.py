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

# Safe relative paths using forward slashes to prevent OneDrive Unicode escape issues
UPLOAD_DIR = "stored_contracts"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

DB_FILE = "contracts_database_v4.db"

# ==========================================
# --- DATABASE INITIALIZATION ---
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT,
            property_name TEXT,
            vendor_name TEXT,
            document_type TEXT,
            status TEXT,
            description TEXT,
            short_summary TEXT,
            is_recurring TEXT,
            billing_interval TEXT,
            interval_amount TEXT,
            deposit_required TEXT,
            contract_date TEXT,
            file_name TEXT,
            term_start TEXT,
            term_end TEXT,
            auto_renew TEXT,
            term_notice TEXT,
            cancel_deadline TEXT,
            date_added TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ==========================================
# --- AI CORE EXTRACTION ENGINE ---
# ==========================================
def ai_analyze_file(file_path, mime_type):
    prompt = """
    Analyze this attached document or image and extract data into a clean JSON object. 
    Read all visible handwritten or typed text carefully.
    Return ONLY a raw JSON string with exactly these keys (do not include markdown block ticks like ```json):
    {
      "project_name": "Short 2-4 word project or task name based on document context",
      "property_name": "Name of the specific building, apartment community, or site location if mentioned, otherwise leave blank",
      "vendor_name": "Name of the company, subcontractor, or contractor who generated this document",
      "document_type": "Must be exactly one of these: 'Estimate/Bid', 'Executed Contract', 'Image/Site Photo', 'Receipt/Invoice', 'Other'",
      "status": "Must be exactly one of these: 'Active' (if current or standard estimate/bid), 'Expired' (if dates clearly passed), or 'Superseded' (if it explicitly states it replaces an older document/version)",
      "short_summary": "A concise, 1-2 sentence high-level overview explaining what this document covers",
      "description": "A robust summary paragraph listing all key equipment, models, total pricing breakdown, line scopes, and searchable technical keywords found in the text",
      "is_recurring": "Must be exactly 'Yes' if this represents an ongoing subscription, utility, or maintenance service contract, or 'No' if it is a one-time charge/project",
      "billing_interval": "If recurring, indicate the period like 'Monthly', 'Quarterly', or 'Annually'. If not recurring, return 'N/A'",
      "interval_amount": "The recurring dollar amount charged per billing interval cycle (e.g. '$150.00'). If not recurring, extract the total estimated project cost",
      "deposit_required": "List the explicit dollar or percentage deposit amount required to start work if explicitly stated, otherwise return 'No'",
      "contract_date": "The document's creation date, proposal date, or date of execution/signature formatted as YYYY-MM-DD. If no date is recognizable, leave this string completely empty.",
      "term_end": "The explicit expiration or end date of the contract terms formatted as YYYY-MM-DD. Leave blank if not found.",
      "term_notice": "The contractual termination notice period length (e.g., '30 days', '60 days', 'None').",
      "cancel_deadline": "CRITICAL CALCULATION: Look at the extracted 'term_end' date and subtract the 'term_notice' requirement to determine the exact final day notice must be sent to prevent auto-renewal. Format as YYYY-MM-DD. If there is no specific notice period or no end date can be found, leave this completely empty."
    }
    """
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        document_part = Part.from_data(data=file_bytes, mime_type=mime_type)
        model = GenerativeModel("gemini-2.5-flash")
        response = model.generate_content([document_part, prompt])
        
        clean_text = response.text.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("\n", 1)[1].rsplit("\n", 1)[0]
        if clean_text.startswith("json"):
            clean_text = clean_text.split("json", 1)[1]
            
        return json.loads(clean_text.strip())
    except Exception as e:
        st.error(f"AI Extraction failed via Vertex: {str(e)}")
        return None

# ==========================================
# --- EXCEL GENERATION UTILITY ---
# ==========================================
def convert_df_to_excel(dataframe):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Contracts Report")
    return output.getvalue()

# ==========================================
# --- USER INTERFACE (STREAMLIT) ---
# ==========================================
st.set_page_config(page_title="AI Contract Database", layout="wide")
st.title("📂 Smart Project Contract & Estimate Database")

# --- Sidebar Upload Components ---
st.sidebar.header("➕ Bulk Document Upload")

uploaded_files = st.sidebar.file_uploader(
    "Drop your PDFs or Images here (Multiple allowed)", 
    type=["pdf", "jpg", "jpeg", "png"], 
    accept_multiple_files=True
)

if "bulk_ai_data" not in st.session_state:
    st.session_state.bulk_ai_data = {}
if "review_queue_index" not in st.session_state:
    st.session_state.review_queue_index = 0
if "last_upload_count" not in st.session_state:
    st.session_state.last_upload_count = 0

# Sync queue resets smoothly if files are completely removed or newly added
if uploaded_files:
    if len(uploaded_files) != st.session_state.last_upload_count:
        st.session_state.review_queue_index = 0
        st.session_state.last_upload_count = len(uploaded_files)
else:
    st.session_state.review_queue_index = 0
    st.session_state.last_upload_count = 0

# Process un-indexed files automatically
if uploaded_files:
    for f_item in uploaded_files:
        if f_item.name not in st.session_state.bulk_ai_data:
            file_path = os.path.abspath(os.path.join(UPLOAD_DIR, f_item.name))
            
            try:
                with open(file_path, "wb") as f:
                    f.write(f_item.getbuffer())
            except Exception as folder_err:
                st.error(f"📁 File System Error: Could not save '{f_item.name}'. Details: {str(folder_err)}")
                continue
                
            with st.sidebar.spinner(f"🤖 AI Scanning {f_item.name}..."):
                ext = f_item.name.lower().split(".")[-1]
                mime_type = "application/pdf" if ext == "pdf" else f"image/{'jpeg' if ext in ['jpg', 'jpeg'] else 'png'}"
                
                extracted_data = ai_analyze_file(file_path, mime_type)
                if extracted_data:
                    st.session_state.bulk_ai_data[f_item.name] = extracted_data
                else:
                    st.session_state.bulk_ai_data[f_item.name] = {
                        "project_name": "Pending Manual Review", "property_name": "", "vendor_name": "", 
                        "document_type": "Estimate/Bid", "status": "Active", "short_summary": "Manual entry required.", 
                        "description": "", "is_recurring": "No", "billing_interval": "N/A", 
                        "interval_amount": "N/A", "deposit_required": "No", "contract_date": "", 
                        "term_end": "", "term_notice": "None", "cancel_deadline": ""
                    }

# Review Form Block
if uploaded_files:
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📋 Review Extractions")
    
    file_options = [f.name for f in uploaded_files]
    
    if st.session_state.review_queue_index >= len(file_options):
        st.session_state.review_queue_index = max(0, len(file_options) - 1)

    selected_file_name = st.sidebar.selectbox(
        "Select file to verify:", 
        file_options, 
        index=st.session_state.review_queue_index
    )
    
    current_selection_idx = file_options.index(selected_file_name)
    if current_selection_idx != st.session_state.review_queue_index:
        st.session_state.review_queue_index = current_selection_idx
        st.rerun()
        
    current_data = st.session_state.bulk_ai_data.get(selected_file_name, {})
    
    p_init = current_data.get("project_name", "")
    prop_init = current_data.get("property_name", "")
    v_init = current_data.get("vendor_name", "")
    doc_types = ["Estimate/Bid", "Executed Contract", "Image/Site Photo", "Receipt/Invoice", "Other"]
    d_type_idx = doc_types.index(current_data.get("document_type", "Estimate/Bid")) if current_data.get("document_type", "Estimate/Bid") in doc_types else 0
    
    status_types = ["Active", "Expired", "Superseded"]
    status_idx = status_types.index(current_data.get("status", "Active")) if current_data.get("status", "Active") in status_types else 0
    
    short_init = current_data.get("short_summary", "")
    desc_init = current_data.get("description", "")
    rec_init = 1 if current_data.get("is_recurring", "No") == "Yes" else 0
    bill_init = current_data.get("billing_interval", "N/A")
    amt_init = current_data.get("interval_amount", "")
    dep_init = current_data.get("deposit_required", "No")
    notice_init = current_data.get("term_notice", "None")
    
    def parse_to_widget_date(date_str):
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else None
        except ValueError:
            return None

    c_date_parsed = parse_to_widget_date(current_data.get("contract_date", ""))
    end_date_parsed = parse_to_widget_date(current_data.get("term_end", ""))
    deadline_parsed = parse_to_widget_date(current_data.get("cancel_deadline", ""))

    with st.sidebar.form("upload_form", clear_on_submit=False):
        st.markdown(f"**Document Queue:** {st.session_state.review_queue_index + 1} of {len(file_options)}")
        st.markdown(f"**Editing Profile:** `{selected_file_name}`")
        
        project = st.text_input("Project / Task Name", value=p_init)
        property_name = st.text_input("Property / Location Name", value=prop_init)
        vendor = st.text_input("Vendor Name", value=v_init)
        doc_type = st.selectbox("Document Type", doc_types, index=d_type_idx)
        status = st.selectbox("Contract Lifecycle Status", status_types, index=status_idx)
        
        contract_date = st.date_input("Document / Execution Date", value=c_date_parsed if c_date_parsed else None)
        
        st.markdown("---")
        short_summary = st.text_input("Short Summary Statement", value=short_init)
        description = st.text_area("Detailed Scope & Keywords", value=desc_init, height=100)
        
        st.markdown("---")
        is_recurring = st.radio("Is this a Recurring Service / Utility?", ["No", "Yes"], index=rec_init)
        billing_interval = st.text_input("Billing Interval (e.g., Monthly, N/A)", value=bill_init)
        interval_amount = st.text_input("Rate / Interval Billing Cost", value=amt_init)
        deposit_required = st.text_input("Deposit Requirement Status", value=dep_init)
        
        st.markdown("---")
        # FIXED: Restored complete markdown call with proper closure
        st.markdown("### 🗓️ Contract Term & Cancellation Dates")
        start_date = st.date_input("Term Start Date", value=None)
        
        end_date = st.date_input("Term Expiration Date", value=end_date_parsed if end_date_parsed else None)
        auto_renew = st.radio("Auto-Renew Active?", ["No", "Yes"], index=0)
        term_notice = st.text_input("Notice Needed (e.g., 30 Days)", value=notice_init)
        cancel_deadline = st.date_input("AI Calculated Cancellation Due Date", value=deadline_parsed if deadline_parsed else None)
        
        submit = st.form_submit_button("Commit and Advance Queue ➡️")

    if submit:
        start_str = start_date.strftime("%Y-%m-%d") if start_date else "N/A"
        end_str = end_date.strftime("%Y-%m-%d") if end_date else "N/A"
        c_date_str = contract_date.strftime("%Y-%m-%d") if contract_date else "N/A"
        deadline_str = cancel_deadline.strftime("%Y-%m-%d") if cancel_deadline else "N/A"
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            INSERT INTO contracts (
                project_name, property_name, vendor_name, document_type, status, description, 
                short_summary, is_recurring, billing_interval, interval_amount, deposit_required, contract_date,
                file_name, term_start, term_end, auto_renew, term_notice, cancel_deadline, date_added
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project, property_name, vendor, doc_type, status, description, 
            short_summary, is_recurring, billing_interval, interval_amount, deposit_required, c_date_str,
            selected_file_name, start_str, end_str, auto_renew, term_notice, deadline_str,
            datetime.now().strftime("%Y-%m-%d")
        ))
        conn.commit()
        conn.close()
        
        if st.session_state.review_queue_index + 1 < len(file_options):
            st.session_state.review_queue_index += 1
            st.rerun()
        else:
            st.sidebar.success("🎉 Final document committed! All files processed.")
            st.session_state.review_queue_index = 0
            st.session_state.bulk_ai_data = {}
            st.rerun()

# --- Search Section ---
st.header("🔍 Cross-Project Search Dashboard")

s_col1, s_col2, s_col3, s_col4 = st.columns(4)
with s_col1:
    search_keyword = st.text_input("Search by Keyword or Summary")
with s_col2:
    search_vendor = st.text_input("Filter by Vendor Name")
with s_col3:
    search_property = st.text_input("Filter by Property Name")
with s_col4:
    search_status = st.selectbox("Filter by Lifecycle Status", ["All Records", "Active", "Expired", "Superseded"])

# Load and query records dynamically from database
conn = sqlite3.connect(DB_FILE)
query = "SELECT * FROM contracts WHERE 1=1"
params = []

if search_keyword:
    query += " AND (project_name LIKE ? OR description LIKE ? OR short_summary LIKE ? OR document_type LIKE ?)"
    like_word = f"%{search_keyword}%"
    params.extend([like_word, like_word, like_word, like_word])
if search_vendor:
    query += " AND vendor_name LIKE ?"
    params.append(f"%{search_vendor}%")
if search_property:
    query += " AND property_name LIKE ?"
    params.append(f"%{search_property}%")
if search_status != "All Records":
    query += " AND status = ?"
    params.append(search_status)

df = pd.read_sql_query(query, conn, params=params)
conn.close()

# --- Report Export Dashboard Integration ---
if not df.empty:
    df_clean_report = df.copy()
    df_clean_report.columns = [
        "ID", "Project Name", "Property Location", "Vendor Name", "Document Type", "Lifecycle Status", 
        "Detailed Scope Description", "Short Summary", "Is Recurring", "Billing Cycle", "Interval Amount/Cost", 
        "Deposit Status", "Document Date", "File Name Reference", "Term Window Start", "Term Expiration End", 
        "Auto Renew Clause", "Notice Window Days", "Cancellation Notice Deadline", "System Entry Date"
    ]
    
    excel_data_stream = convert_df_to_excel(df_clean_report)
    current_timestamp = datetime.now().strftime("%Y-%m-%d")
    report_filename = f"contracts_export_{current_timestamp}.xlsx"
    
    st.download_button(
        label="📊 Export Current Results to Excel (.xlsx)",
        data=excel_data_stream,
        file_name=report_filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    st.markdown("---")

# Render Search Results Expandable Dashboard Cards
if not df.empty:
    df.columns = [
        "ID", "Project/Task", "Property", "Vendor", "Type", "Status", "Description", 
        "Short Summary", "Recurring", "Billing Interval", "Interval Amount", "Deposit Status", "Doc Date",
        "File Name", 'Term Start', "Term End", "Auto-Renew", "Notice Period", "Cancel Deadline", "Date Added"
    ]
    
    for index, row in df.iterrows():
        status_indicator = "🟢" if row["Status"] == "Active" else "🔴" if row["Status"] == "Expired" else "🟡 [SUPERSEDED]"
        header_title = f"{status_indicator} {row['Project/Task']} — {row['Vendor']} ({row['Type']})"
        if row["Property"]:
            header_title = f"📍 [{row['Property']}] {status_indicator} {row['Project/Task']} — {row['Vendor']}"
            
        with st.expander(header_title):
            edit_key = f"edit_active_{row['ID']}"
            if edit_key not in st.session_state:
                st.session_state[edit_key] = False
                
            if not st.session_state[edit_key]:
                if row["Status"] == "Expired":
                    st.error("🚨 WARNING: This contract has expired and is no longer contractually legally binding.")
                elif row["Status"] == "Superseded":
                    st.warning("⚠️ ATTENTION: This document has been replaced by an upgraded or newer project version profile entry.")
                    
                st.markdown(f"**Quick Overview:** *{row['Short Summary']}*")
                st.markdown("---")
                
                c_left, c_right = st.columns(2)
                with c_left:
                    st.markdown(f"**Detailed Scope & Specifications:**")
                    st.write(row["Description"])
                    st.markdown(f"**File Registry Link:** `{row['File Name']}`")
                    file_path = os.path.join(UPLOAD_DIR, str(row["File Name"]))
                    if os.path.exists(file_path):
                        with open(file_path, "rb") as file:
                            st.download_button(label="📥 Download Original Document", data=file, file_name=str(row["File Name"]), key=f"dl_{row['ID']}")
                
                with c_right:
                    st.markdown("📊 **Operational & Financial Status:**")
                    m1, m2, m3, m4 = st.columns(4)
                    with m1:
                        st.metric(label="Record Status", value=row["Status"])
                    with m2:
                        st.metric(label="Billing Cost/Rate", value=row["Interval Amount"])
                    with m3:
                        st.metric(label="Billing Cycle", value=f"{row['Recurring']} ({row['Billing Interval']})")
                    with m4:
                        st.metric(label="Deposit Req.", value=row["Deposit Status"])
                    
                    st.markdown("🔒 **Critical Dates & Renewal Terms:**")
                    st.write(f"• **Document Execution Date:** {row['Doc Date']}")
                    st.write(f"• **Active Windows:** {row['Term Start']} to {row['Term End']}")
                    st.write(f"• **Auto-Renewal Clause:** {row['Auto-Renew']} (Requires {row['Notice Period']} notice)")
                    
                    if row["Cancel Deadline"] != "N/A" and row["Cancel Deadline"] != "":
                        st.error(f"⚠️ **Notice Cancellation Deadline:** Notice must be sent before **{row['Cancel Deadline']}**")
                    else:
                        st.write("• **Notice Cancellation Deadline:** N/A")
                
                st.markdown("---")
                btn_col1, btn_col2, btn_spacer = st.columns([1, 1, 5])
                with btn_col1:
                    if st.button("✏️ Edit Record", key=f"trigger_edit_{row['ID']}"):
                        st.session_state[edit_key] = True
                        st.rerun()
                with btn_col2:
                    if st.button("🗑️ Delete Duplicate", key=f"trigger_del_{row['ID']}", type="secondary"):
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        c.execute("DELETE FROM contracts WHERE id = ?", (row["ID"],))
                        conn.commit()
                        conn.close()
                        st.success("Entry cleanly removed from index tracker.")
                        st.rerun()
                        
            else:
                st.markdown("### 🛠️ Edit Contract Fields")
                with st.form(key=f"edit_form_panel_{row['ID']}"):
                    e_col1, e_col2 = st.columns(2)
                    with e_col1:
                        up_project = st.text_input("Project Name", value=row["Project/Task"])
                        up_property = st.text_input("Property / Location", value=row["Property"])
                        up_vendor = st.text_input("Vendor Name", value=row['Vendor'])
                        up_status = st.selectbox("Lifecycle Status", ["Active", "Expired", "Superseded"], index=["Active", "Expired", "Superseded"].index(row["Status"]))
                        up_short = st.text_input("Short Summary", value=row["Short Summary"])
                        up_desc = st.text_area("Detailed Scope & Keywords", value=row["Description"], height=100)
                    with e_col2:
                        up_amt = st.text_input("Rate / Billing Cost", value=row["Interval Amount"])
                        up_interval = st.text_input("Billing Interval", value=row["Billing Interval"])
                        up_deposit = st.text_input("Deposit Requirement", value=row["Deposit Status"])
                        up_doc_date = st.text_input("Document Date (YYYY-MM-DD)", value=row["Doc Date"])
                        up_deadline = st.text_input("Cancellation Deadline Date (YYYY-MM-DD)", value=row["Cancel Deadline"])
                    
                    f_col1, f_col2, f_spacer = st.columns([1.5, 1.5, 5])
                    with f_col1:
                        save_changes = st.form_submit_button("💾 Save Corrections")
                    with f_col2:
                        cancel_changes = st.form_submit_button("❌ Cancel")
                        
                if save_changes:
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    c.execute("""
                        UPDATE contracts 
                        SET project_name = ?, property_name = ?, vendor_name = ?, status = ?, short_summary = ?, 
                            description = ?, interval_amount = ?, billing_interval = ?, 
                            deposit_required = ?, contract_date = ?, cancel_deadline = ? 
                        WHERE id = ?
                    """, (
                        up_project, up_property, up_vendor, up_status, up_short, 
                        up_desc, up_amt, up_interval, up_deposit, 
                        up_doc_date, up_deadline, row["ID"]
                    ))
                    conn.commit()
                    conn.close()
                    st.session_state[edit_key] = False
                    st.success("Changes permanently written down.")
                    st.rerun()
                    
                if cancel_changes:
                    st.session_state[edit_key] = False
                    st.rerun()
else:
    st.info("No matching records found.")