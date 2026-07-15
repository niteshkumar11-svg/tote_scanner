import os
import streamlit as st
import gspread
import pandas as pd
from datetime import datetime

# ─── Config ──────────────────────────────────────────────────────────────────
SHEET_ID = "1XZDSao2M3dPqrCbmIx_EZaps6aBPNlO9muEe9owfA2U"
SHEET_GID = 958256319
BOX_ID_COL = "Box ID"
SOURCE_FC_COL = "Source FC"
# Resolve creds path relative to this script file, regardless of launch directory
SERVICE_ACCOUNT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "creds.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
LOG_HEADERS = ["Timestamp", "Box ID", "Source FC", "Status"]


# ─── Google client (cached across reruns) ────────────────────────────────────
# On Streamlit Cloud: reads from st.secrets["gcp_service_account"]
# Locally: falls back to creds.json file
@st.cache_resource
def get_gc():
    if "gcp_service_account" in st.secrets:
        return gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    return gspread.service_account(filename=SERVICE_ACCOUNT_FILE, scopes=SCOPES)


@st.cache_data(ttl=300, show_spinner="Loading source data...")
def load_source_sheet() -> pd.DataFrame:
    ws = next(
        (w for w in get_gc().open_by_key(SHEET_ID).worksheets() if w.id == SHEET_GID),
        None,
    )
    if ws is None:
        raise ValueError(f"Source sheet (gid={SHEET_GID}) not found.")
    values = ws.get_all_values()
    if len(values) < 2:
        return pd.DataFrame()
    # Row 1 is a title row; actual column headers are on row 2 (index 1)
    df = pd.DataFrame(values[2:], columns=values[1])
    df.columns = df.columns.str.strip()
    return df


def get_or_create_log_ws(spreadsheet, dept: str):
    try:
        return spreadsheet.worksheet(dept)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=dept, rows=5000, cols=len(LOG_HEADERS))
        ws.append_row(LOG_HEADERS)
        return ws


def log_to_sheet(dept: str, box_id: str, source_fc: str, status: str):
    spreadsheet = get_gc().open_by_key(SHEET_ID)
    ws = get_or_create_log_ws(spreadsheet, dept)
    ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), box_id, source_fc, status])


def _find_col(df: pd.DataFrame, name: str) -> str:
    """Case-insensitive column lookup; raises with helpful message if missing."""
    for col in df.columns:
        if col.strip().lower() == name.strip().lower():
            return col
    raise KeyError(f"Column '{name}' not found. Sheet has: {list(df.columns)}")


def lookup_box(box_id: str, dept: str, df: pd.DataFrame) -> dict:
    box_col = _find_col(df, BOX_ID_COL)
    src_col  = _find_col(df, SOURCE_FC_COL)
    match = df[df[box_col].astype(str).str.strip().str.upper() == box_id.upper()]

    if match.empty:
        return {
            "box_id": box_id, "source_fc": "—", "status": "NOT_FOUND",
            "message": f"Box ID <b>{box_id}</b> not found in source sheet.",
        }

    source_fc = str(match.iloc[0][src_col]).strip()
    is_ulu = source_fc.upper().startswith("ULU")

    if dept == "RC":
        ok = is_ulu
        err_msg = f"<b>{box_id}</b> — Source FC: <b>{source_fc}</b> — NOT a ULU FC. Cannot go to RC!"
        ok_msg  = f"<b>{box_id}</b> — Source FC: <b>{source_fc}</b> — Valid for RC ✓"
    else:
        ok = not is_ulu
        err_msg = f"<b>{box_id}</b> — Source FC: <b>{source_fc}</b> — ULU FC detected! Should go to RC, not Inbound."
        ok_msg  = f"<b>{box_id}</b> — Source FC: <b>{source_fc}</b> — Valid for Inbound ✓"

    return {
        "box_id": box_id, "source_fc": source_fc,
        "status": "OK" if ok else "ERROR",
        "message": ok_msg if ok else err_msg,
    }


# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Tote Scanner", page_icon="📦", layout="centered")

st.markdown("""
<style>
/* ── Department selection buttons ── */
.dept-btn-row .stButton > button {
    height: 160px !important;
    font-size: 1.9rem !important;
    font-weight: 800 !important;
    border-radius: 14px !important;
    letter-spacing: 0.04em;
}
/* ── Scan result banners ── */
.res-ok   { background:#d4edda; color:#155724; padding:18px 20px; border-radius:10px;
            font-size:1.2rem; font-weight:600; border-left:7px solid #28a745; margin:8px 0; }
.res-err  { background:#f8d7da; color:#721c24; padding:18px 20px; border-radius:10px;
            font-size:1.2rem; font-weight:600; border-left:7px solid #dc3545; margin:8px 0; }
.res-warn { background:#fff3cd; color:#856404; padding:18px 20px; border-radius:10px;
            font-size:1.2rem; font-weight:600; border-left:7px solid #ffc107; margin:8px 0; }
/* ── Back button — keep it small ── */
.back-btn .stButton > button {
    font-size: 0.85rem !important;
    padding: 4px 12px !important;
}
</style>
""", unsafe_allow_html=True)

# ─── Error popup dialog ──────────────────────────────────────────────────────
@st.dialog("⚠️ Wrong Box Scanned!")
def _error_popup(message: str):
    st.markdown(f"<div style='font-size:1.1rem'>{message}</div>", unsafe_allow_html=True)
    st.markdown("")
    if st.button("Continue", use_container_width=True, type="primary"):
        st.session_state.error_popup = None
        st.rerun()


