import streamlit as st
import pandas as pd
from datetime import datetime
import urllib.parse
from streamlit_gsheets import GSheetsConnection
import requests
import time

# 1. הגדרות דף ועיצוב
st.set_page_config(page_title="נוכחות חטיבה 226", layout="centered", page_icon="🇮🇱")

st.markdown("""
    <style>
    .stApp { background-color: #4B5320; color: white; direction: rtl; text-align: right; }
    div[data-testid="stText"], div[data-testid="stMarkdownContainer"] { text-align: right; direction: rtl; }
    .stButton>button { background-color: #D4AF37; color: black; font-weight: bold; border-radius: 10px; width: 100%; border: none; }
    .stTextInput>div>div>input { background-color: #f0f2f6; text-align: right; color: black; }
    h1, h2, h3, h4, span, label, p { color: white !important; }
    .stCheckbox { direction: rtl; text-align: right; }
    .stDataFrame { direction: rtl; }
    </style>
    """, unsafe_allow_html=True)

# לוגו
col1, col2, col3 = st.columns([1,1,1])
with col2:
    st.image("https://upload.wikimedia.org/wikipedia/he/3/30/226_Tag.png", width=150)

st.title("🇮🇱 ניהול נוכחות - חטיבה 226")

# 2. חיבור ל-Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(worksheet="Sheet1", ttl=0)
        df.columns = df.columns.str.strip()
        
        def clean_frame(val):
            if pd.isna(val): return "ללא מחלקה"
            try:
                f_val = float(val)
                return str(int(f_val)) if f_val.is_integer() else str(val)
            except: return str(val)
        
        if 'מסגרת' in df.columns:
            df['מסגרת'] = df['מסגרת'].apply(clean_frame)
            
        # ניקוי מספר אישי (חשוב מאוד להתראות!)
        if 'מספר אישי' in df.columns:
             df['מספר אישי'] = df['מספר אישי'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        for col in ['נוכח', 'זמן דיווח', 'פעיל', 'מפקד']:
            if col not in df.columns: df[col] = "" 
        
        df['נוכח'] = df['נוכח'].apply(lambda x: True if str(x).lower() in ['true', '1', 'v'] else False)
        df['פעיל'] = df['פעיל'].apply(lambda x: False if str(x).lower() in ['false', '0'] else True)
        return df
    except Exception as e:
        st.error(f"שגיאה בחיבור לגוגל שיטס: {e}")
        st.stop()

def save_data(df_to_save):
    try:
        conn.update(worksheet="Sheet1", data=df_to_save)
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.error(f"שגיאה בשמירה: {e}")

# --- פונקציה חכמה לשליחת התראות אישיות ---
def send_targeted_notifications(active_df):
    # הקישור לאפליקציה שלך (חשוב: תחליף בקישור האמיתי כשתעלה לענן)
    app_link = "https://attendance-226.streamlit.app"
    
    count = 0
    progress_text = "שולח התראות לחיילים פעילים..."
    my_bar = st.progress(0, text=progress_text)
    total = len(active_df)
    
    for index, row in active_df.iterrows():
        mi = str(row['מספר אישי']).strip()
        
        # בניית הערוץ האישי: h226_ + מספר אישי
        topic = f"h226_{mi}"
        
        try:
            requests.post(f"https://ntfy.sh/{topic}", 
                data="בוקר טוב! נפתח דיווח נוכחות. לחץ כאן למילוי.",
                headers={
                    "Title": "🇮🇱 חטיבה 226 - נוכחות",
                    "Click": app_link,
                    "Priority": "high",
                    "Tags": "warning,flag-il"
                }
            )
            count += 1
            # עדכון בר ההתקדמות
            my_bar.progress(count / total, text=f"נשלח ל-{row['שם מלא']} ({count}/{total})")
            time.sleep(0.05) # השהייה קטנה כדי לא להעמיס
        except:
            pass
            
    my_bar.empty() # העלמת הבר בסיום
    return count

# טעינת נתונים
df = load_data()

# --- סרגל צד ---
with st.sidebar:
    st.header("⚙️ ניהול סד''כ")
    
    with st.expander("➕ הוספת חייל חדש"):
        n_name = st.text_input("שם מלא:")
        n_mi = st.text_input("מספר אישי:")
        frames_list = sorted(df['מסגרת'].unique().tolist()) if 'מסגרת' in df.columns else ["1"]
        n_frame = st.selectbox("מסגרת:", frames_list)
        n_is_comm = st.checkbox("מפקד?")
        
        if st.button("הוסף לענן"):
            if n_name and n_mi:
                new_row = pd.DataFrame([{
                    "שם מלא": n_name, "מסגרת": str(n_frame), "מספר אישי": n_mi, 
                    "מפקד": n_is_comm, "נוכח": False, "זמן דיווח": "", "פעיל": True
                }])
                updated_df = pd.concat([df, new_row], ignore_index=True)
                save_data(updated_df)

    st.divider()
    
    st.subheader("ניהול יומי")
    if st.button("🔄 התחל מחזור + שלח התראות"):
        # 1. איפוס הנתונים
        df['נוכח'] = False
        df['זמן דיווח'] = ""
        conn.update(worksheet="Sheet1", data=df) # שמירה ללא rerun עדיין
        
        # 2. שליחת התראות רק לפעילים
        active_soldiers = df[df['פעיל'] == True]
        
        if not active_soldiers.empty:
            sent_count = send_targeted_notifications(active_soldiers)
            st.success(f"המחזור אופס! נשלחו התראות ל-{sent_count} חיילים פעילים.")
        else:
            st.warning("המחזור אופס, אך לא נמצאו חיילים פעילים לשליחת התראה.")
            
        time.sleep(2) # לתת זמן לקרוא את ההודעה
        st.rerun()

# --- תצוגה ראשית ---
search_term = st.text_input("🔍 חיפוש חייל:", "")

active_mask = df['פעיל'] == True
total_active = len(df[active_mask])
total_present = len(df[active_mask & (df['נוכח'] == True)])

st.progress(total_present / total_active if total_active > 0 else 0, 
            text=f"דיווחו {total_present} מתוך {total_active} פעילים")

frames = sorted(df['מסגרת'].unique().tolist())

if frames:
    tabs = st.tabs(frames)
    for i, frame in enumerate(frames):
        with tabs[i]:
            if st.button(f"✅ סמן את כל {frame} כנוכחים", key=f"all_{frame}"):
                mask = (df['מסגרת'] == frame) & (df['פעיל'] == True)
                df.loc[mask, 'נוכח'] = True
                df.loc[mask, 'זמן דיווח'] = datetime.now().strftime("%H:%M")
                save_data(df)

            st.divider()
            
            frame_data = df[df['מסגרת'] == frame]
            for idx, row in frame_data.iterrows():
                name = str(row['שם מלא'])
                mi = str(row['מספר אישי'])
                
                if not search_term or search_term in name or search_term in mi:
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        is_comm = str(row['מפקד']).strip().lower() in ['true', 'v', '1', 'כן']
                        tag = "⭐ " if is_comm else ""
                        if row['פעיל']:
                            val = st.checkbox(f"{tag}{name} ({mi})", value=row['נוכח'], key=f"c_{idx}")
                            if val != row['נוכח']:
                                df.at[idx, 'נוכח'] = val
                                df.at[idx, 'זמן דיווח'] = datetime.now().strftime("%H:%M") if val else ""
                                save_data(df)
                        else:
                            st.write(f"~~{name}~~ (לא פעיל)")
                    with c2:
                        icon = "❌" if row['פעיל'] else "✅"
                        if st.button(icon, key=f"btn_{idx}", help="השבת/החזר"):
                            df.at[idx, 'פעיל'] = not row['פעיל']
                            if not df.at[idx, 'פעיל']: df.at[idx, 'נוכח'] = False
                            save_data(df)

# סיכום
st.divider()
missing = df[active_mask & (df['נוכח'] == False)]['שם מלא'].tolist()
if not missing and total_active > 0:
    st.success("🏁 כולם נוכחים!")
    msg = urllib.parse.quote(f"דיווח נוכחות חטיבה 226 הושלם!\nסה''כ: {total_present} נוכחים.")
    st.link_button("📲 שלח עדכון בוואטסאפ", f"https://wa.me/?text={msg}")
elif total_active > 0:
    st.warning(f"⚠️ חסרים עוד {len(missing)} אנשים.")