import streamlit as st
import requests
import psycopg2
import pandas as pd
import os
st.set_page_config(page_title="ParisLens Dashboard", layout="wide")
st.title("ParisLens Monitoring Dashboard")

#chedck the API health 
st.header("API STATUS") 
try: 
    res= requests.get("http://api:8000/health", timeout=10)
    if res.status_code == 200: # if the API is healthy 
        st.success("OK")
    else: 
        st.warning("API has some issues") 
except Exception as e: 
    st.error("Issue with API endpoint, cannot be reached") 
         

#check the scraper health: 
st.header("Scraper Health")
def get_scraper_logs():
    db_url = os.environ.get("DATABASE_URL")
    conn = psycopg2.connect(db_url)
    df = pd.read_sql("SELECT * FROM scraper_runs LIMIT 5", conn)
    conn.close()
    return df
try:
    df_logs = get_scraper_logs()
    st.dataframe(df_logs)
except Exception as e:
    st.error(f"Could not connect to database to fetch logs: {e}")