import streamlit as st
import requests
import json
import os
import pandas as pd
from datetime import date, datetime, timedelta
import announcements_utils

# --- Page Config ---
st.set_page_config(layout="wide")
st.title("Dashboard")

# --- Load External Configurations ---
def get_auth_cookie():
    try:
        with open("web_cookie.txt", "r") as f:
            return f.read().strip()
    except Exception as e:
        st.error(f"Error loading web_cookie.txt: {e}")
        return ""

STOCKSCANS_COOKIE = get_auth_cookie()

# --- Session State Initialization ---
states = {
    "sector_data": None,
    "selected_sectors": [],
    "index_data": None,
    "selected_indices": []
}
for key, val in states.items():
    if key not in st.session_state:
        st.session_state[key] = val

# --- Global Helpers ---
def clean_scores(scores):
    """Cleans historicScores data for st.column_config.LineChartColumn."""
    cleaned = []
    if isinstance(scores, list):
        recent_scores = scores[-30:] if len(scores) > 30 else scores
        for s in recent_scores:
            if isinstance(s, list) and len(s) > 1:
                try:
                    cleaned.append(float(s[1])) 
                except (ValueError, TypeError):
                    pass
            elif isinstance(s, (int, float)):
                cleaned.append(float(s))
    return cleaned

