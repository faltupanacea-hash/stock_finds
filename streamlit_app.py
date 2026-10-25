import streamlit as st
import requests
import json
import os
import pandas as pd
from datetime import date, datetime, timedelta
import announcements_utils
import base64

try:
    from streamlit_pdf_viewer import pdf_viewer
except ImportError:
    pdf_viewer = None

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
    "interested_sectors": [],
    "cached_cons_sector": None, # (selection_key_hash, dataframe)
    "index_data": None,
    "selected_indices": [],
    "interested_indices": [],
    "cached_cons_index": None,
    "bse_data": pd.DataFrame(),
    "selected_ann_row": None,
    "bse_fetched": False,
    "scan_match_data": None,
    "concall_data": None,
    "selected_concall_row": None
}
for key, val in states.items():
    if key not in st.session_state:
        st.session_state[key] = val

@st.cache_data(show_spinner=False, ttl=3600)
def get_cached_pdf_bytes(link):
    """Fetches and caches PDF bytes for the embedded viewer."""
    return announcements_utils.fetch_pdf_bytes(link)




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

@st.cache_data(ttl=3600)
def get_fno_list():
    """Fetches the list of symbols in the Futures segment from NSE with local fallback."""
    url = "https://www.nseindia.com/api/underlying-information"
    backup_file = "nse_fno_backup.json"
    headers = {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9,en-IN;q=0.8',
        'priority': 'u=1, i',
        'referer': 'https://www.nseindia.com/products-services/equity-derivatives-list-underlyings-information',
        'sec-ch-ua': '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36 Edg/144.0.0.0'
    }
    
    import time
    max_retries = 3
    
    symbols = set()
    
    # helper to parse symbols from json data
    def parse_symbols(data):
        syms = set()
        if 'data' in data and isinstance(data['data'], dict):
            underlying = data['data'].get('UnderlyingList', [])
            indices = data['data'].get('IndexList', [])
            for item in underlying + indices:
                if 'symbol' in item:
                    # Clean and normalize symbol
                    syms.add(item['symbol'].strip().upper())
        return syms

    # Attempt Live Fetch
    for attempt in range(max_retries):
        try:
            session = requests.Session()
            session.headers.update(headers)
            session.get("https://www.nseindia.com", timeout=10)
            time.sleep(1.0)
            response = session.get(url, timeout=10)
            
            if response.status_code == 403 and attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
                
            response.raise_for_status()
            data = response.json()
            return parse_symbols(data)
            
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            break
    
    # Fallback to local file
    try:
        if os.path.exists(backup_file):
            with open(backup_file, "r") as f:
                data = json.load(f)
                st.sidebar.info("Using cached NSE F&O list (API blocked).")
                return parse_symbols(data)
    except Exception as e:
        st.sidebar.error(f"Error loading NSE fallback: {e}")
        
    return set()

def get_status_color(val):
    if not isinstance(val, str): return ""
    v = val.lower()
    if "outperforming" in v: return "background-color: #ccffcc; color: #006600"
    if "accumulating" in v: return "background-color: #cce5ff; color: #004085"
    if "consolidating" in v: return "background-color: #ffe5cc; color: #856404"
    if "underperforming" in v: return "background-color: #ffcccc; color: #cc0000"
    return ""

def highlight_fno(val, fno_list):
    """Styles a cell green if the symbol is in the F&O list."""
    if not isinstance(val, str) or not val: return ""
    
    # Extract symbol from URL or 'NSE:SYMBOL'
    # URLs look like: https://in.tradingview.com/chart/?symbol=360ONE
    # Or raw symbols: 360ONE
    raw_symbol = val.split('=')[-1].split(':')[-1].strip().upper()
    
    if raw_symbol in fno_list:
        return "background-color: #d1f7d1; color: #006600; font-weight: bold;"
    return ""