# ─── Session state ────────────────────────────────────────────────────────────
for key, default in [("dept", None), ("scan_log", []), ("last_result", None), ("error_popup", None)]:
    if key not in st.session_state:
        st.session_state[key] = default


# ════════════════════════════════════════════════════════════════════════════
# LANDING PAGE — department selection
# ════════════════════════════════════════════════════════════════════════════
if st.session_state.dept is None:
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align:center'>📦 Tote Scanner</h1>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align:center; color:gray; margin-bottom:40px'>Select department to begin scanning</h4>",
                unsafe_allow_html=True)

    st.markdown('<div class="dept-btn-row">', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        if st.button("RC", use_container_width=True, type="primary"):
            st.session_state.dept = "RC"
            st.session_state.scan_log = []
            st.session_state.last_result = None
            st.rerun()
    with col2:
        if st.button("Inbound", use_container_width=True, type="primary"):
            st.session_state.dept = "Inbound"
            st.session_state.scan_log = []
            st.session_state.last_result = None
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════
# SCAN PAGE
# ════════════════════════════════════════════════════════════════════════════
else:
    dept = st.session_state.dept

    # Header row
    col_h, col_back = st.columns([5, 1])
    with col_h:
        st.markdown(f"<h2 style='margin-bottom:4px'>📦 {dept} — Tote Scanner</h2>",
                    unsafe_allow_html=True)
    with col_back:
        st.markdown('<div class="back-btn">', unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("← Back"):
            st.session_state.dept = None
            st.session_state.scan_log = []
            st.session_state.last_result = None
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    if dept == "RC":
        st.info("RC mode — only **ULU** source FCs are valid.", icon="ℹ️")
    else:
        st.info("Inbound mode — **ULU** source FCs will be flagged as errors.", icon="ℹ️")

    st.divider()

    # ── Scan form ──────────────────────────────────────────────────────────
    # Barcode scanners send the code followed by Enter — the form auto-submits on Enter.
    with st.form("scan_form", clear_on_submit=True):
        box_input = st.text_input(
            "Box ID",
            placeholder="Scan barcode — auto-submits on Enter...",
            label_visibility="collapsed",
        )
        st.form_submit_button("Submit", use_container_width=True, type="primary")

    # Auto-focus the input after every rerun so the scanner can go straight in
    st.components.v1.html("""
    <script>
        setTimeout(function () {
            const inputs = window.parent.document.querySelectorAll('input[type="text"]');
            if (inputs.length > 0) inputs[0].focus();
        }, 150);
    </script>
    """, height=0)

    # ── Process scan ──────────────────────────────────────────────────────
    if box_input.strip():
        try:
            df = load_source_sheet()
            result = lookup_box(box_input.strip(), dept, df)
            result["time"] = datetime.now().strftime("%H:%M:%S")

            log_to_sheet(dept, result["box_id"], result["source_fc"], result["status"])

            st.session_state.scan_log.insert(0, result)

            if result["status"] == "OK":
                st.session_state.last_result = result
                st.session_state.error_popup = None
            else:
                st.session_state.error_popup = result["message"]
                st.session_state.last_result = None

        except FileNotFoundError:
            st.error(f"Credentials file `{SERVICE_ACCOUNT_FILE}` not found.", icon="🔑")
        except Exception as e:
            st.error(f"Error: {e}", icon="⚠️")

    # ── Error popup (blocks scan until user clicks Continue) ──────────────
    if st.session_state.error_popup:
        _error_popup(st.session_state.error_popup)

    # ── Last result banner (OK scans only) ────────────────────────────────
    if st.session_state.last_result:
        r = st.session_state.last_result
        st.markdown(f'<div class="res-ok">{r["message"]}</div>', unsafe_allow_html=True)

    # ── Scan log ──────────────────────────────────────────────────────────
    if st.session_state.scan_log:
        st.divider()
        ok_n  = sum(1 for e in st.session_state.scan_log if e["status"] == "OK")
        err_n = sum(1 for e in st.session_state.scan_log if e["status"] == "ERROR")
        nf_n  = sum(1 for e in st.session_state.scan_log if e["status"] == "NOT_FOUND")

        col_l, col_clr = st.columns([4, 1])
        with col_l:
            st.markdown(
                f"**Scan Log** — {len(st.session_state.scan_log)} scanned &nbsp;|&nbsp; "
                f"✅ {ok_n} &nbsp;❌ {err_n} &nbsp;⚠️ {nf_n}",
                unsafe_allow_html=True,
            )
        with col_clr:
            if st.button("Clear Log", use_container_width=True):
                st.session_state.scan_log = []
                st.session_state.last_result = None
                st.rerun()

        log_df = pd.DataFrame(
            [{"Time": e["time"], "Box ID": e["box_id"],
              "Source FC": e["source_fc"], "Status": e["status"]}
             for e in st.session_state.scan_log]
        )

        def _color(val):
            return {
                "OK":        "background-color:#d4edda;color:#155724",
                "ERROR":     "background-color:#f8d7da;color:#721c24",
                "NOT_FOUND": "background-color:#fff3cd;color:#856404",
            }.get(val, "")

        st.dataframe(
            log_df.style.map(_color, subset=["Status"]),
            use_container_width=True,
            hide_index=True,
        )