def fetch_constituents(name, scan_type="Industry"):
    """Fetches stock constituents for a given sector or index."""
    url = "https://www.stockscans.in/api/company/market-scans/constituents"
    payload = json.dumps({
        "name": name,
        "marketScanType": scan_type,
        "timePeriod": "Latest"
    })
    headers = {
        'accept': 'application/json',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'origin': 'https://www.stockscans.in',
        'priority': 'u=1, i',
        'referer': 'https://www.stockscans.in/market-scans',
        'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Cookie': STOCKSCANS_COOKIE
    }
    try:
        response = requests.request("POST", url, headers=headers, data=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Error fetching constituents for {name}: {e}")
        return None

def get_status_color(val):
    if not isinstance(val, str): return ""
    v = val.lower()
    if "outperforming" in v: return "background-color: #ccffcc; color: #006600"
    if "accumulating" in v: return "background-color: #cce5ff; color: #004085"
    if "consolidating" in v: return "background-color: #ffe5cc; color: #856404"
    if "underperforming" in v: return "background-color: #ffcccc; color: #cc0000"
    return ""

def render_rotation_tab(tab_name, data_key, selection_key, scan_type):
    st.header(tab_name)
    st.text("Outperforming → Strength is visible and persistent")
    st.text("Accumulating → Early signs of strength are emerging")
    st.text("Consolidating → Momentum is slowing down")
    st.text("Underperforming → Persistent weakness remains")

    if st.button(f"Fetch {tab_name} Data"):
        url = "https://www.stockscans.in/api/company/market-scans/table"
        payload = json.dumps({"marketScanType": scan_type, "timePeriod": "Latest"})
        headers = {
          'accept': 'application/json',
          'accept-language': 'en-US,en;q=0.9',
          'content-type': 'application/json',
          'origin': 'https://www.stockscans.in',
          'priority': 'u=1, i',
          'referer': 'https://www.stockscans.in/market-scans',
          'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
          'sec-ch-ua-mobile': '?0',
          'sec-ch-ua-platform': '"Windows"',
          'sec-fetch-dest': 'empty',
          'sec-fetch-mode': 'cors',
          'sec-fetch-site': 'same-origin',
          'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
          'Cookie': STOCKSCANS_COOKIE
        }
        with st.spinner("Fetching..."):
            try:
                response = requests.request("POST", url, headers=headers, data=payload)
                response.raise_for_status()
                data = response.json()
                if data and "table" in data:
                    df = pd.DataFrame(data["table"])
                    if "historicScores" in df.columns:
                        df["historicScores"] = df["historicScores"].apply(clean_scores)
                    if "score" in df.columns:
                        df = df.sort_values(by="score", ascending=False)
                    st.session_state[data_key] = df
                    st.session_state[selection_key] = []
                else:
                    st.warning("No data found.")
            except Exception as e:
                st.error(f"Error: {e}")

    if st.session_state[data_key] is not None:
        df = st.session_state[data_key]
        status_col = next((c for c in df.columns if c.lower() == "status"), None)
        display_df = df.style.map(get_status_color, subset=[status_col]) if status_col else df
        event = st.dataframe(
            display_df,
            column_config={"historicScores": st.column_config.LineChartColumn("Historic Scores (1M)", width="medium")},
            use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row", key=f"{data_key}_table"
        )
        if event.selection.rows:
            st.session_state[selection_key] = df.iloc[event.selection.rows]["name"].tolist()
        else:
            st.session_state[selection_key] = []
    else:
        st.info(f"Click 'Fetch {tab_name} Data' to load.")

def render_constituents_tab(header, selection_key, scan_type):
    st.header(header)
    selected = st.session_state.get(selection_key, [])
    if selected:
        st.write(f"Aggregating data for: {', '.join(selected)}")
        all_dfs = []
        progress = st.progress(0)
        for i, name in enumerate(selected):
            data = fetch_constituents(name, scan_type=scan_type)
            if data and "table" in data:
                sdf = pd.DataFrame(data["table"])
                if "historicScores" in sdf.columns:
                    sdf["historicScores"] = sdf["historicScores"].apply(clean_scores)
                sdf["Source Name"] = name
                all_dfs.append(sdf)
            progress.progress((i + 1) / len(selected))
        progress.empty()

        if all_dfs:
            final_df = pd.concat(all_dfs, ignore_index=True)
            id_col = next((c for c in final_df.columns if c.lower() in ["companyid", "symbol", "id"]), None)
            if id_col:
                ids_string = ", ".join(map(str, final_df[id_col].dropna().unique().tolist()))
                st.subheader("Copy Identifiers")
                copy_html = f"""<button id="copyBtn" style="background-color:#007bff;color:white;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;">Copy IDs</button>
                <script>document.getElementById('copyBtn').onclick=function(){{navigator.clipboard.writeText('{ids_string}').then(function(){{const b=document.getElementById('copyBtn');b.innerText='Copied!';b.style.backgroundColor='#28a745';setTimeout(function(){{b.innerText='Copy IDs';b.style.backgroundColor='#007bff';}},2000);}});}};</script>"""
                st.components.v1.html(copy_html, height=50)
                st.code(ids_string, language="")
                final_df["TV Link"] = "https://in.tradingview.com/chart/?symbol=" + final_df[id_col].astype(str)

            cols = ["Source Name"]
            if "TV Link" in final_df.columns: cols.append("TV Link")
            cols += [c for c in final_df.columns if c not in cols]
            st.dataframe(final_df[cols], use_container_width=True, hide_index=True, key=f"{selection_key}_details_table",
                column_config={"historicScores": st.column_config.LineChartColumn("Historic Scores (1M)", width="medium"), "TV Link": st.column_config.LinkColumn("TradingView", display_text="Open Chart")})
    else:
        st.info("Select items in the rotation tab first.")

# --- Tabs ---
tabs = st.tabs(["Sector Rotation", "Sector Constituents", "Index Rotation", "Index Constituents", "Corp Announcements", "Screeners"])
t_sec, t_sec_det, t_ind, t_ind_det, t_ann, t_scr = tabs

with t_sec: render_rotation_tab("Sector Rotation", "sector_data", "selected_sectors", "Industry")
with t_sec_det: render_constituents_tab("Sector Constituents", "selected_sectors", "Industry")
with t_ind: render_rotation_tab("Index Rotation", "index_data", "selected_indices", "Index")
with t_ind_det: render_constituents_tab("Index Constituents", "selected_indices", "Index")

with t_ann:
    st.header("Corporate Announcements")
    c1, c2 = st.columns(2)
    with c1: d_from = st.date_input("From Date", date.today())
    with c2: d_to = st.date_input("To Date", date.today())
    if 'bse_data' not in st.session_state: st.session_state['bse_data'] = pd.DataFrame()
    if st.button("Fetch Announcements"):
        with st.spinner("Fetching..."):
            st.session_state['bse_data'] = announcements_utils.get_bse_announcements(d_from, d_to)
            st.session_state['bse_fetched'] = True
    bse_df = st.session_state['bse_data']
    if not bse_df.empty:
        st.success(f"Found {len(bse_df)} announcements.")
        types = ["All"] + sorted(bse_df['TYPE'].unique().tolist())
        sel_type = st.selectbox("Filter Type", types)
        disp_bse = bse_df if sel_type == "All" else bse_df[bse_df['TYPE'] == sel_type]
        dl_path = st.text_input("Local Download Folder Path")
        if st.button("Download PDFs"):
            if dl_path:
                path = dl_path.strip().strip('"').strip("'")
                if not os.path.exists(path): os.makedirs(path)
                count, errs = announcements_utils.download_pdfs(disp_bse, path)
                if count > 0: st.success(f"Downloaded {count} files.")
                for e in errs: st.error(e)
            else: st.error("Enter path.")
        st.dataframe(disp_bse, column_config={"LINK": st.column_config.LinkColumn("PDF", display_text="Open")}, use_container_width=True, hide_index=True, key="bse_table")
    elif st.session_state.get('bse_fetched'): st.info("No announcements found.")

with t_scr:
    st.header("Imp Screeners")
    st.markdown("- [Go to Markets Dashboard](https://www.stockscans.in/market-scans/dashboard)")
    st.write("Quick access to Chartink screeners and dashboards:")
    links = [("HVY Screener", "hvy-atfinallynitin"), ("MARS stocks", "159858"), ("Market Breadth Check1", "163999"), ("Market Breadth Check2", "149096")]
    for name, path in links:
        url = f"https://chartink.com/{'screener' if '-' in path else 'dashboard'}/{path}"
        st.markdown(f"- [{name}]({url})")
