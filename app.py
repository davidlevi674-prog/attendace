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
    div[data-baseweb="input"] input { color: black !important; }
    div[data-baseweb="select"] span { color: black !important; }
    
    /* מחיקת הסרגל הצדדי */
    [data-testid="collapsedControl"] { display: none !important; }
    [data-testid="stSidebar"] { display: none !important; }
    
    .main .block-container { padding-top: 2rem !important; }

    /* עיצוב כפתורים */
    div.stButton > button { 
        background-color: #D4AF37 !important; 
        border-radius: 10px !important; 
        border: none !important; 
        color: black !important;
        font-weight: bold !important;
        width: 100%;
        height: 3em;
    }
    
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

# --- 2. חיבור ועיבוד נתונים ---
conn = st.connection("gsheets", type=GSheetsConnection)

def run_with_retry(func, retries=3, delay=1):
    for i in range(retries):
        try: return func()
        except Exception as e:
            if i < retries - 1:
                time.sleep(delay)
                continue
            raise e

def parse_bool(val):
    # פונקציה חסינת-כדורים להמרת כל ערך מגוגל לאמת/שקר
    if isinstance(val, bool): return val
    if pd.isna(val): return False
    val_str = str(val).strip().lower()
    return val_str in ['true', '1', '1.0', 'v', 'yes', 'כן', 't']

def load_data_from_cloud(force_fresh=False):
    try:
        # שימוש ב-ttl=0 עוקף כל מטמון ומביא נתונים ישירות מגוגל
        ttl_val = 0 if force_fresh else 2
        df = run_with_retry(lambda: conn.read(worksheet="Sheet1", ttl=ttl_val))
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
            
        # שימוש בפונקציה החדשה והחזקה
        df['נוכח'] = df['נוכח'].apply(parse_bool)
        df['פעיל'] = df['פעיל'].apply(parse_bool)
        
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
        st.cache_data.clear() # ניקוי מטמון כללי לאחר שמירה
    except Exception as e:
        st.warning(f"שגיאת שמירה: {e}")

def send_push(active_df):
    app_link = "https://attendace-4wq3edrxk6hwohjswi4hjm.streamlit.app/"
    count = 0
    total = len(active_df)
    if total == 0: return 0
    
    my_bar = st.progress(0, text="שולח התראות לפלוגה...")
    for index, row in active_df.iterrows():
        mi = "".join(filter(str.isdigit, str(row['מספר אישי'])))
        if not mi: continue
        try:
            requests.post(f"https://ntfy.sh/toto_{mi}", 
                data="Attendance Check is open".encode('utf-8'),
                headers={
                    "Title": "נוכחות גרביל".encode('utf-8').decode('latin-1'),
                    "Message": "דיווח ירוק פלוגתי החל. היכנס לסמן שאתה בסדר!".encode('utf-8').decode('latin-1'),
                    "Click": app_link, "Priority": "high", "Tags": "warning"
                }, timeout=5)
            count += 1
            my_bar.progress(count / total)
        except: pass
    time.sleep(1); my_bar.empty()
    return count

# --- 3. לוגיקה ראשית וממשק ---

col_ref, col_info = st.columns([1, 4])
with col_ref:
    if st.button("🔄 רענן נתונים"):
        st.cache_data.clear() # ניקוי אגרסיבי שיסנכרן את הפלאפון והמחשב
        st.rerun()

df = load_data_from_cloud()

