import streamlit as st
import requests
import json
import pandas as pd

st.set_page_config(layout="wide")
st.title("Stock Market Scans")

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

if st.button("Fetch Data"):
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
        
        # Configure the historicScores column as a line chart
        column_config = {
            "historicScores": st.column_config.LineChartColumn(
                "Historic Scores",
                width="medium",
                help="The stock's historic scores over time",
                y_min=0,
                y_max=100, # Assuming score is 0-100, adjust if needed
            )
        }
        
        st.dataframe(
            df,
            column_config=column_config,
            use_container_width=True,
            hide_index=True
        )
    elif data:
        st.warning("No 'table' key found in the response.")
        st.json(data)
