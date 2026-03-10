import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_gsheets import GSheetsConnection
import requests
import time
import os

# --- 1. הגדרות ועיצוב (פתרון אגרסיבי ל-Sidebar) ---
st.set_page_config(page_title="בדיקת נוכחות גרביל", layout="wide", page_icon="logo.png")

st.markdown("""
    <style>
    /* הגדרות כלליות */
    .stApp { background-color: #4B5320; color: white; direction: rtl; text-align: right; }
    [data-testid="stSidebar"] { background-color: #3b4218 !important; min-width: 250px !important; }
    div[data-testid="stText"], div[data-testid="stMarkdownContainer"] { text-align: right; direction: rtl; }
    h1, h2, h3, h4, span, label, p { color: white !important; }
    
    /* פתרון לכיתוב האנכי: מניעת שבירת מילים */
    [data-testid="stSidebar"] * { white-space: nowrap !important; }

    /* הסתרת ה-Sidebar בסמארטפון כדי שלא יפריע */
    @media (max-width: 768px) {
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="stSidebarNav"] { display: none !important; }
        .main .block-container { padding: 1rem !important; }
    }

    /* עיצוב כפתורים זהב */
    div.stButton > button { 
        background-color: #D4AF37 !important; 
        border-radius: 10px !important; 
        border: none !important; 
        color: black !important;
        font-weight: bold !important;
        width: 100%;
    }
    
    /* כפתור מחיקה אדום */
    .stButton button[kind="primary"] {
        background-color: #ff4b4b !important;
        color: white !important;
    }
    
    div[data-testid="stDataEditor"] { direction: rtl; }
    </style>
    """, unsafe_allow_html=True)

col1, col2, col3 = st.columns([1,1,1])
with col2:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=120)
    else:
        st.markdown("<h2 style='text-align: center;'>🇮🇱</h2>", unsafe_allow_html=True)

st.title("בדיקת נוכחות גרביל")

# --- 2. חיבור ---
conn = st.connection("gsheets", type=GSheetsConnection)

def run_with_retry(func, retries=3, delay=2):
    for i in range(retries):
        try: return func()
        except Exception as e:
            if "429" in str(e) or "Quota" in str(e):
                if i < retries - 1:
                    time.sleep(delay * (i + 1))
                    continue
            raise e