if not df.empty:
    active_mask = (df['פעיל'] == True)
    total_present = len(df[active_mask & (df['נוכח'] == True)])
    total_active = len(df[active_mask])
    
    with col_info:
        st.progress(total_present / total_active if total_active > 0 else 0, 
                    text=f"סה''כ מדווחים: {total_present} מתוך {total_active} (פעילים)")

    st.divider()
    frames = sorted(df['מסגרת'].unique().tolist())
    selected_frame = st.selectbox("בחר מחלקה לדיווח:", frames)
    
    if 'show_inactive_view' not in st.session_state: st.session_state.show_inactive_view = False
    if st.button("👁️ " + ("חזור לרשימת פעילים" if st.session_state.show_inactive_view else "הצג חיילים לא פעילים")):
        st.session_state.show_inactive_view = not st.session_state.show_inactive_view
        st.rerun()
        
    is_active_view = not st.session_state.show_inactive_view
    frame_mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == is_active_view)
    
    original_display_df = df.loc[frame_mask, ['נוכח', 'פעיל', 'שם מלא', 'מספר אישי', 'מפקד']].copy()
    display_df = original_display_df.copy()
    
    if is_active_view:
        if st.checkbox(f"✅ סמן הכל כנוכחים ({selected_frame})", key=f"all_p_{selected_frame}"):
            display_df['נוכח'] = True
    else:
        if st.checkbox(f"✅ סמן הכל כפעילים ({selected_frame})", key=f"all_a_{selected_frame}"):
            display_df['פעיל'] = True

    editor_key = f"ed_{selected_frame}_{st.session_state.show_inactive_view}"
    edited_df = st.data_editor(
        display_df,
        column_config={
            "נוכח": st.column_config.CheckboxColumn("🟢 נמצא?", default=False, width="small"),
            "פעיל": st.column_config.CheckboxColumn("פעיל?", default=True, width="small"),
            "שם מלא": st.column_config.TextColumn("שם מלא"),
        },
        disabled=["שם מלא", "מספר אישי", "מפקד"],
        hide_index=True,
        key=editor_key,
        use_container_width=True
    )

    # מנגנון שמירה חכם שמונע התנגשויות 
    if not edited_df.equals(original_display_df):
        if st.button("💾 שמור דיווח", use_container_width=True):
            with st.spinner("מסנכרן נתונים מול שאר הפלוגה..."):
                current_time = datetime.now().strftime("%H:%M")
                latest_df = load_data_from_cloud(force_fresh=True)
                updated = False
                
                for _, row in edited_df.iterrows():
                    mi = row['מספר אישי']
                    orig_present = original_display_df[original_display_df['מספר אישי'] == mi]['נוכח'].values[0]
                    orig_active = original_display_df[original_display_df['מספר אישי'] == mi]['פעיל'].values[0]
                    
                    if row['נוכח'] != orig_present or row['פעיל'] != orig_active:
                        idx_list = latest_df.index[latest_df['מספר אישי'] == mi].tolist()
                        if idx_list:
                            idx = idx_list[0]
                            old_latest_present = latest_df.at[idx, 'נוכח']
                            latest_df.at[idx, 'נוכח'] = row['נוכח']
                            latest_df.at[idx, 'פעיל'] = row['פעיל']
                            if row['נוכח'] and not old_latest_present: 
                                latest_df.at[idx, 'זמן דיווח'] = current_time
                            updated = True
                
                if updated:
                    save_changes_to_cloud(latest_df)
                    st.success("הדיווח נקלט בהצלחה!")
                    
                    # ניקוי זיכרון הממשק - קריטי כדי לראות את השינוי מיד!
                    if editor_key in st.session_state: del st.session_state[editor_key]
                    if f"all_p_{selected_frame}" in st.session_state: del st.session_state[f"all_p_{selected_frame}"]
                    if f"all_a_{selected_frame}" in st.session_state: del st.session_state[f"all_a_{selected_frame}"]
                
                time.sleep(1)
                st.rerun()

    st.divider()

    # --- 4. אזור מפקדים ---
    with st.expander("⚙️ אזור מפקדים (הוספה, מחיקה ואיפוס)"):
        st.markdown("#### ניהול כוח אדם")
        col_add_name, col_add_mi = st.columns(2)
        n_name = col_add_name.text_input("שם מלא (חייל חדש):")
        n_mi_input = col_add_mi.text_input("מספר אישי (חייל חדש):")
        col_add_frame, col_add_comm = st.columns(2)
        n_frame = col_add_frame.selectbox("מסגרת:", frames)
        n_is_comm = col_add_comm.checkbox("הגדר כמפקד")
        
        if st.button("➕ הוסף חייל לפלוגה"):
            if n_name and n_mi_input:
                latest_df = load_data_from_cloud(force_fresh=True)
                new_row = pd.DataFrame([{"שם מלא": n_name, "מסגרת": str(n_frame), "מספר אישי": str(n_mi_input).strip(), "מפקד": n_is_comm, "נוכח": False, "זמן דיווח": "", "פעיל": True}])
                latest_df = pd.concat([latest_df, new_row], ignore_index=True)
                save_changes_to_cloud(latest_df)
                st.success("החייל הוסף!")
                st.rerun()
            else:
                st.warning("נא למלא שם ומספר אישי.")
                
        st.markdown("---")
        del_mi = st.text_input("הזן מספר אישי למחיקה מוחלטת:")
        if st.button("🗑️ מחק חייל לצמיתות", type="primary"):
            if del_mi:
                latest_df = load_data_from_cloud(force_fresh=True)
                idx_list = latest_df.index[latest_df['מספר אישי'] == del_mi.strip()].tolist()
                if idx_list:
                    latest_df = latest_df.drop(idx_list)
                    save_changes_to_cloud(latest_df)
                    st.success("החייל נמחק מהרישומים!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("המספר האישי לא נמצא במערכת.")

        st.markdown("---")
        st.markdown("#### ניהול אירוע אמת")
        st.warning("פעולה זו תאפס את הסטטוס של כולם ל-'לא נמצא' ותשלח התראות Push לכל החיילים הפעילים.")
        if st.button("🚨 פתח דיווח ירוק פלוגתי (שלח התראות)"):
            latest_df = load_data_from_cloud(force_fresh=True)
            latest_df['נוכח'] = False
            latest_df['זמן דיווח'] = ""
            save_changes_to_cloud(latest_df)
            
            active_soldiers = latest_df[latest_df['פעיל'] == True]
            count = send_push(active_soldiers)
            st.success(f"הלוח אופס! נשלחו {count} התראות לחיילים.")
            time.sleep(3)
            st.rerun()

else:
    st.warning("המערכת ריקה. לא נמצאו נתונים בגיליון.")
