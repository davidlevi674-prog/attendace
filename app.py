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
    /* עיצוב הטבלה */
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

# --- 2. מנגנון חיבור חכם ---
conn = st.connection("gsheets", type=GSheetsConnection)

def run_with_retry(func, retries=3, delay=2):
    """מנגנון ניסיון חוזר למניעת קריסות מול גוגל"""
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
    """טוען נתונים מהענן עם המרה חסינה לשגיאות"""
    try:
        df = run_with_retry(lambda: conn.read(worksheet="Sheet1", ttl=5))
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
            
        # המרה קפדנית ובטוחה של בוליאנים
        valid_true = ['true', '1', 'v', 'yes', 'כן', 'true.0']
        df['נוכח'] = df['נוכח'].astype(str).str.strip().str.lower().isin(valid_true)
        
        valid_false = ['false', '0', 'no', 'לא', 'false.0']
        df['פעיל'] = ~df['פעיל'].astype(str).str.strip().str.lower().isin(valid_false)
        
        return df
    except Exception as e:
        st.error("תקלה בטעינת הנתונים, נסה לרענן.")
        return pd.DataFrame()

def save_changes_to_cloud(df_to_save):
    """שומר לענן בפורמט שגוגל מבין בוודאות"""
    df_copy = df_to_save.copy()
    
    # המרה לטקסט מפורש כדי שגוגל שיטס לא יתבלבל בין פורמטים
    df_copy['נוכח'] = df_copy['נוכח'].apply(lambda x: 'TRUE' if x else 'FALSE')
    df_copy['פעיל'] = df_copy['פעיל'].apply(lambda x: 'TRUE' if x else 'FALSE')
    
    try:
        run_with_retry(lambda: conn.update(worksheet="Sheet1", data=df_copy))
    except Exception as e:
        st.warning(f"שגיאת שמירה זמנית (עומס): {e}")

# --- 3. שליחת התראות ---
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

# --- 4. לוגיקה ראשית ---

# טעינה מהענן (או מהמטמון)
df = load_data_from_cloud()
original_df = df.copy()

col_ref, col_info = st.columns([1, 4])
with col_ref:
    if st.button("🔄 רענן נתונים"):
        st.cache_data.clear() # כופה משיכה טרייה מגוגל
        st.rerun()

# --- חישוב סטטיסטיקה (מתעדכן מיד לאחר ריענון) ---
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
    display_df = df.loc[frame_mask, ['נוכח', 'שם מלא', 'מספר אישי', 'מפקד']].copy()
    
    # --- הפתרון המבוקש: צ'קבוקס "סמן הכל" מעל הטבלה ---
    select_all_key = f"select_all_{selected_frame}"
    if st.checkbox(f"✅ סמן את כל מחלקה {selected_frame}", key=select_all_key):
        display_df['נוכח'] = True # מדליק הכל לפני הצגת הטבלה
        
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
        key=editor_key, # מפתח ייחודי לכל מחלקה! מונע מחיקת זיכרון במעבר
        use_container_width=True
    )

    # --- מנגנון השמירה ---
    original_frame_df = original_df.loc[frame_mask, ['נוכח', 'שם מלא', 'מספר אישי', 'מפקד']]
    
    if not edited_df.equals(original_frame_df):
        st.warning("⚠️ ביצעת שינויים בנוכחות. לחץ כאן כדי לשמור בענן:")
        
        if st.button("💾 שמור נתונים", type="primary", use_container_width=True):
            df.update(edited_df)
            current_time = datetime.now().strftime("%H:%M")
            
            # עדכון זמני הגעה רק לאלו שסימנו אותם עכשיו
            for idx in edited_df.index:
                old_val = original_df.loc[idx, 'נוכח']
                new_val = edited_df.loc[idx, 'נוכח']
                if new_val == True and old_val == False:
                    df.at[idx, 'זמן דיווח'] = current_time
            
            with st.spinner('שולח נתונים לגוגל...'):
                save_changes_to_cloud(df)
                
                # התיקון הקריטי: מחיקת כל זיכרון ישן כדי להכריח את האפליקציה למשוך את החדש
                st.cache_data.clear()
                
                if select_all_key in st.session_state:
                    st.session_state[select_all_key] = False # מכבה את הצ'קבוקס העליון חזרה
                
                if editor_key in st.session_state:
                    del st.session_state[editor_key] # מנקה את העורך
                
                st.success("הנתונים נשמרו בהצלחה!")
                time.sleep(1)
                st.rerun()

# --- כפתורי ניהול בסרגל צד ---
with st.sidebar:
    st.header("מנהל")
    if st.button("🔄 התחל יום חדש + שלח התראות"):
        df['נוכח'] = False
        df['זמן דיווח'] = ""
        save_changes_to_cloud(df)
        st.cache_data.clear()
        
        # ניקוי העורכים כדי שיראו מסך נקי
        for key in list(st.session_state.keys()):
            if key.startswith("editor_") or key.startswith("select_all_"):
                del st.session_state[key]
                
        active_soldiers = df[df['פעיל'] == True]
        count = send_push(active_soldiers)
        st.success(f"נשלחו {count} התראות. יום חדש התחיל!")
        time.sleep(2)
        st.rerun()