def load_data_from_cloud():
    try:
        df = run_with_retry(lambda: conn.read(worksheet="Sheet1", ttl=0))
        df.columns = [str(c).strip() for c in df.columns]
        def clean_frame(val):
            if pd.isna(val): return "ללא מחלקה"
            try: return str(int(float(val))) if float(val).is_integer() else str(val)
            except: return str(val)
        if 'מסגרת' in df.columns: df['מסגרת'] = df['מסגרת'].apply(clean_frame)
        if 'מספר אישי' in df.columns: 
            df['מספר אישי'] = df['מספר אישי'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        for col in ['נוכח', 'זמן דיווח', 'פעיל', 'מפקד']:
            if col not in df.columns: df[col] = "" 
        valid_true = ['true', '1', 'v', 'yes', 'כן', 'true.0', 't']
        df['נוכח'] = df['נוכח'].astype(str).str.strip().str.lower().isin(valid_true)
        df['פעיל'] = df['פעיל'].astype(str).str.strip().str.lower().isin(valid_true)
        return df
    except Exception as e:
        st.error(f"תקלה בטעינת הנתונים: {e}")
        return pd.DataFrame()

def save_changes_to_cloud(df_to_save):
    df_copy = df_to_save.copy()
    df_copy['נוכח'] = df_copy['נוכח'].apply(lambda x: 'TRUE' if x else 'FALSE')
    df_copy['פעיל'] = df_copy['פעיל'].apply(lambda x: 'TRUE' if x else 'FALSE')
    try:
        run_with_retry(lambda: conn.update(worksheet="Sheet1", data=df_copy))
        st.cache_data.clear()
    except Exception as e:
        st.warning(f"שגיאת שמירה: {e}")

def send_push(active_df):
    app_link = "https://attendace-4wq3edrxk6hwohjswi4hjm.streamlit.app/"
    count = 0
    total = len(active_df)
    if total == 0: return 0
    my_bar = st.progress(0, text="שולח התראות...")
    for index, row in active_df.iterrows():
        mi = "".join(filter(str.isdigit, str(row['מספר אישי'])))
        if not mi: continue
        try:
            requests.post(f"https://ntfy.sh/toto_{mi}", 
                data="Attendance Check is open".encode('utf-8'),
                headers={
                    "Title": "נוכחות גרביל".encode('utf-8').decode('latin-1'),
                    "Message": "בוקר טוב! נפתח דיווח נוכחות.".encode('utf-8').decode('latin-1'),
                    "Click": app_link, "Priority": "high", "Tags": "warning"
                }, timeout=10)
            count += 1
            my_bar.progress(count / total)
        except: pass
    time.sleep(1); my_bar.empty()
    return count

# --- 3. ניהול מצב ---
if "master_df" not in st.session_state:
    st.session_state.master_df = load_data_from_cloud()

# --- סרגל צד (יוצג רק במחשב) ---
with st.sidebar:
    st.header("⚙️ מנהל (מחשב)")
    if st.button("🔄 רענן נתונים", key="side_ref"):
        st.cache_data.clear()
        st.session_state.master_df = load_data_from_cloud()
        st.rerun()
    with st.expander("➕ הוספת חייל"):
        n_name = st.text_input("שם:")
        n_mi = st.text_input("מ.א:")
        if st.button("הוסף"):
            if n_name and n_mi:
                new_row = pd.DataFrame([{"שם מלא": n_name, "מסגרת": "1", "מספר אישי": n_mi.strip(), "מפקד": False, "נוכח": False, "זמן דיווח": "", "פעיל": True}])
                st.session_state.master_df = pd.concat([st.session_state.master_df, new_row], ignore_index=True)
                save_changes_to_cloud(st.session_state.master_df)
                st.rerun()
    if st.button("🔄 למחזור דיווח חדש"):
        st.session_state.master_df['נוכח'] = False
        save_changes_to_cloud(st.session_state.master_df)
        send_push(st.session_state.master_df[st.session_state.master_df['פעיל'] == True])
        st.rerun()

# --- 4. לוגיקה ראשית (מותאמת לסלולר) ---
df = st.session_state.master_df

# כפתור רענון ראשי (תמיד גלוי, גם בטלפון)
if st.button("🔄 רענן נתונים"):
    st.cache_data.clear()
    st.session_state.master_df = load_data_from_cloud()
    st.rerun()

if not df.empty:
    active_mask = (df['פעיל'] == True)
    total_present = len(df[active_mask & (df['נוכח'] == True)])
    total_active = len(df[active_mask])
    st.progress(total_present / total_active if total_active > 0 else 0, text=f"נוכחים: {total_present}/{total_active}")

    st.divider()
    frames = sorted(df['מסגרת'].unique().tolist())
    selected_frame = st.selectbox("מחלקה:", frames)
    
    if 'show_inactive_view' not in st.session_state: st.session_state.show_inactive_view = False
    if st.button("👁️ " + ("פעילים" if st.session_state.show_inactive_view else "לא פעילים")):
        st.session_state.show_inactive_view = not st.session_state.show_inactive_view
        st.rerun()
        
    is_active_view = not st.session_state.show_inactive_view
    frame_mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == is_active_view)
    display_df = df.loc[frame_mask, ['נוכח', 'פעיל', 'שם מלא', 'מספר אישי', 'מפקד']].copy()
    
    if is_active_view and st.checkbox(f"✅ סמן הכל ({selected_frame})", key=f"all_{selected_frame}"):
        display_df['נוכח'] = True

    edited_df = st.data_editor(display_df, column_config={"נוכח": st.column_config.CheckboxColumn("🟢", width="small"), "פעיל": st.column_config.CheckboxColumn("V", width="small")}, disabled=["שם מלא", "מספר אישי", "מפקד"], hide_index=True, use_container_width=True)

    if not edited_df.equals(display_df):
        if st.button("💾 שמור שינויים"):
            current_time = datetime.now().strftime("%H:%M")
            for _, row in edited_df.iterrows():
                mi = row['מספר אישי']
                idx = st.session_state.master_df.index[st.session_state.master_df['מספר אישי'] == mi].tolist()[0]
                st.session_state.master_df.at[idx, 'נוכח'] = row['נוכח']
                st.session_state.master_df.at[idx, 'פעיל'] = row['פעיל']
                if row['נוכח'] and not df.at[idx, 'נוכח']: st.session_state.master_df.at[idx, 'זמן דיווח'] = current_time
            save_changes_to_cloud(st.session_state.master_df)
            st.rerun()
