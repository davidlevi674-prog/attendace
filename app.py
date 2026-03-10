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
    .stApp { background-color: #4B5320; color: white; direction: rtl; text-align: right; }
    div[data-testid="stText"], div[data-testid="stMarkdownContainer"] { text-align: right; direction: rtl; }
    h1, h2, h3, h4, span, label, p { color: white !important; }
    div[data-testid="stDataEditor"] { direction: rtl; }
    </style>
    """, unsafe_allow_html=True)

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

def send_push(active_df):
    app_link = "https://attendace-4wq3edrxk6hwohjswi4hjm.streamlit.app/"
    count = 0
    my_bar = st.progress(0, text="שולח התראות...")
    total = len(active_df)
    for index, row in active_df.iterrows():
        mi = str(row['מספר אישי']).strip()
        try:
            requests.post(f"https://ntfy.sh/h226_{mi}", 
                data="בוקר טוב! נפתח דיווח נוכחות. לחץ למילוי.",
                headers={"Title": "🇮🇱 נוכחות גרביל", "Click": app_link, "Tags": "warning"})
            count += 1
            my_bar.progress(count / total)
        except: pass
    my_bar.empty()
    return count

# --- 3. ה"מוח" המקומי של האפליקציה ---
if "master_df" not in st.session_state:
    st.session_state.master_df = load_data_from_cloud()

# --- 4. לוגיקה ראשית ---

col_ref, col_info = st.columns([1, 4])
with col_ref:
    if st.button("🔄 רענן נתונים מגוגל"):
        # רק הכפתור הזה מושך נתונים חדשים מגוגל!
        st.cache_data.clear()
        st.session_state.master_df = load_data_from_cloud()
        st.rerun()

# חישוב סטטיסטיקה מתוך הזיכרון המקומי
df = st.session_state.master_df
active_mask = df['פעיל'] == True
total_present = len(df[active_mask & (df['נוכח'] == True)])
total_active = len(df[active_mask])

with col_info:
    st.progress(total_present / total_active if total_active > 0 else 0, 
                text=f"סה''כ נוכחים: {total_present} מתוך {total_active}")

st.divider()

if not df.empty:
    frames = sorted(df['מסגרת'].unique().tolist())
    selected_frame = st.selectbox("בחר מחלקה לצפייה וסימון:", frames)
    
    frame_mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == True)
    
    # שואבים את הנתונים לתצוגה מתוך הזיכרון המקומי!
    display_df = df.loc[frame_mask, ['נוכח', 'שם מלא', 'מספר אישי', 'מפקד']].copy()
    
    # צ'קבוקס חכם
    select_all_key = f"select_all_{selected_frame}"
    if st.checkbox(f"✅ סמן את כל מחלקה {selected_frame}", key=select_all_key):
        display_df['נוכח'] = True 
        
    editor_key = f"editor_{selected_frame}"
    edited_df = st.data_editor(
        display_df,
        column_config={
            "נוכח": st.column_config.CheckboxColumn("🟢 ירוק", default=False),
            "מפקד": st.column_config.CheckboxColumn("מפקד?", disabled=True),
            "שם מלא": st.column_config.TextColumn("שם מלא", disabled=True),
            "מספר אישי": st.column_config.TextColumn("מספר אישי", disabled=True),
        },
        disabled=["שם מלא", "מספר אישי", "מפקד"],
        hide_index=True,
        key=editor_key,
        use_container_width=True
    )

    if not edited_df.equals(display_df):
        st.warning("⚠️ ביצעת שינויים בנוכחות. לחץ כאן כדי לשמור בענן:")
        
        if st.button("💾 שמור נתונים", type="primary", use_container_width=True):
            current_time = datetime.now().strftime("%H:%M")
            
            # 1. מעדכנים קודם כל את הזיכרון המקומי!!
            for _, row in edited_df.iterrows():
                mi = row['מספר אישי']
                new_val = row['נוכח']
                
                df_indices = st.session_state.master_df.index[st.session_state.master_df['מספר אישי'] == mi].tolist()
                if df_indices:
                    idx = df_indices[0]
                    old_val = st.session_state.master_df.at[idx, 'נוכח']
                    
                    st.session_state.master_df.at[idx, 'נוכח'] = new_val
                    if new_val == True and old_val == False:
                        st.session_state.master_df.at[idx, 'זמן דיווח'] = current_time
            
            # 2. שולחים לגוגל בשקט
            with st.spinner('מעדכן נתונים בענן...'):
                save_changes_to_cloud(st.session_state.master_df)
                
                # מוחקים את זכרון העורך כדי שלא יפריע
                if select_all_key in st.session_state:
                    del st.session_state[select_all_key]
                if editor_key in st.session_state:
                    del st.session_state[editor_key]
                
                st.success("הנתונים נשמרו בהצלחה!")
                time.sleep(0.5)
                st.rerun()

# --- כפתורי ניהול בסרגל צד ---
with st.sidebar:
    st.header("מנהל")
    if st.button("🔄 התחל יום חדש + שלח התראות"):
        st.session_state.master_df['נוכח'] = False
        st.session_state.master_df['זמן דיווח'] = ""
        
        with st.spinner("מאפס יום חדש..."):
            save_changes_to_cloud(st.session_state.master_df)
            
            for key in list(st.session_state.keys()):
                if key.startswith("editor_") or key.startswith("select_all_"):
                    del st.session_state[key]
                    
            active_soldiers = st.session_state.master_df[st.session_state.master_df['פעיל'] == True]
            count = send_push(active_soldiers)
            st.success(f"נשלחו {count} התראות. יום חדש התחיל!")
            time.sleep(2)
            st.rerun()
