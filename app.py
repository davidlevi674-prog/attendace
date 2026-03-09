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
        # ttl=5 מאפשר בדיקה תכופה יחסית של נתונים חדשים מאחרים
        df = run_with_retry(lambda: conn.read(worksheet="Sheet1", ttl=5))
        df.columns = df.columns.str.strip()
        
        # המרות וניקוי
        def clean_frame(val):
            if pd.isna(val): return "ללא מחלקה"
            try: return str(int(float(val))) if float(val).is_integer() else str(val)
            except: return str(val)
            
        if 'מסגרת' in df.columns: df['מסגרת'] = df['מסגרת'].apply(clean_frame)
        if 'מספר אישי' in df.columns: 
            df['מספר אישי'] = df['מספר אישי'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            
        # ווידוא עמודות
        for col in ['נוכח', 'זמן דיווח', 'פעיל', 'מפקד']:
            if col not in df.columns: df[col] = "" 
            
        # המרה לבוליאני (חשוב מאוד לטבלה)
        df['נוכח'] = df['נוכח'].apply(lambda x: True if str(x).lower() in ['true', '1', 'v'] else False)
        df['פעיל'] = df['פעיל'].apply(lambda x: False if str(x).lower() in ['false', '0'] else True)
        
        return df
    except Exception as e:
        st.error("תקלה בטעינת הנתונים, נסה לרענן.")
        return pd.DataFrame()

def save_changes_to_cloud(df):
    """שומר את הטבלה המעודכנת לענן"""
    try:
        run_with_retry(lambda: conn.update(worksheet="Sheet1", data=df))
        st.cache_data.clear() # ניקוי מטמון כדי שנראה את השינוי מיד
    except Exception as e:
        st.warning(f"שגיאת שמירה זמנית (עומס): {e}")

# --- 3. שליחת התראות (לפי הקוד הקודם) ---
def send_push(active_df):
    app_link = "https://attendance-226.streamlit.app" # אל תשכח לעדכן ללינק האמיתי
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

df = load_data_from_cloud()

# כפתור רענון ידני (לראות מה אחרים סימנו)
col_ref, col_info = st.columns([1, 4])
with col_ref:
    if st.button("🔄 רענן נתונים"):
        st.session_state.data = load_data_from_cloud()
        st.rerun()

# חישוב סטטיסטיקה
df = st.session_state.data
active_mask = df['פעיל'] == True
total_present = len(df[active_mask & (df['נוכח'] == True)])
total_active = len(df[active_mask])

with col_info:
    st.progress(total_present / total_active if total_active > 0 else 0, 
                text=f"סה''כ נוכחים: {total_present} מתוך {total_active}")

st.divider()

# --- התצוגה המרכזית: טבלה עריכה ---
# אנחנו מציגים רק את העמודות הרלוונטיות לעריכה
# המשתמש יכול לסמן הרבה Vים, ורק בסוף הפעולה זה יישלח
if not df.empty:
    # פילטר לפי מחלקה (טאבים)
    frames = sorted(df['מסגרת'].unique().tolist())
    selected_frame = st.selectbox("בחר מחלקה לצפייה וסימון:", frames)
    
    # סינון הנתונים לתצוגה
    frame_mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == True)
    display_df = df.loc[frame_mask, ['נוכח', 'שם מלא', 'מספר אישי', 'מפקד']]
    
    # הגדרות הטבלה
    edited_df = st.data_editor(
        display_df,
        column_config={
            "נוכח": st.column_config.CheckboxColumn(
                "הגיע?",
                help="סמן אם החייל נוכח",
                default=False,
            ),
            "מפקד": st.column_config.CheckboxColumn(
                "מפקד?",
                disabled=True # אי אפשר לשנות מפקד מכאן
            ),
             "שם מלא": st.column_config.TextColumn(
                "שם מלא",
                disabled=True
            ),
             "מספר אישי": st.column_config.TextColumn(
                "מספר אישי",
                disabled=True
            ),
        },
        disabled=["שם מלא", "מספר אישי", "מפקד"], # רק נוכחות ניתנת לעריכה
        hide_index=True,
        key="editor",
        use_container_width=True
    )

    # --- מנגנון השמירה החכם ---
    # כאן הקסם קורה: אנחנו משווים את מה שהמשתמש רואה לבין מה שהיה בזיכרון
    # אם יש הבדל - אנחנו מעדכנים את הטבלה הראשית ושומרים לענן
    
    # בדיקה האם היו שינויים בטבלה
    if not edited_df.equals(display_df):
        # עדכון הטבלה הראשית (df) עם הנתונים החדשים מהטבלה הקטנה (edited_df)
        df.update(edited_df)
        
        # עדכון זמני דיווח למי שסומן כעת
        # (לוגיקה: מי שסומן כנוכח ואין לו זמן דיווח, או שסימונו השתנה)
        current_time = datetime.now().strftime("%H:%M")
        
        # לולאה לעדכון זמנים רק למי ששינה סטטוס
        for idx in edited_df.index:
            old_val = display_df.loc[idx, 'נוכח']
            new_val = edited_df.loc[idx, 'נוכח']
            if new_val and not old_val: # אם סומן כרגע
                df.at[idx, 'זמן דיווח'] = current_time
        
        # שמירה לענן
        with st.spinner('שומר שינויים בענן...'):
            save_changes_to_cloud(df)
            st.session_state.data = df # עדכון הזיכרון המקומי
            st.success("השינויים נשמרו בהצלחה!")
            time.sleep(1) # לתת למשתמש לראות את הוי
            st.rerun()

# --- כפתורי ניהול בסרגל צד ---
with st.sidebar:
    st.header("מנהל")
    if st.button("🔄 התחל יום חדש + שלח התראות"):
        df['נוכח'] = False
        df['זמן דיווח'] = ""
        save_changes_to_cloud(df)
        st.session_state.data = df
        
        active_soldiers = df[df['פעיל'] == True]
        count = send_push(active_soldiers)
        st.success(f"נשלחו {count} התראות")
        time.sleep(2)
        st.rerun()

    # אפשרות לסימון גורף למחלקה הנוכחית (פתרון ל"סמן הכל")
    st.divider()
    if st.button(f"✅ סמן את כל מחלקה {selected_frame} כנוכחים"):
        mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == True)
        df.loc[mask, 'נוכח'] = True
        df.loc[mask, 'זמן דיווח'] = datetime.now().strftime("%H:%M")
        save_changes_to_cloud(df)
        st.session_state.data = df
        st.rerun()
