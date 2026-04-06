import streamlit as st
import requests
import psycopg2
import pandas as pd
import os
from datetime import datetime, timedelta
st.set_page_config(page_title="ParisLens Dashboard", layout="wide")
#adding a backround image for fun 
st.markdown(
    """

    <style>
    .stApp {
        background-image: url("https://images5.alphacoders.com/916/thumb-1920-916863.jpg");
        background-attachment: fixed;
        background-size: cover;
    }
    /* Let's optionally make the panels slightly transparent so we can see the background! */
    .st-emotion-cache-1wmy9hl {
        background-color: rgba(0,0,0,0.5);
    }
    /* white text because of the backround*/
    h1, h2, h3, h4, h5, h6, p, span, div, label {
        color: white !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)
st.title("ParisLens Monitoring Dashboard")
# stats from arrondisments enpoint: general and plots
st.header("Arrondissement Analytics")
def fetch_arrondissement_stats():
    """Fetch stats from the API"""
    try:
        res = requests.get("http://api:8000/arrondissements", timeout=10)
        if res.status_code == 200:
            data = res.json()
            df = pd.DataFrame(data["stats"])
            df["date"] = pd.to_datetime(df["date"])
            return df
        else:
            st.error(f"API returned status code {res.status_code}")
            return None
    except Exception as e:
        st.error(f"Could not fetch arrondissement stats: {e}")
        return None

# Fetch data
df_stats = fetch_arrondissement_stats()

if df_stats is not None and len(df_stats) > 0:
    df_stats["date"] = pd.to_datetime(df_stats["date"])
    
    unique_arrondissements = sorted(df_stats["arrondissement"].unique())
    min_date = df_stats["date"].min()
    max_date = df_stats["date"].max()
    
    # default date range: last 30 days
    default_start = max(min_date, max_date - timedelta(days=30))
    
    # adding filters to make the plots easier to navigate
    st.sidebar.header("Filters")
    
    # date range filter
    date_range = st.sidebar.date_input(
        "Select date range",
        value=(default_start.date(), max_date.date()),
        min_value=min_date.date(),
        max_value=max_date.date()
    )
    
    # arrondissement filter
    selected_arrondissements = st.sidebar.multiselect(
        "Select arrondissements",
        options=unique_arrondissements,
        default=unique_arrondissements
    )
    
    # apply filters
    if len(date_range) == 2:
        start_date, end_date = date_range
        start_date = pd.to_datetime(start_date)
        end_date = pd.to_datetime(end_date)
        df_filtered = df_stats[
            (df_stats["date"] >= start_date) &
            (df_stats["date"] <= end_date) &
            (df_stats["arrondissement"].isin(selected_arrondissements))
        ]
    else:
        df_filtered = df_stats[df_stats["arrondissement"].isin(selected_arrondissements)]
    
    if len(df_filtered) > 0:
        # average prime per m square by date and arrondisment
        st.subheader("Average Price per m² by Arrondissement")
        
        chart_price = st.line_chart()
        pivot_price = df_filtered.pivot(index="date", columns="arrondissement", values="avg_price_per_m2")
        if len(pivot_price) > 0:
            chart_price.line_chart(pivot_price)
        
        # listing count
        st.subheader("Number of Listings by Arrondissement")
        
        chart_listings = st.line_chart()
        pivot_listings = df_filtered.pivot(index="date", columns="arrondissement", values="listing_count")
        if len(pivot_listings) > 0:
            chart_listings.line_chart(pivot_listings)
        
        # summary statistics for date period and arronsissements selected
        st.subheader("Summary Statistics")
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("Average Price per m²", 
                     f"€{df_filtered[(df_filtered['date'] == df_filtered['date'].max()) & (df_stats["arrondissement"].isin(selected_arrondissements))]['avg_price_per_m2'].mean():.2f}")
        
        with col2:
            st.metric("Total Listings", 
                     f"{df_filtered[(df_filtered['date'] == df_filtered['date'].max()) & (df_stats["arrondissement"].isin(selected_arrondissements))]['listing_count'].sum():.0f}")
    else:
        st.warning("No data available for the selected filters")
else:
    st.info("No arrondissement stats data available yet")

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
st.header("Ingestion Pipeline Runs")
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