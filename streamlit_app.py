import streamlit as st
import requests
import json
import os
import pandas as pd
from datetime import date, datetime, timedelta
import announcements_utils

st.set_page_config(layout="wide")
st.title("Dashboard")

tab1, tab2, tab3 = st.tabs(["Sector Rotation", "Corp Announcements", "Screeners"])

with tab1:
    st.header("Sector in Limelight")
    st.text("Outperforming → Strength is visible and persistent")
    st.text("Accumulating → Early signs of strength are emerging")
    st.text("Consolidating → Momentum is slowing down")
    st.text("Underperforming → Persistent weakness remains")
    
    def fetch_data():
        url = "https://www.stockscans.in/api/company/market-scans/table"

        payload = json.dumps({
          "marketScanType": "Industry",
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
          'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
        }

        try:
            response = requests.request("POST", url, headers=headers, data=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching data: {e}")
            return None

    if st.button("Fetch Scans Data"):
        with st.spinner("Fetching data..."):
            data = fetch_data()
            
        if data and "table" in data:
            df = pd.DataFrame(data["table"])
            
            # Fix: Ensure historicScores is a list of floats for the LineChartColumn
            # The API might be returning mixed types or pandas might be inferring it incorrectly.
            def clean_scores(scores):
                cleaned = []
                if isinstance(scores, list):
                    # Slice to get approximately the last 1 month (assuming daily data, ~22-30 points)
                    recent_scores = scores[-30:] if len(scores) > 30 else scores
                    
                    for s in recent_scores:
                        if isinstance(s, list) and len(s) > 1:
                             # Structure is [date, score, status]
                             try:
                                 cleaned.append(float(s[1]))
                             except (ValueError, TypeError):
                                 pass
                        elif isinstance(s, (int, float)):
                            cleaned.append(float(s))
                return cleaned

            if "historicScores" in df.columns:
                df["historicScores"] = df["historicScores"].apply(clean_scores)
            
            if "score" in df.columns:
                df = df.sort_values(by="score", ascending=False)
            
            # Configure the historicScores column as a line chart
            column_config = {
                "historicScores": st.column_config.LineChartColumn(
                    "Historic Scores (Last 1 Month)",
                    width="medium",
                    help="The stock's historic scores over time"
                )
            }
            
            # Define color mapping for status column
            def get_status_color(val):
                if not isinstance(val, str):
                    return ""
                
                val_lower = val.lower()
                if "outperforming" in val_lower:
                    return "background-color: #ccffcc; color: #006600" # Green
                elif "accumulating" in val_lower:
                    return "background-color: #cce5ff; color: #004085" # Dark Blue
                elif "consolidating" in val_lower:
                    return "background-color: #ffe5cc; color: #856404" # Orange
                elif "underperforming" in val_lower:
                    return "background-color: #ffcccc; color: #cc0000" # Red
                return ""

            # Check if status column exists (case-insensitive)
            status_col = None
            for col in df.columns:
                if col.lower() == "status":
                    status_col = col
                    break
            
            if status_col:
                # Apply styling
                st.dataframe(
                    df.style.map(get_status_color, subset=[status_col]),
                    column_config=column_config,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.dataframe(
                    df,
                    column_config=column_config,
                    use_container_width=True,
                    hide_index=True
                )
        elif data:
            st.warning("No 'table' key found in the response.")
            st.json(data)

with tab2:
    st.header("Corporate Announcements")
    
    col1, col2 = st.columns(2)
    with col1:
        from_date = st.date_input("From Date", date.today() - timedelta(days=0))
    with col2:
        to_date = st.date_input("To Date", date.today())
    
    # Initialize session state for BSE data and fetch status
    if 'bse_data' not in st.session_state:
        st.session_state['bse_data'] = pd.DataFrame()
    if 'bse_fetched' not in st.session_state:
        st.session_state['bse_fetched'] = False

    if st.button("Fetch Data"):
        with st.spinner("Fetching and analyzing announcements... this may take a while."):
            # Fetch data and store in session state
            st.session_state['bse_data'] = announcements_utils.get_bse_announcements(from_date, to_date)
            st.session_state['bse_fetched'] = True
            
    # Check if data exists in session state
    if not st.session_state['bse_data'].empty:
        bse_df = st.session_state['bse_data']
        st.success(f"Found {len(bse_df)} relevant announcements.")
        
        # Filter by Type
        types = ["All"] + sorted(bse_df['TYPE'].unique().tolist())
        selected_type = st.selectbox("Filter by Type", types)
        
        if selected_type != "All":
            display_df = bse_df[bse_df['TYPE'] == selected_type]
        else:
            display_df = bse_df
            
        # Download Button at the Top (above the table)
        col_dl1, col_dl2 = st.columns([0.7, 0.3])
        with col_dl1:
             download_folder = st.text_input("Enter Local Download Folder Path", help="e.g., C:\\Users\\Name\\Downloads\\BSE_Announcements")
        with col_dl2:
             # Add some vertical spacing to align button
             st.write("")
             st.write("")
             if st.button("Download PDFs to Folder"):
                 if download_folder:
                     # Remove quotes if user accidentally included them
                     clean_folder = download_folder.strip().strip('"').strip("'")
                     with st.spinner(f"Downloading PDFs to {clean_folder}..."):
                         try:
                             # Ensure the folder exists
                             if not os.path.exists(clean_folder):
                                 os.makedirs(clean_folder)
                                 
                             count, errors = announcements_utils.download_pdfs(display_df, clean_folder)
                             
                             if count > 0:
                                 st.success(f"Successfully downloaded {count} files.")
                             if errors:
                                 with st.expander("See Download Errors"):
                                     for e in errors:
                                         st.error(e)
                             if count == 0 and not errors:
                                 st.info("No new files to download.")
                         except Exception as e:
                             st.error(f"Error: {e}")
                 else:
                     st.error("Please enter a download folder path.")

        st.dataframe(
            display_df,
            column_config={
                "LINK": st.column_config.LinkColumn("PDF Link", display_text="Open PDF")
            },
            use_container_width=True,
            hide_index=True
        )
    elif st.session_state['bse_fetched']:
        st.info("No matching announcements found for the selected date range.")

with tab3:
    st.header("Imp Screeners")
    st.write("Quick access to Chartink screeners and dashboards:")
    st.markdown("- [HVY Screener](https://chartink.com/screener/hvy-atfinallynitin)")
    st.markdown("- [MARS stocks](https://chartink.com/dashboard/159858)")
    st.markdown("- [Market Breadth Check1](https://chartink.com/dashboard/163999)")
    st.markdown("- [Market Breadth Check2](https://chartink.com/dashboard/149096)")
