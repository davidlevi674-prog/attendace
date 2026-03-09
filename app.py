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
    """טוען נתונים מהענן"""
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
            
        df['נוכח'] = df['נוכח'].apply(lambda x: True if str(x).lower() in ['true', '1', 'v'] else False)
        df['פעיל'] = df['פעיל'].apply(lambda x: False if str(x).lower() in ['false', '0'] else True)
        
        return df
    except Exception as e:
        st.error("תקלה בטעינת הנתונים, נסה לרענן.")
        return pd.DataFrame()

def save_changes_to_cloud(df_to_save):
    """שומר את הטבלה המעודכנת לענן"""
    try:
        run_with_retry(lambda: conn.update(worksheet="Sheet1", data=df_to_save))
        st.cache_data.clear()
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

# טעינה ישירה
df = load_data_from_cloud()

col_ref, col_info = st.columns([1, 4])
with col_ref:
    if st.button("🔄 רענן נתונים"):
        st.cache_data.clear() # מנקה את הזיכרון כדי לאלץ קריאה חדשה
        st.rerun()

# חישוב סטטיסטיקה מתוך df
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
    display_df = df.loc[frame_mask, ['נוכח', 'שם מלא', 'מספר אישי', 'מפקד']]
    
    # 🟢 צביעת עמודת הנוכחות ברקע ירוק עדין
    styled_df = display_df.style.map(lambda _: 'background-color: rgba(40, 167, 69, 0.2);', subset=['נוכח'])
    
    edited_df = st.data_editor(
        styled_df, # הכנסנו את הטבלה הצבועה לכאן
        column_config={
            "נוכח": st.column_config.CheckboxColumn("🟢 הגיע?", default=False),
            "מפקד": st.column_config.CheckboxColumn("מפקד?", disabled=True),
             "שם מלא": st.column_config.TextColumn("שם מלא", disabled=True),
             "מספר אישי": st.column_config.TextColumn("מספר אישי", disabled=True),
        },
        disabled=["שם מלא", "מספר אישי", "מפקד"],
        hide_index=True,
        key="editor",
        use_container_width=True
    )

    if not edited_df.equals(display_df):
        st.warning("⚠️ ביצעת שינויים בטבלה. לחץ על הכפתור כדי לשמור אותם בענן:")
        
        # כפתור שמירה
        if st.button("💾 שמור נוכחות", type="primary", use_container_width=True):
            df.update(edited_df)
            current_time = datetime.now().strftime("%H:%M")
            
            for idx in edited_df.index:
                old_val = display_df.loc[idx, 'נוכח']
                new_val = edited_df.loc[idx, 'נוכח']
                if new_val and not old_val:
                    df.at[idx, 'זמן דיווח'] = current_time
            
            with st.spinner('שולח נתונים לגוגל...'):
                save_changes_to_cloud(df)
                
                # מחיקת הזיכרון לאחר שמירה
                if 'editor' in st.session_state:
                    del st.session_state['editor']
                    
                st.success("השינויים נשמרו בהצלחה!")
                time.sleep(1)
                st.rerun()

# --- כפתורי ניהול ---
with st.sidebar:
    st.header("מנהל")
    if st.button("🔄 התחל יום חדש + שלח התראות"):
        df['נוכח'] = False
        df['זמן דיווח'] = ""
        save_changes_to_cloud(df)
        
        # מחיקת זיכרון העורך כדי להעלים את ה-Vים מהמסך
        if 'editor' in st.session_state:
            del st.session_state['editor']
            
        active_soldiers = df[df['פעיל'] == True]
        count = send_push(active_soldiers)
        st.success(f"נשלחו {count} התראות")
        time.sleep(2)
        st.rerun()

    st.divider()
    
    if 'selected_frame' in locals():
        if st.button(f"✅ סמן את כל מחלקה {selected_frame} כנוכחים"):
            mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == True)
            df.loc[mask, 'נוכח'] = True
            df.loc[mask, 'זמן דיווח'] = datetime.now().strftime("%H:%M")
            save_changes_to_cloud(df)
            
            # 🛠️ התיקון הקריטי: מחיקת זיכרון העורך כדי להכריח את ה-Vים להופיע!
            if 'editor' in st.session_state:
                del st.session_state['editor']
                
            st.rerun()
