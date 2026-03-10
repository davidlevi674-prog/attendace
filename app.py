import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_gsheets import GSheetsConnection
import requests
import time
import os

# --- 1. הגדרות ועיצוב ---
st.set_page_config(page_title="בדיקת נוכחות גרביל", layout="wide", page_icon="logo.png")

st.markdown("""
    <style>
    /* רקע ראשי */
    .stApp { background-color: #4B5320; color: white; direction: rtl; text-align: right; }
    
    /* רקע סרגל צד - ירוק זית כהה כדי שהטקסט הלבן יבלוט */
    [data-testid="stSidebar"] { background-color: #3b4218 !important; }
    
    /* יישור טקסט */
    div[data-testid="stText"], div[data-testid="stMarkdownContainer"] { text-align: right; direction: rtl; }
    
    /* צבע טקסט כללי ללבן */
    h1, h2, h3, h4, span, label, p { color: white !important; }
    
    /* צבע שחור לטקסט בתוך תיבות טקסט כדי שאפשר יהיה לקרוא מה כותבים */
    div[data-baseweb="input"] input { color: black !important; }
    div[data-baseweb="select"] span { color: black !important; }
    
    /* כיווניות הטבלה */
    div[data-testid="stDataEditor"] { direction: rtl; }
    </style>
    """, unsafe_allow_html=True)

# לוגו
col1, col2, col3 = st.columns([1,1,1])
with col2:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=150)
    else:
        st.markdown("<h2 style='text-align: center;'>🇮🇱</h2>", unsafe_allow_html=True)

st.title("בדיקת נוכחות גרביל")

# --- 2. חיבור ---
conn = st.connection("gsheets", type=GSheetsConnection)

def run_with_retry(func, retries=3, delay=2):
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            if "429" in str(e) or "Quota" in str(e):
                if i < retries - 1:
                    time.sleep(delay * (i + 1))
                    continue
            raise e

def load_data_from_cloud():
    try:
        df = run_with_retry(lambda: conn.read(worksheet="Sheet1", ttl=0))
        df.columns = df.columns.str.strip()
        
        def clean_frame(val):
            if pd.isna(val): return "ללא מחלקה"
            try: return str(int(float(val))) if float(val).is_integer() else str(val)
            except: return str(val)
            
        if 'מסגרת' in df.columns: df['מסגרת'] = df['מסגרת'].apply(clean_frame)
        if 'מספר אישי' in df.columns: 
            df['מספר אישי'] = df['מספר אישי'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            
        for col in ['נוכח', 'זמן דיווח', 'פעיל', 'מפקד']:
            if col not in df.columns: df[col] = "" 
            
        valid_true = ['true', '1', 'v', 'yes', 'כן', 'true.0']
        df['נוכח'] = df['נוכח'].astype(str).str.strip().str.lower().isin(valid_true)
        
        valid_false = ['false', '0', 'no', 'לא', 'false.0']
        df['פעיל'] = ~df['פעיל'].astype(str).str.strip().str.lower().isin(valid_false)
        
        return df
    except Exception as e:
        st.error("תקלה בטעינת הנתונים, נסה לרענן.")
        return pd.DataFrame()

def save_changes_to_cloud(df_to_save):
    df_copy = df_to_save.copy()
    df_copy['נוכח'] = df_copy['נוכח'].apply(lambda x: 'TRUE' if x else 'FALSE')
    df_copy['פעיל'] = df_copy['פעיל'].apply(lambda x: 'TRUE' if x else 'FALSE')
    try:
        run_with_retry(lambda: conn.update(worksheet="Sheet1", data=df_copy))
    except Exception as e:
        st.warning(f"שגיאת שמירה זמנית (עומס): {e}")


