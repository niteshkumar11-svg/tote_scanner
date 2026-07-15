import streamlit as st
import gspread
import pandas as pd
from datetime import datetime

# ─── Config ──────────────────────────────────────────────────────────────────
SHEET_ID = "1XZDSao2M3dPqrCbmIx_EZaps6aBPNlO9muEe9owfA2U"
SHEET_GID = 958256319
BOX_ID_COL = "Box ID"
SOURCE_FC_COL = "Source FC"
# Place your Google service account JSON file in the same folder as this script
SERVICE_ACCOUNT_FILE = "creds.json"
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]


# ─── Sheet loader (cached 5 min) ─────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Fetching sheet data...")
def load_sheet() -> pd.DataFrame:
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    spreadsheet = gc.open_by_key(SHEET_ID)
    worksheets = spreadsheet.worksheets()
    ws = next((w for w in worksheets if w.id == SHEET_GID), None)
    if ws is None:
        raise ValueError(f"Sheet with gid={SHEET_GID} not found.")
    records = ws.get_all_records()
    return pd.DataFrame(records)


def lookup_box(box_id: str, dept: str, df: pd.DataFrame) -> dict:
    """Returns a result dict with keys: box_id, source_fc, status, message"""
    match = df[df[BOX_ID_COL].astype(str).str.strip().str.upper() == box_id.upper()]

    if match.empty:
        return {
            "box_id": box_id,
            "source_fc": "—",
            "status": "NOT_FOUND",
            "message": f"Box ID **{box_id}** not found in source sheet.",
        }

    source_fc = str(match.iloc[0][SOURCE_FC_COL]).strip()
    is_ulu = source_fc.upper().startswith("ULU")

    if dept == "RC":
        if is_ulu:
            status = "OK"
            message = f"✅ **{box_id}** — Source FC: **{source_fc}** — Valid for RC"
        else:
            status = "ERROR"
            message = f"❌ **{box_id}** — Source FC: **{source_fc}** — NOT a ULU FC. This box cannot go to RC!"
    else:  # Inbound
        if not is_ulu:
            status = "OK"
            message = f"✅ **{box_id}** — Source FC: **{source_fc}** — Valid for Inbound"
        else:
            status = "ERROR"
            message = f"❌ **{box_id}** — Source FC: **{source_fc}** — ULU FC detected. This box should go to RC, not Inbound!"

    return {"box_id": box_id, "source_fc": source_fc, "status": status, "message": message}


# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Tote Scanner", page_icon="📦", layout="centered")

st.markdown(
    """
    <style>
    .result-ok    { background:#d4edda; color:#155724; padding:16px; border-radius:8px;
                    font-size:1.15rem; font-weight:600; border-left:6px solid #28a745; }
    .result-error { background:#f8d7da; color:#721c24; padding:16px; border-radius:8px;
                    font-size:1.15rem; font-weight:600; border-left:6px solid #dc3545; }
    .result-warn  { background:#fff3cd; color:#856404; padding:16px; border-radius:8px;
                    font-size:1.15rem; font-weight:600; border-left:6px solid #ffc107; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📦 Tote Scanner")

# ─── Session state init ───────────────────────────────────────────────────────
if "scan_log" not in st.session_state:
    st.session_state.scan_log = []
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "active_dept" not in st.session_state:
    st.session_state.active_dept = None


# ─── Department selector ──────────────────────────────────────────────────────
st.subheader("1 · Select Department")
dept = st.radio("Department", ["RC", "Inbound"], horizontal=True, label_visibility="collapsed")

# Reset log when department changes mid-session
if st.session_state.active_dept != dept:
    st.session_state.active_dept = dept
    st.session_state.scan_log = []
    st.session_state.last_result = None

if dept == "RC":
    st.info("RC mode: only boxes with **ULU** source FC are valid.", icon="ℹ️")
else:
    st.info("Inbound mode: boxes with **ULU** source FC will be flagged as errors.", icon="ℹ️")

st.divider()

# ─── Scan input ───────────────────────────────────────────────────────────────
st.subheader("2 · Scan Totes")

with st.form("scan_form", clear_on_submit=True):
    box_input = st.text_input(
        "Box ID",
        placeholder="Scan barcode or type Box ID and press Enter...",
        label_visibility="collapsed",
    )
    submitted = st.form_submit_button("Scan", use_container_width=True, type="primary")

if submitted and box_input.strip():
    try:
        df = load_sheet()
        result = lookup_box(box_input.strip(), dept, df)
        result["time"] = datetime.now().strftime("%H:%M:%S")
        st.session_state.scan_log.insert(0, result)
        st.session_state.last_result = result
    except FileNotFoundError:
        st.error(
            f"Service account file `{SERVICE_ACCOUNT_FILE}` not found. "
            "Place it in the same folder as this script.",
            icon="🔑",
        )
    except Exception as e:
        st.error(f"Error: {e}", icon="⚠️")

# ─── Last scan result (prominent) ────────────────────────────────────────────
if st.session_state.last_result:
    r = st.session_state.last_result
    css = {"OK": "result-ok", "ERROR": "result-error", "NOT_FOUND": "result-warn"}[r["status"]]
    # Convert markdown bold to HTML for the styled box
    msg_html = r["message"].replace("**", "<b>", 1)
    while "**" in msg_html:
        msg_html = msg_html.replace("**", "</b>", 1).replace("**", "<b>", 1)
    st.markdown(f'<div class="{css}">{msg_html}</div>', unsafe_allow_html=True)
    st.markdown("")

# ─── Scan log table ───────────────────────────────────────────────────────────
if st.session_state.scan_log:
    st.divider()
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        total = len(st.session_state.scan_log)
        ok_count = sum(1 for e in st.session_state.scan_log if e["status"] == "OK")
        err_count = sum(1 for e in st.session_state.scan_log if e["status"] == "ERROR")
        nf_count = sum(1 for e in st.session_state.scan_log if e["status"] == "NOT_FOUND")
        st.subheader(f"Scan Log — {total} scanned | ✅ {ok_count} | ❌ {err_count} | ⚠️ {nf_count}")
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Clear Log", use_container_width=True):
            st.session_state.scan_log = []
            st.session_state.last_result = None
            st.rerun()

    log_df = pd.DataFrame(
        [{"Time": e["time"], "Box ID": e["box_id"], "Source FC": e["source_fc"], "Status": e["status"]}
         for e in st.session_state.scan_log]
    )

    def _color_status(val):
        if val == "OK":
            return "background-color:#d4edda; color:#155724"
        if val == "ERROR":
            return "background-color:#f8d7da; color:#721c24"
        return "background-color:#fff3cd; color:#856404"

    styled = log_df.style.map(_color_status, subset=["Status"])
    st.dataframe(styled, use_container_width=True, hide_index=True)