def render_rotation_tab(tab_name, data_key, selection_key, scan_type):
    st.header(tab_name)
    st.text("Outperforming → Strength is visible and persistent")
    st.text("Accumulating → Early signs of strength are emerging")
    st.text("Consolidating → Momentum is slowing down")
    st.text("Underperforming → Persistent weakness remains")

    if st.button(f"Fetch {tab_name} Data"):
        url = "https://www.stockscans.in/api/scans/market/run"
        payload = json.dumps({"marketScanType": scan_type, "timePeriod": "Latest"})
        headers = {
            'sec-ch-ua-platform': '"Windows"',
            'Referer': 'https://www.stockscans.in/market-scans',
            'sec-ch-ua': '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
            'sec-ch-ua-mobile': '?0',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        if STOCKSCANS_COOKIE:
            headers['Cookie'] = STOCKSCANS_COOKIE

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
        df = st.session_state[data_key].copy() # Copy to avoid mutation issues
        
        # Filter logic if it's the Index Rotation tab
        if scan_type == "Index":
            # Add a text input or checkbox for filtering
            col_f1, col_f2 = st.columns([3, 1])
            with col_f1:
                filter_query = st.text_input("Filter by Index Name (use '/' or '|' or ',' for multiple, e.g. BSE/NIFTY)", value="NIFTY", key="index_name_filter_query")
            with col_f2:
                apply_filter = st.checkbox("Apply Filter", value=True, key="index_name_filter_apply")
                
            if apply_filter and filter_query:
                # Split the filter_query and strip whitespace
                patterns = [p.strip().lower() for p in filter_query.replace('|', '/').replace(',', '/').split('/') if p.strip()]
                if patterns:
                    # Filter rows where name contains any of the patterns
                    mask = df["name"].astype(str).str.lower().apply(lambda x: any(pat in x for pat in patterns))
                    df = df[mask]
        
        column_config = {
            "historicScores": st.column_config.LineChartColumn("Historic Scores (1M)", width="medium")
        }

        # Handle ID Column Hyperlinking
        id_col = next((c for c in df.columns if c.lower() in ["companyid", "symbol", "id"]), None)
        if id_col:
            # Transform the ID column values into clickable TradingView URLs
            df[id_col] = "https://in.tradingview.com/chart/?symbol=" + df[id_col].astype(str)
            column_config[id_col] = st.column_config.LinkColumn(id_col, display_text=r"symbol=(.*)")
            
        status_col = next((c for c in df.columns if c.lower() == "status"), None)
        
        # Prepare display dataframe with F&O highlighting
        fno_list = get_fno_list()
        if id_col:
            # Apply styling to the ID column (which now contains URLs)
            display_df = df.style.map(get_status_color, subset=[status_col] if status_col else [])
            display_df = display_df.map(
                lambda x: highlight_fno(x, fno_list),
                subset=[id_col]
            )
        else:
            display_df = df.style.map(get_status_color, subset=[status_col] if status_col else [])
        
        event = st.dataframe(
            display_df,
            column_config=column_config,
            use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row", key=f"{data_key}_table"
        )
        if event.selection.rows:
            new_selection = df.iloc[event.selection.rows]["name"].tolist()
            if new_selection != st.session_state[selection_key]:
                st.session_state[selection_key] = new_selection
                # Clear interested list when parent selection changes
                # data_key is 'sector_data' or 'index_data'
                prefix = data_key.split('_')[0] # 'sector' or 'index'
                st.session_state[f"interested_{prefix}s"] = []
        else:
            if st.session_state[selection_key]:
                st.session_state[selection_key] = []
                prefix = data_key.split('_')[0]
                st.session_state[f"interested_{prefix}s"] = []
    else:
        st.info(f"Click 'Fetch {tab_name} Data' to load.")

def render_constituents_tab(header, selection_key, scan_type):
    st.header(header)
    selected = st.session_state.get(selection_key, [])
    if selected:
        # --- Caching Mechanism ---
        cache_key = f"cached_cons_{selection_key.split('_')[1]}" # sector or index
        selection_hash = ",".join(sorted(selected))
        
        cached_data = st.session_state.get(cache_key)
        if cached_data and cached_data[0] == selection_hash:
            final_df = cached_data[1]
        else:
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
                # Default sort by score descending
                if "score" in final_df.columns:
                    final_df = final_df.sort_values(by="score", ascending=False)
                st.session_state[cache_key] = (selection_hash, final_df)
            else:
                final_df = pd.DataFrame()

        if not final_df.empty:
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
            
            # Prepare display dataframe with F&O highlighting
            fno_list = get_fno_list()
            display_df = final_df[cols]
            
            if id_col:
                # Apply styling to the ID column
                styled_df = display_df.style.map(
                    lambda x: highlight_fno(x, fno_list),
                    subset=[id_col] if id_col in cols else []
                )
            else:
                styled_df = display_df

            event = st.dataframe(
                styled_df, 
                use_container_width=True, 
                hide_index=True, 
                key=f"{selection_key}_details_table",
                on_select="rerun", # Keep "rerun" but data is now cached so it's fast
                selection_mode="multi-row",
                column_config={
                    "historicScores": st.column_config.LineChartColumn("Historic Scores (1M)", width="medium"), 
                    "TV Link": st.column_config.LinkColumn("TradingView", display_text=r"symbol=(.*)")
                }
            )

            # --- FEATURE 3: Interested List (Manual Trigger) ---
            interested_key = f"interested_{selection_key.split('_')[1]}"
            
            if st.button("Add Selected to Interested List", key=f"btn_{selection_key}"):
                if event.selection.rows:
                    selected_indices = event.selection.rows
                    # Extract raw IDs (before hyperlinking if needed, but here we just need the values)
                    # Note: final_df still has the raw ID values if we haven't overwritten them 
                    # in a way that breaks extraction. The render_constituents_tab logic 
                    # doesn't hyperlink the IDs in final_df[cols] display as URLs like the rotation tabs do.
                    # It creates a separate "TV Link" column.
                    st.session_state[interested_key] = final_df.iloc[selected_indices][id_col].dropna().unique().tolist()
                else:
                    st.warning("Please select rows in the table above first.")

            interested_ids = st.session_state.get(interested_key, [])
            if interested_ids:
                interested_string = ", ".join(map(str, interested_ids))
                st.subheader("Interested List")
                interested_copy_html = f"""
                <button id="copyInterestedBtn" style="background-color:#28a745;color:white;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;">Copy Interested</button>
                <script>
                document.getElementById('copyInterestedBtn').onclick = function() {{
                    navigator.clipboard.writeText('{interested_string}').then(function() {{
                        const b = document.getElementById('copyInterestedBtn');
                        b.innerText = 'Copied!';
                        setTimeout(function() {{
                            b.innerText = 'Copy Interested';
                        }}, 2000);
                    }});
                }};
                </script>
                """
                st.components.v1.html(interested_copy_html, height=50)
                st.code(interested_string, language="")
    else:
        st.info("Select items in the rotation tab first.")

def render_announcement_pdf_viewer(selected_row):
    """Renders the embedded PDF viewer card for the selected corporate announcement."""
    if not selected_row:
        st.info("👈 **No announcement selected.** Click on any row in the table to open its PDF directly in this embedded viewer.")
        return

    link = selected_row.get("LINK", "")
    company = selected_row.get("SLONGNAME", "Company Announcement")
    atype = selected_row.get("TYPE", "Announcement")
    headline = selected_row.get("HEADLINE", "")
    subcat = selected_row.get("SUBCATNAME", "")
    dissem_dt = selected_row.get("DissemDT", "")
    newssub = selected_row.get("NEWSSUB", "")
    
    # Header display card
    st.markdown(
        f"""
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <h4 style="margin: 0; color: #1e293b; font-weight: 700;">🏢 {company}</h4>
                <span style="background-color: #2563eb; color: #ffffff; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600;">{atype}</span>
            </div>
            <div style="font-size: 12px; color: #64748b; margin-bottom: 4px;">
                <strong>Date & Time:</strong> {dissem_dt} &nbsp;|&nbsp; <strong>Subcategory:</strong> {subcat}
            </div>
            {f'<div style="font-size: 13px; color: #334155;"><strong>Subject:</strong> {newssub}</div>' if newssub and newssub != '-' else ''}
            {f'<div style="font-size: 13px; color: #334155;"><strong>Headline:</strong> {headline}</div>' if headline and headline != newssub else ''}
        </div>
        """,
        unsafe_allow_html=True
    )

    if not link:
        st.warning("No PDF attachment link is available for this announcement.")
        return

    # PDF Action Controls
    ctl1, ctl2, ctl3 = st.columns([2, 2, 1])
    with ctl2:
        st.link_button("🌐 Open BSE URL", link, use_container_width=True)
    with ctl3:
        if st.button("✖ Close", key="btn_close_pdf", use_container_width=True):
            st.session_state["selected_ann_row"] = None
            st.rerun()

    with st.spinner("Fetching PDF attachment from BSE..."):
        pdf_bytes = get_cached_pdf_bytes(link)

    if pdf_bytes:
        safe_company = "".join([c for c in company if c.isalnum() or c in (' ', '-', '_')]).strip()
        safe_type = "".join([c for c in atype if c.isalnum() or c in (' ', '-', '_')]).strip()
        raw_name = link.split('/')[-1]
        pdf_filename = f"{safe_company}_{safe_type}_{raw_name}"

        with ctl1:
            st.download_button(
                label="📥 Download PDF",
                data=pdf_bytes,
                file_name=pdf_filename,
                mime="application/pdf",
                use_container_width=True
            )

        rendered = False
        if pdf_viewer is not None:
            try:
                pdf_viewer(input=pdf_bytes, width="100%", height=800, render_text=True)
                rendered = True
            except Exception as e:
                rendered = False

        if not rendered:
            base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
            pdfjs_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset="utf-8">
              <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
              <style>
                body {{ margin: 0; padding: 0; background-color: #1e293b; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
                #toolbar {{
                  position: sticky; top: 0; z-index: 100;
                  background: #0f172a; color: white; padding: 8px 14px;
                  display: flex; gap: 8px; align-items: center; justify-content: center;
                  box-shadow: 0 2px 6px rgba(0,0,0,0.3); font-size: 13px; border-bottom: 1px solid #334155;
                }}
                .btn {{
                  background: #2563eb; color: white; border: none; padding: 5px 12px;
                  border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600;
                }}
                .btn:hover {{ background: #1d4ed8; }}
                .btn:disabled {{ background: #475569; cursor: not-allowed; }}
                #canvas-container {{
                  display: flex; flex-direction: column; align-items: center;
                  padding: 14px 8px; gap: 14px; overflow-y: auto; max-height: 740px;
                }}
                canvas {{
                  box-shadow: 0 4px 12px rgba(0,0,0,0.45); background: white;
                  border-radius: 4px; max-width: 98%;
                }}
                #loading {{ color: #cbd5e1; padding: 25px; font-size: 14px; }}
              </style>
            </head>
            <body>
              <div id="toolbar">
                <button class="btn" id="prev-btn" onclick="changePage(-1)">◀ Prev</button>
                <span>Page <strong id="page-num">1</strong> / <span id="page-count">-</span></span>
                <button class="btn" id="next-btn" onclick="changePage(1)">Next ▶</button>
                <button class="btn" onclick="zoom(0.2)">🔍 Zoom +</button>
                <button class="btn" onclick="zoom(-0.2)">🔍 Zoom -</button>
                <button class="btn" onclick="resetZoom()">Fit</button>
              </div>
              <div id="canvas-container">
                <div id="loading">Rendering PDF document...</div>
                <canvas id="pdf-render"></canvas>
              </div>

              <script>
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

                const b64Data = "{base64_pdf}";
                const rawData = atob(b64Data);
                const uint8Array = new Uint8Array(rawData.length);
                for (let i = 0; i < rawData.length; i++) {{
                  uint8Array[i] = rawData.charCodeAt(i);
                }}

                let pdfDoc = null,
                    pageNum = 1,
                    pageRendering = false,
                    pageNumPending = null,
                    scale = 1.3,
                    canvas = document.getElementById('pdf-render'),
                    ctx = canvas.getContext('2d');

                function renderPage(num) {{
                  pageRendering = true;
                  pdfDoc.getPage(num).then(function(page) {{
                    let viewport = page.getViewport({{ scale: scale }});
                    canvas.height = viewport.height;
                    canvas.width = viewport.width;

                    let renderContext = {{
                      canvasContext: ctx,
                      viewport: viewport
                    }};
                    let renderTask = page.render(renderContext);

                    renderTask.promise.then(function() {{
                      pageRendering = false;
                      document.getElementById('loading').style.display = 'none';
                      if (pageNumPending !== null) {{
                        renderPage(pageNumPending);
                        pageNumPending = null;
                      }}
                    }});
                  }});

                  document.getElementById('page-num').textContent = num;
                  document.getElementById('prev-btn').disabled = (num <= 1);
                  document.getElementById('next-btn').disabled = (num >= pdfDoc.numPages);
                }}

                function queueRenderPage(num) {{
                  if (pageRendering) {{
                    pageNumPending = num;
                  }} else {{
                    renderPage(num);
                  }}
                }}

                function changePage(delta) {{
                  if (!pdfDoc) return;
                  let newPage = pageNum + delta;
                  if (newPage >= 1 && newPage <= pdfDoc.numPages) {{
                    pageNum = newPage;
                    queueRenderPage(pageNum);
                  }}
                }}

                function zoom(delta) {{
                  scale = Math.max(0.6, Math.min(3.0, scale + delta));
                  queueRenderPage(pageNum);
                }}

                function resetZoom() {{
                  scale = 1.3;
                  queueRenderPage(pageNum);
                }}

                pdfjsLib.getDocument({{ data: uint8Array }}).promise.then(function(pdfDoc_) {{
                  pdfDoc = pdfDoc_;
                  document.getElementById('page-count').textContent = pdfDoc.numPages;
                  renderPage(pageNum);
                }}).catch(function(err) {{
                  document.getElementById('loading').textContent = 'Error rendering PDF: ' + err.message;
                }});
              </script>
            </body>
            </html>
            """
            st.components.v1.html(pdfjs_html, height=800)
    else:
        st.error(f"Unable to fetch PDF from BSE. You can try viewing it directly: [Open BSE Link]({link})")

def fetch_scan_matched_stocks():
    """Fetches most scan-matched stocks from stockscans.in API."""
    url = "https://www.stockscans.in/api/home/most-scan-matched-stocks"
    headers = {
        'accept': 'application/json',
        'accept-language': 'en-US,en;q=0.9,hi;q=0.8',
        'content-type': 'application/json',
        'priority': 'u=1, i',
        'referer': 'https://www.stockscans.in/',
        'sec-ch-ua': '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36',
        'x-sync-source': '97dwuu6hmu48c2tr',
        'Cookie': STOCKSCANS_COOKIE
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Error fetching most scan-matched stocks: {e}")
        return None

def render_scan_match_tab():
    st.header("Most Scan-Matched Stocks")
    st.caption("Displays stocks matching the highest number of scan filters on StockScans.")

    if 'scan_match_data' not in st.session_state:
        st.session_state['scan_match_data'] = None

    if st.button("Fetch SCAN MATCH Data"):
        with st.spinner("Fetching most scan-matched stocks..."):
            data = fetch_scan_matched_stocks()
            if data and "companies" in data:
                companies = data["companies"]
                rows = []
                for c in companies:
                    pop_scans = [s.get('scanName') for s in c.get('popularScans', []) if s.get('scanName')]
                    saved_scans = [s.get('scanName') for s in c.get('savedScans', []) if s.get('scanName')]
                    all_scans = list(dict.fromkeys(pop_scans + saved_scans))
                    rows.append({
                        'companyId': c.get('companyId', ''),
                        'Name': c.get('Name', ''),
                        'matchCount': pd.to_numeric(c.get('matchCount', 0), errors='coerce'),
                        'Matched Scans': ", ".join(all_scans),
                        'allScansList': all_scans
                    })
                df = pd.DataFrame(rows)
                if "matchCount" in df.columns:
                    df = df.sort_values(by="matchCount", ascending=False).reset_index(drop=True)
                st.session_state['scan_match_data'] = df
            else:
                st.warning("No data returned or invalid response structure.")

    df = st.session_state.get('scan_match_data')
    if df is not None and not df.empty:
        df_display = df.copy()

        # Filters row
        f_col1, f_col2, f_col3 = st.columns([1, 1, 1])
        with f_col1:
            name_filter = st.text_input("Filter by Name / Symbol", key="sm_name_filter", placeholder="Search symbol or name...")
        with f_col2:
            all_scan_names = sorted(list(set([scan for sublist in df_display['allScansList'] for scan in sublist])))
            selected_scans = st.multiselect("Filter by Scan Name", all_scan_names, key="sm_scan_filter")
        with f_col3:
            max_matches = int(df_display['matchCount'].max()) if 'matchCount' in df_display.columns else 1
            min_matches = st.number_input("Min Match Count", min_value=1, max_value=max_matches if max_matches > 1 else 100, value=1, key="sm_min_match")

        # Apply Filters
        if name_filter.strip():
            query = name_filter.strip().lower()
            df_display = df_display[
                df_display['companyId'].astype(str).str.lower().str.contains(query) |
                df_display['Name'].astype(str).str.lower().str.contains(query)
            ]

        if selected_scans:
            df_display = df_display[
                df_display['allScansList'].apply(lambda lst: any(s in lst for s in selected_scans))
            ]

        if min_matches > 1:
            df_display = df_display[df_display['matchCount'] >= min_matches]

        df_display = df_display.reset_index(drop=True)

        # Copy Stock Identifiers
        if not df_display.empty and 'companyId' in df_display.columns:
            raw_ids = df_display['companyId'].apply(lambda x: str(x).split(':')[-1].strip()).dropna().unique().tolist()
            ids_string = ", ".join(raw_ids)
            st.subheader("Copy Stock Identifiers")
            copy_html = f"""<button id="copySmBtn" style="background-color:#007bff;color:white;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;">Copy Tickers ({len(raw_ids)})</button>
            <script>document.getElementById('copySmBtn').onclick=function(){{navigator.clipboard.writeText('{ids_string}').then(function(){{const b=document.getElementById('copySmBtn');b.innerText='Copied!';b.style.backgroundColor='#28a745';setTimeout(function(){{b.innerText='Copy Tickers ({len(raw_ids)})';b.style.backgroundColor='#007bff';}},2000);}});}};</script>"""
            st.components.v1.html(copy_html, height=50)

        cols_to_show = ['companyId', 'Name', 'matchCount', 'Matched Scans']
        grid_df = df_display[cols_to_show].copy()

        grid_df['companyId'] = "https://in.tradingview.com/chart/?symbol=" + grid_df['companyId'].astype(str)

        column_config = {
            "companyId": st.column_config.LinkColumn("TradingView Link", display_text=r"symbol=(.*)"),
            "Name": st.column_config.TextColumn("Company Name"),
            "matchCount": st.column_config.NumberColumn("Scan Matches"),
            "Matched Scans": st.column_config.TextColumn("Matched Scan Filters", width="large")
        }

        fno_list = get_fno_list()
        styled_df = grid_df.style.map(
            lambda x: highlight_fno(x, fno_list),
            subset=["companyId"]
        )

        st.dataframe(
            styled_df,
            column_config=column_config,
            use_container_width=True,
            hide_index=True,
            key="scan_match_table"
        )
    elif st.session_state.get('scan_match_data') is not None:
        st.info("No matching stocks found for the selected filters.")
    else:
        st.info("Click 'Fetch SCAN MATCH Data' to load the latest scan-matched stocks.")

def fetch_concall_data(offset=0):
    """Fetches concall scans data for a given offset from stockscans.in API."""
    url = "https://www.stockscans.in/api/scans/concall/run"
    payload = json.dumps({
        "industry": [],
        "index": [],
        "watchlistIds": [],
        "resultTiers": [],
        "sentimentTiers": [],
        "filters": [
            {
                "left": "Market Capitalization",
                "sign": ">=",
                "right": "100"
            }
        ],
        "q": "",
        "offset": offset,
        "quarter": None
    })
    headers = {
        'accept': 'application/json',
        'accept-language': 'en-US,en;q=0.9,hi;q=0.8',
        'content-type': 'application/json',
        'origin': 'https://www.stockscans.in',
        'priority': 'u=1, i',
        'referer': 'https://www.stockscans.in/concall-scans',
        'sec-ch-ua': '"Chromium";v="154", "Google Chrome";v="154", "Not A(Brand";v="99"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36',
        'x-sync-skip': '1',
        'x-sync-source': 'omcz67l9mvn1alsu',
        'Cookie': STOCKSCANS_COOKIE
    }
    try:
        response = requests.request("POST", url, headers=headers, data=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Error fetching Concall data (offset {offset}): {e}")
        return None

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_stockscans_doc_bytes(url):
    """Fetches PDF bytes from stockscans.in/document/... with cookie auth."""
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return None
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36',
        'Referer': 'https://www.stockscans.in/concall-scans',
        'Cookie': STOCKSCANS_COOKIE
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception as e:
        print(f"Error fetching Stockscans document {url}: {e}")
    return None

def render_concall_pdf_viewer(selected_row):
    """Renders the embedded PDF viewer below the concalls table for the selected row."""
    if not selected_row:
        st.info("💡 **Tip**: Click on any row in the table above to open and preview its Concall Notes or PPT in the embedded PDF viewer below.")
        return

    company_id = str(selected_row.get("companyId", "")).split('=')[-1]
    company_name = selected_row.get("name", "Company")
    industry = selected_row.get("industry", "")
    concall_date = selected_row.get("when", "")
    score = selected_row.get("resultScore", "")
    tags = selected_row.get("tags", "")

    ss_url = selected_row.get("ssUrl")
    ppt_url = selected_row.get("pptSsUrl")

    # Header card
    st.markdown(
        f"""
        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin-bottom: 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <h4 style="margin: 0; color: #1e293b; font-weight: 700;">🎙️ {company_name} ({company_id})</h4>
                <span style="background-color: #0284c7; color: #ffffff; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600;">{industry}</span>
            </div>
            <div style="font-size: 12px; color: #64748b; margin-bottom: 4px;">
                <strong>Concall Date:</strong> {concall_date} {f"&nbsp;|&nbsp; <strong>Score:</strong> {score}" if score != "" and pd.notna(score) else ""}
            </div>
            {f'<div style="font-size: 13px; color: #334155; margin-top: 4px;"><strong>Highlights:</strong> {tags}</div>' if tags else ''}
        </div>
        """,
        unsafe_allow_html=True
    )

    # Document selection: Concall Notes or PPT
    available_docs = {}
    if ss_url and pd.notna(ss_url) and str(ss_url).strip().startswith("http"):
        available_docs["Concall Notes"] = str(ss_url).strip()
    if ppt_url and pd.notna(ppt_url) and str(ppt_url).strip().startswith("http"):
        available_docs["PPT Notes"] = str(ppt_url).strip()

    if not available_docs:
        st.warning(f"No Concall Notes or PPT attachment is available for {company_name}.")
        return

    col_sel, col_link, col_close = st.columns([3, 2, 1])
    with col_sel:
        if len(available_docs) > 1:
            doc_type = st.radio("Choose Document to View:", list(available_docs.keys()), horizontal=True, key=f"concall_doc_choice_{company_id}")
        else:
            doc_type = list(available_docs.keys())[0]
            st.write(f"**Viewing Document:** `{doc_type}`")

    target_url = available_docs[doc_type]

    with col_link:
        st.link_button(f"🌐 Open {doc_type} URL", target_url, use_container_width=True)
    with col_close:
        if st.button("✖ Close Viewer", key="btn_close_concall_pdf", use_container_width=True):
            st.session_state["selected_concall_row"] = None
            st.rerun()

    with st.spinner(f"Loading {doc_type} from StockScans..."):
        pdf_bytes = fetch_stockscans_doc_bytes(target_url)

    if pdf_bytes:
        safe_sym = "".join([c for c in company_id if c.isalnum() or c in (' ', '-', '_')]).strip()
        safe_doc = "".join([c for c in doc_type if c.isalnum() or c in (' ', '-', '_')]).strip()
        filename = f"{safe_sym}_{safe_doc}_{target_url.split('/')[-1]}"

        st.download_button(
            label=f"📥 Download {doc_type}",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf"
        )

        rendered = False
        if pdf_viewer is not None:
            try:
                pdf_viewer(input=pdf_bytes, width="100%", height=800, render_text=True)
                rendered = True
            except Exception:
                rendered = False

        if not rendered:
            base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
            pdfjs_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset="utf-8">
              <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
              <style>
                body {{ margin: 0; padding: 0; background-color: #1e293b; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
                #toolbar {{
                  position: sticky; top: 0; z-index: 100;
                  background: #0f172a; color: white; padding: 8px 14px;
                  display: flex; gap: 8px; align-items: center; justify-content: center;
                  box-shadow: 0 2px 6px rgba(0,0,0,0.3); font-size: 13px; border-bottom: 1px solid #334155;
                }}
                .btn {{
                  background: #2563eb; color: white; border: none; padding: 5px 12px;
                  border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600;
                }}
                .btn:hover {{ background: #1d4ed8; }}
                .btn:disabled {{ background: #475569; cursor: not-allowed; }}
                #canvas-container {{
                  display: flex; flex-direction: column; align-items: center;
                  padding: 14px 8px; gap: 14px; overflow-y: auto; max-height: 740px;
                }}
                canvas {{
                  box-shadow: 0 4px 12px rgba(0,0,0,0.45); background: white;
                  border-radius: 4px; max-width: 98%;
                }}
                #loading {{ color: #cbd5e1; padding: 25px; font-size: 14px; }}
              </style>
            </head>
            <body>
              <div id="toolbar">
                <button class="btn" id="prev-btn" onclick="changePage(-1)">◀ Prev</button>
                <span>Page <strong id="page-num">1</strong> / <span id="page-count">-</span></span>
                <button class="btn" id="next-btn" onclick="changePage(1)">Next ▶</button>
                <button class="btn" onclick="zoom(0.2)">🔍 Zoom +</button>
                <button class="btn" onclick="zoom(-0.2)">🔍 Zoom -</button>
                <button class="btn" onclick="resetZoom()">Fit</button>
              </div>
              <div id="canvas-container">
                <div id="loading">Rendering document...</div>
                <canvas id="pdf-render"></canvas>
              </div>

              <script>
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

                const b64Data = "{base64_pdf}";
                const rawData = atob(b64Data);
                const uint8Array = new Uint8Array(rawData.length);
                for (let i = 0; i < rawData.length; i++) {{
                  uint8Array[i] = rawData.charCodeAt(i);
                }}

                let pdfDoc = null,
                    pageNum = 1,
                    pageRendering = false,
                    pageNumPending = null,
                    scale = 1.3,
                    canvas = document.getElementById('pdf-render'),
                    ctx = canvas.getContext('2d');

                function renderPage(num) {{
                  pageRendering = true;
                  pdfDoc.getPage(num).then(function(page) {{
                    let viewport = page.getViewport({{ scale: scale }});
                    canvas.height = viewport.height;
                    canvas.width = viewport.width;

                    let renderContext = {{
                      canvasContext: ctx,
                      viewport: viewport
                    }};
                    let renderTask = page.render(renderContext);

                    renderTask.promise.then(function() {{
                      pageRendering = false;
                      document.getElementById('loading').style.display = 'none';
                      if (pageNumPending !== null) {{
                        renderPage(pageNumPending);
                        pageNumPending = null;
                      }}
                    }});
                  }});

                  document.getElementById('page-num').textContent = num;
                  document.getElementById('prev-btn').disabled = (num <= 1);
                  document.getElementById('next-btn').disabled = (num >= pdfDoc.numPages);
                }}

                function queueRenderPage(num) {{
                  if (pageRendering) {{
                    pageNumPending = num;
                  }} else {{
                    renderPage(num);
                  }}
                }}

                function changePage(delta) {{
                  if (!pdfDoc) return;
                  let newPage = pageNum + delta;
                  if (newPage >= 1 && newPage <= pdfDoc.numPages) {{
                    pageNum = newPage;
                    queueRenderPage(pageNum);
                  }}
                }}

                function zoom(delta) {{
                  scale = Math.max(0.6, Math.min(3.0, scale + delta));
                  queueRenderPage(pageNum);
                }}

                function resetZoom() {{
                  scale = 1.3;
                  queueRenderPage(pageNum);
                }}

                pdfjsLib.getDocument({{ data: uint8Array }}).promise.then(function(pdfDoc_) {{
                  pdfDoc = pdfDoc_;
                  document.getElementById('page-count').textContent = pdfDoc.numPages;
                  renderPage(pageNum);
                }}).catch(function(err) {{
                  document.getElementById('loading').textContent = 'Error rendering PDF: ' + err.message;
                }});
              </script>
            </body>
            </html>
            """
            st.components.v1.html(pdfjs_html, height=800)
    else:
        st.error(f"Unable to load document from StockScans. [Open directly in browser]({target_url})")

def render_concall_tab():
    st.header("Concalls")
    st.caption("Fetches earnings conference call summaries, sentiment scores, and highlights.")

    if 'concall_data' not in st.session_state:
        st.session_state['concall_data'] = None

    if st.button("Fetch Concalls Data", key="fetch_concalls_btn", type="primary"):
        with st.spinner("Fetching concall data (offset 0 & 50)..."):
            all_rows = []
            for offset in [0, 50]:
                data = fetch_concall_data(offset=offset)
                if data and "rows" in data and isinstance(data["rows"], list):
                    all_rows.extend(data["rows"])

            if all_rows:
                col_names = [
                    'companyKey', 'companyId', 'name', 'industry', 'when',
                    'ssUrl', 'src', 'notesReady', 'resultScore', 'sentimentTier',
                    'tags', 'pptSsUrl', 'congratsCount', 'audioWebcastId'
                ]
                num_cols = len(all_rows[0])
                cols = col_names[:num_cols] if num_cols <= len(col_names) else [col_names[i] if i < len(col_names) else f"col_{i}" for i in range(num_cols)]
                df = pd.DataFrame(all_rows, columns=cols)
                if 'tags' in df.columns:
                    df['tags'] = df['tags'].apply(lambda x: " | ".join(x) if isinstance(x, list) else str(x) if pd.notna(x) else "")

                # Prepend base document URL to ssUrl and pptSsUrl
                base_doc_url = "https://www.stockscans.in/document/"
                if 'ssUrl' in df.columns:
                    df['ssUrl'] = df['ssUrl'].apply(
                        lambda x: base_doc_url + str(x).strip() if pd.notna(x) and str(x).strip() and not str(x).strip().startswith("http") else (str(x).strip() if pd.notna(x) and str(x).strip().startswith("http") else None)
                    )
                if 'pptSsUrl' in df.columns:
                    df['pptSsUrl'] = df['pptSsUrl'].apply(
                        lambda x: base_doc_url + str(x).strip() if pd.notna(x) and str(x).strip() and not str(x).strip().startswith("http") else (str(x).strip() if pd.notna(x) and str(x).strip().startswith("http") else None)
                    )

                st.session_state['concall_data'] = df
                st.session_state['selected_concall_row'] = None
            else:
                st.warning("No rows returned or invalid response structure.")

    df = st.session_state.get('concall_data')
    if df is not None and not df.empty:
        df_display = df.copy()

        # Filters row
        f_col1, f_col2 = st.columns([1, 1])
        with f_col1:
            name_filter = st.text_input("Filter by Name / Symbol", key="cc_name_filter", placeholder="Search symbol or name...")
        with f_col2:
            industries = ["All"] + sorted([str(x) for x in df_display['industry'].dropna().unique().tolist()]) if 'industry' in df_display.columns else ["All"]
            selected_industry = st.selectbox("Filter by Industry", industries, key="cc_industry_filter")

        if name_filter.strip():
            query = name_filter.strip().lower()
            mask = False
            if 'companyId' in df_display.columns:
                mask = mask | df_display['companyId'].astype(str).str.lower().str.contains(query)
            if 'name' in df_display.columns:
                mask = mask | df_display['name'].astype(str).str.lower().str.contains(query)
            df_display = df_display[mask]

        if selected_industry != "All" and 'industry' in df_display.columns:
            df_display = df_display[df_display['industry'] == selected_industry]

        df_display = df_display.reset_index(drop=True)

        # Copy Tickers button
        if not df_display.empty and 'companyId' in df_display.columns:
            raw_ids = df_display['companyId'].apply(lambda x: str(x).split(':')[-1].strip()).dropna().unique().tolist()
            ids_string = ", ".join(raw_ids)
            st.subheader("Copy Stock Identifiers")
            copy_html = f"""<button id="copyCcBtn" style="background-color:#007bff;color:white;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;">Copy Tickers ({len(raw_ids)})</button>
            <script>document.getElementById('copyCcBtn').onclick=function(){{navigator.clipboard.writeText('{ids_string}').then(function(){{const b=document.getElementById('copyCcBtn');b.innerText='Copied!';b.style.backgroundColor='#28a745';setTimeout(function(){{b.innerText='Copy Tickers ({len(raw_ids)})';b.style.backgroundColor='#007bff';}},2000);}});}};</script>"""
            st.components.v1.html(copy_html, height=50)

        grid_df = df_display.copy()

        # Hyperlinks and Column formatting
        column_config = {}
        if 'companyId' in grid_df.columns:
            grid_df['companyId'] = "https://in.tradingview.com/chart/?symbol=" + grid_df['companyId'].astype(str)
            column_config["companyId"] = st.column_config.LinkColumn("TradingView Link", display_text=r"symbol=(.*)")
        if 'name' in grid_df.columns:
            column_config["name"] = st.column_config.TextColumn("Company Name")
        if 'industry' in grid_df.columns:
            column_config["industry"] = st.column_config.TextColumn("Industry")
        if 'when' in grid_df.columns:
            column_config["when"] = st.column_config.TextColumn("Date / Time")
        if 'resultScore' in grid_df.columns:
            column_config["resultScore"] = st.column_config.NumberColumn("Result Score")
        if 'sentimentTier' in grid_df.columns:
            column_config["sentimentTier"] = st.column_config.NumberColumn("Sentiment Tier")
        if 'tags' in grid_df.columns:
            column_config["tags"] = st.column_config.TextColumn("Key Highlights", width="large")
        if 'ssUrl' in grid_df.columns:
            column_config["ssUrl"] = st.column_config.LinkColumn("Concall Notes", display_text="Notes PDF")
        if 'pptSsUrl' in grid_df.columns:
            column_config["pptSsUrl"] = st.column_config.LinkColumn("PPT Notes", display_text="PPT PDF")

        # Hide CompanyKey, notesready, src, audioWebcastId columns
        cols_to_hide = {'companykey', 'notesready', 'src', 'audiowebcastid'}
        display_cols = [c for c in grid_df.columns if c.lower() not in cols_to_hide]

        st.caption("💡 **Tip**: Click on any row in the table below to open and preview its Concall Notes or PPT in the embedded PDF viewer below.")

        event = st.dataframe(
            grid_df[display_cols],
            column_config=column_config,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="concall_table"
        )

        if event and event.selection.rows:
            sel_idx = event.selection.rows[0]
            if sel_idx < len(df_display):
                st.session_state['selected_concall_row'] = df_display.iloc[sel_idx].to_dict()

        st.divider()
        render_concall_pdf_viewer(st.session_state.get('selected_concall_row'))

    elif st.session_state.get('concall_data') is not None:
        st.info("No concall records found matching your filters.")
    else:
        st.info("Click 'Fetch Concalls Data' to load earnings conference call summaries.")

# --- Tabs ---
tabs = st.tabs(["SCAN MATCH", "Concalls", "Corp Announcements", "Screeners"])
t_sm, t_cc, t_ann, t_scr = tabs

with t_sm: render_scan_match_tab()
with t_cc: render_concall_tab()

with t_ann:
    st.header("Corporate Announcements")
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1: d_from = st.date_input("From Date", date.today() - timedelta(days=1), key="ann_date_from")
    with c2: d_to = st.date_input("To Date", date.today(), key="ann_date_to")
    with c3:
        st.write("")
        st.write("")
        fetch_clicked = st.button("Fetch Announcements", use_container_width=True, type="primary")

    if fetch_clicked:
        with st.spinner("Fetching corporate announcements from BSE..."):
            st.session_state['bse_data'] = announcements_utils.get_bse_announcements(d_from, d_to)
            st.session_state['bse_fetched'] = True
            st.session_state['selected_ann_row'] = None

    bse_df = st.session_state.get('bse_data', pd.DataFrame())
    if not bse_df.empty:
        st.success(f"Found {len(bse_df)} announcements.")
        
        col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
        with col_f1:
            types = ["All"] + sorted(bse_df['TYPE'].dropna().unique().tolist())
            sel_type = st.selectbox("Filter by Category / Type", types, key="ann_filter_type")
        with col_f2:
            search_query = st.text_input("Search Company / Subject", "", placeholder="e.g. Tata, Dividend, Bonus...", key="ann_search_query")
        with col_f3:
            layout_view = st.radio("Viewer Layout", ["Side-by-Side", "Stacked (Below Table)"], horizontal=True, key="ann_layout_view")
            
        disp_bse = bse_df.copy()
        if sel_type != "All":
            disp_bse = disp_bse[disp_bse['TYPE'] == sel_type]
        if search_query.strip():
            sq = search_query.strip().lower()
            mask = (
                disp_bse['SLONGNAME'].astype(str).str.lower().str.contains(sq, na=False) |
                disp_bse['NEWSSUB'].astype(str).str.lower().str.contains(sq, na=False) |
                disp_bse['HEADLINE'].astype(str).str.lower().str.contains(sq, na=False)
            )
            disp_bse = disp_bse[mask]

        # Bulk download expander
        with st.expander("📦 Bulk Download Options"):
            dl_path = st.text_input("Local Download Folder Path", key="ann_dl_path")
            if st.button("Download Filtered PDFs to Folder", key="ann_dl_btn"):
                if dl_path:
                    path = dl_path.strip().strip('"').strip("'")
                    if not os.path.exists(path): os.makedirs(path)
                    count, errs = announcements_utils.download_pdfs(disp_bse, path)
                    if count > 0: st.success(f"Downloaded {count} files.")
                    for e in errs: st.error(e)
                else: st.error("Enter path.")

        column_config = {
            "LINK": st.column_config.LinkColumn("BSE Link", display_text="Open BSE")
        }

        st.caption("💡 **Tip**: Click on any row in the table below to immediately view the PDF in the embedded viewer.")

        if layout_view == "Side-by-Side":
            col_table, col_pdf = st.columns([1, 3], gap="medium")
            with col_table:
                event = st.dataframe(
                    disp_bse,
                    column_config=column_config,
                    use_container_width=True,
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun",
                    key="bse_table_side"
                )
                if event.selection.rows:
                    sel_idx = event.selection.rows[0]
                    if sel_idx < len(disp_bse):
                        st.session_state['selected_ann_row'] = disp_bse.iloc[sel_idx].to_dict()

            with col_pdf:
                render_announcement_pdf_viewer(st.session_state.get('selected_ann_row'))
        else:
            event = st.dataframe(
                disp_bse,
                column_config=column_config,
                use_container_width=True,
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun",
                key="bse_table_stacked"
            )
            if event.selection.rows:
                sel_idx = event.selection.rows[0]
                if sel_idx < len(disp_bse):
                    st.session_state['selected_ann_row'] = disp_bse.iloc[sel_idx].to_dict()

            st.divider()
            render_announcement_pdf_viewer(st.session_state.get('selected_ann_row'))

    elif st.session_state.get('bse_fetched'):
        st.info("No announcements found for the selected date range.")

with t_scr:
    st.header("Imp Screeners")
    st.markdown("- [Go to Markets Dashboard](https://www.stockscans.in/market-scans/dashboard)")
    st.markdown("- [Sector Rotation](https://bananapatterns.com/market/rotation#search)")
    st.write("Quick access to Chartink screeners and dashboards:")
    links = [("HVY Screener", "hvy-atfinallynitin"), ("MARS stocks", "159858"), ("Market Breadth Check1", "163999"), ("Market Breadth Check 2", "149096")]
    for name, path in links:
        url = f"https://chartink.com/{'screener' if '-' in path else 'dashboard'}/{path}"
        st.markdown(f"- [{name}]({url})")
