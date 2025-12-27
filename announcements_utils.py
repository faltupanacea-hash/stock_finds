import requests
import pandas as pd
from datetime import datetime, timedelta

def fetch_dataframe(updstr, fromdate, todate, tableno, pageno, subcat="-1"):
    url = f"https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno={pageno}&strCat={updstr}&strPrevDate={fromdate}&strScrip=&strSearch=P&strToDate={todate}&strType=C&subcategory={subcat}"
    headers = {
        'authority': 'api.bseindia.com',
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'en-US,en;q=0.9',
        'origin': 'https://www.bseindia.com',
        'referer': 'https://www.bseindia.com/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 Edg/117.0.2045.43'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        if tableno == 'Table1':
             # Table1 structure is simpler, usually just row count
             data_json = response.json().get('Table1', [])
        else:
             data_json = response.json().get('Table', [])
        
        dataf = pd.DataFrame(data=data_json)
        return dataf
    except Exception as e:
        print(f"Error fetching data: {e}")
        return pd.DataFrame()

def fetch_category_data(datastr, fromdate, todate, subcategory):
    # Fetch first page to get row count
    page_df = fetch_dataframe(datastr, fromdate, todate, 'Table1', str(1), subcategory)
    if page_df.empty or 'ROWCNT' not in page_df.columns:
        return pd.DataFrame()

    rowcnt = page_df.loc[0]['ROWCNT']
    fetchdf = pd.DataFrame()
    
    if rowcnt > 0:
        # Calculate pagination (50 items per page)
        num_pages = (rowcnt // 50) + 2
        for pagenumber in range(1, int(num_pages)):
            pagewise_df = fetch_dataframe(datastr, fromdate, todate, 'Table', str(pagenumber), subcategory)
            fetchdf = pd.concat([fetchdf, pagewise_df], ignore_index=True)

    return fetchdf

def search_data(searchstr, df):
    if df.empty:
        return pd.DataFrame()
        
    # Ensure columns exist to avoid KeyError
    required_cols = ['NEWSSUB', 'HEADLINE', 'MORE', 'SUBCATNAME']
    for col in required_cols:
        if col not in df.columns:
            df[col] = '' # Fill missing columns with empty string
            
    mask = (df['NEWSSUB'].astype(str).str.contains(searchstr, case=False, na=False)) | \
           (df['HEADLINE'].astype(str).str.contains(searchstr, case=False, na=False)) | \
           (df['MORE'].astype(str).str.contains(searchstr, case=False, na=False)) | \
           (df['SUBCATNAME'].astype(str).str.contains(searchstr, case=False, na=False))
           
    searched_data = df.loc[mask]
    
    # Select specific columns
    target_cols = ['SLONGNAME', 'NEWSSUB', 'HEADLINE', 'ATTACHMENTNAME', 'DissemDT', 'SUBCATNAME']
    available_cols = [c for c in target_cols if c in searched_data.columns]
    
    searched_data_df = searched_data[available_cols].copy()
    searched_data_df = searched_data_df.drop_duplicates()
    
    if 'ATTACHMENTNAME' in searched_data_df.columns:
        searched_data_df['LINK'] = 'https://www.bseindia.com/xml-data/corpfiling/AttachLive/' + searched_data_df['ATTACHMENTNAME']
        del searched_data_df['ATTACHMENTNAME']
    
    searched_data_df.insert(0, 'TYPE', searchstr)
    return searched_data_df

def get_bse_announcements(from_date, to_date):
    # Convert dates to string format required by API (YYYYMMDD)
    fromdate_str = from_date.strftime("%Y%m%d")
    todate_str = to_date.strftime("%Y%m%d")
    
    all_results = []
    
    # 1. Company Updates
    comp_df = fetch_category_data("Company+Update", fromdate_str, todate_str, "-1")
    
    categories = [
        "Investor Meet", "Credit Rating", "Presentation", "Transcript", "Press Release",
        "Contract", "FDA", "Inspection", "Demerger", "Buyback", "Buy back", "Offer",
        "Strike", "Expansion", "Capex", "Capacity", "Shut down", "Prefer", "Delisting",
        "Conversion", "Amalgamation", "Resignation", "Name", "Acquisition", "Capital clause",
        "Object clause", "Objects clause", "Rights", "Inaug", "Production", "Change in management",
        "One time settlement", "Scheme of arrangement", "Resolution plan", "Hiving off",
        "Slump", "Forensic auditor", "Raising", "Restructuring", "Qualified", "Allotment",
        "Joint Venture", "Monthly Business Updates"
    ]
    
    for cat in categories:
        res = search_data(cat, comp_df)
        if not res.empty:
            all_results.append(res)
            
    # 2. Corp Actions
    corp_df = fetch_category_data("Corp.+Action", fromdate_str, todate_str, "-1")
    corp_categories = ["Bonus", "Split", "Right Issue", "Merger"]
    for cat in corp_categories:
        res = search_data(cat, corp_df)
        if not res.empty:
            all_results.append(res)
            
    # 3. Insider Trading
    insider_df = fetch_category_data("Insider+Trading+%2F+SAST", fromdate_str, todate_str, "-1")
    res = search_data("SAST", insider_df)
    if not res.empty:
        all_results.append(res)
        
    # 4. AGM/EGM
    agm_df = fetch_category_data("AGM%2FEGM", fromdate_str, todate_str, "EGM")
    res = search_data("EGM", agm_df)
    if not res.empty:
        all_results.append(res)
        
    # 5. Board Meetings
    board_meet_df = fetch_category_data("Board+Meeting", fromdate_str, todate_str, "Outcome+of+Board+Meeting")
    res = search_data("Outcome", board_meet_df)
    if not res.empty:
        all_results.append(res)
        
    if all_results:
        return pd.concat(all_results, axis=0, ignore_index=True)
    
    return pd.DataFrame()

def download_pdfs(df, download_dir):
    import os
    import time
    
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        
    headers = {
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
      'Accept-Language': 'en-US,en;q=0.9,en-IN;q=0.8',
      'Connection': 'keep-alive',
      'Sec-Fetch-Dest': 'document',
      'Sec-Fetch-Mode': 'navigate',
      'Sec-Fetch-Site': 'none',
      'Sec-Fetch-User': '?1',
      'Upgrade-Insecure-Requests': '1',
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0',
      'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
      'sec-ch-ua-mobile': '?0',
      'sec-ch-ua-platform': '"Windows"'
    }
    
    downloaded_count = 0
    errors = []
    
    # Iterate through unique links to avoid duplicates
    unique_links = df[['LINK', 'SLONGNAME', 'TYPE']].drop_duplicates().to_dict('records')
    
    for item in unique_links:
        link = item['LINK']
        company = item['SLONGNAME']
        atype = item['TYPE']
        
        # Create a safe filename
        safe_company = "".join([c for c in company if c.isalnum() or c in (' ', '-', '_')]).strip()
        safe_type = "".join([c for c in atype if c.isalnum() or c in (' ', '-', '_')]).strip()
        filename = f"{safe_company}_{safe_type}_{link.split('/')[-1]}"
        
        filepath = os.path.join(download_dir, filename)
        
        if os.path.exists(filepath):
            continue
            
        try:
            response = requests.get(link, headers=headers, timeout=30)
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    f.write(response.content)
                downloaded_count += 1
            else:
                errors.append(f"Failed to download {link}: Status {response.status_code}")
        except Exception as e:
            errors.append(f"Error downloading {link}: {e}")
            
        # Be polite to the server
        time.sleep(0.5)
        
    return downloaded_count, errors

def download_pdfs_to_zip(df):
    import io
    import zipfile
    import time
    
    zip_buffer = io.BytesIO()
    
    headers = {
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
      'Accept-Language': 'en-US,en;q=0.9,en-IN;q=0.8',
      'Connection': 'keep-alive',
      'Sec-Fetch-Dest': 'document',
      'Sec-Fetch-Mode': 'navigate',
      'Sec-Fetch-Site': 'none',
      'Sec-Fetch-User': '?1',
      'Upgrade-Insecure-Requests': '1',
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36 Edg/134.0.0.0',
      'sec-ch-ua': '"Chromium";v="134", "Not:A-Brand";v="24", "Microsoft Edge";v="134"',
      'sec-ch-ua-mobile': '?0',
      'sec-ch-ua-platform': '"Windows"'
    }
    
    downloaded_count = 0
    errors = []
    
    # Iterate through unique links to avoid duplicates
    unique_links = df[['LINK', 'SLONGNAME', 'TYPE']].drop_duplicates().to_dict('records')
    
    with zipfile.ZipFile(zip_buffer, 'a', zipfile.ZIP_DEFLATED) as zip_file:
        for item in unique_links:
            link = item['LINK']
            company = item['SLONGNAME']
            atype = item['TYPE']
            
            # Create a safe filename
            safe_company = "".join([c for c in company if c.isalnum() or c in (' ', '-', '_')]).strip()
            safe_type = "".join([c for c in atype if c.isalnum() or c in (' ', '-', '_')]).strip()
            filename = f"{safe_company}_{safe_type}_{link.split('/')[-1]}"
            
            try:
                response = requests.get(link, headers=headers, timeout=30)
                if response.status_code == 200:
                    zip_file.writestr(filename, response.content)
                    downloaded_count += 1
                else:
                    errors.append(f"Failed to download {link}: Status {response.status_code}")
            except Exception as e:
                errors.append(f"Error downloading {link}: {e}")
                
            # Be polite to the server
            time.sleep(0.5)
            
    zip_buffer.seek(0)
    return zip_buffer, downloaded_count, errors
