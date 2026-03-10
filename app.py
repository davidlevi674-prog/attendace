import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit_gsheets import GSheetsConnection
import requests
import time
import os

# --- 1. הגדרות ועיצוב (מותאם למניעת דריסת ה-Sidebar) ---
st.set_page_config(page_title="בדיקת נוכחות גרביל", layout="wide", page_icon="logo.png")

st.markdown("""
    <style>
    /* הגדרות כלליות וכיווניות */
    .stApp { background-color: #4B5320; color: white; direction: rtl; text-align: right; }
    [data-testid="stSidebar"] { background-color: #3b4218 !important; }
    div[data-testid="stText"], div[data-testid="stMarkdownContainer"] { text-align: right; direction: rtl; }
    h1, h2, h3, h4, span, label, p { color: white !important; }
    div[data-baseweb="input"] input { color: black !important; }
    div[data-baseweb="select"] span { color: black !important; }
    
    /* פתרון לבעיית ה-Sidebar בסמארטפון */
    @media (max-width: 768px) {
        /* הסתרת הסרגל שלא יצוף מעל התוכן */
        [data-testid="stSidebar"][aria-expanded="true"] {
            width: 80vw !important;
        }
        /* מניעת דריסה של התוכן הראשי */
        .main .block-container { 
            padding-top: 2rem !important; 
            padding-right: 1rem !important; 
            padding-left: 1rem !important; 
        }
        h1 { font-size: 1.4rem !important; margin-top: 10px !important; }
    }

    /* עיצוב כפתורים זהב */
    div.stButton > button { 
        background-color: #D4AF37 !important; 
        border-radius: 10px !important; 
        border: none !important; 
        color: black !important;
        font-weight: bold !important;
    }
    
    /* כפתור מחיקה אדום */
    .stButton button[kind="primary"] {
        background-color: #ff4b4b !important;
        color: white !important;
    }
    
    div[data-testid="stDataEditor"] { direction: rtl; }
    </style>
    """, unsafe_allow_html=True)

# סידור לוגו - בטלפון הוא יהיה קטן יותר כדי לא לתפוס מקום
col1, col2, col3 = st.columns([1,1,1])
with col2:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=100)
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
        st.warning(f"שגיאת שמירה זמנית: {e}")

def send_push(active_df):
    app_link = "https://attendace-4wq3edrxk6hwohjswi4hjm.streamlit.app/"
    count = 0
    total = len(active_df)
    if total == 0: return 0
        
    my_bar = st.progress(0, text="שולח התראות...")
    for index, row in active_df.iterrows():
        mi_raw = str(row['מספר אישי']).strip()
        mi = "".join(filter(str.isdigit, mi_raw))
        if not mi: continue
            
        topic = f"toto_{mi}"
        try:
            requests.post(
                f"https://ntfy.sh/{topic}", 
                data="Attendance Check is open".encode('utf-8'),
                headers={
                    "Title": "נוכחות גרביל".encode('utf-8').decode('latin-1'),
                    "Message": "בוקר טוב! נפתח דיווח נוכחות. לחץ למילוי.".encode('utf-8').decode('latin-1'),
                    "Click": app_link,
                    "Priority": "high",
                    "Tags": "warning"
                },
                timeout=10
            )
            count += 1
            my_bar.progress(count / total)
        except: pass
            
    time.sleep(1)
    my_bar.empty()
    return count

# --- 3. ניהול מצב ---
if "master_df" not in st.session_state:
    st.session_state.master_df = load_data_from_cloud()

with st.sidebar:
    st.header("⚙️ מנהל")
    
    if st.button("🔄 רענן נתונים"):
        st.cache_data.clear()
        st.session_state.master_df = load_data_from_cloud()
        st.rerun()

    with st.expander("➕ הוספת חייל חדש"):
        n_name = st.text_input("שם מלא:")
        n_mi_input = st.text_input("מספר אישי (להוספה):")
        frames_list = sorted(st.session_state.master_df['מסגרת'].unique().tolist()) if not st.session_state.master_df.empty else ["1"]
        n_frame = st.selectbox("מסגרת (מחלקה):", frames_list)
        n_is_comm = st.checkbox("מפקד?")
        if st.button("הוסף לרשימה"):
            if n_name and n_mi_input:
                new_row = pd.DataFrame([{
                    "שם מלא": n_name, "מסגרת": str(n_frame), "מספר אישי": str(n_mi_input).strip(), 
                    "מפקד": n_is_comm, "נוכח": False, "זמן דיווח": "", "פעיל": True
                }])
                st.session_state.master_df = pd.concat([st.session_state.master_df, new_row], ignore_index=True)
                save_changes_to_cloud(st.session_state.master_df)
                st.success("החייל הוסף!")
                st.rerun()

    with st.expander("🗑️ מחיקת חייל לצמיתות"):
        del_mi = st.text_input("מספר אישי למחיקה:")
        if st.button("מחק חייל", type="primary"):
            if del_mi:
                idx_list = st.session_state.master_df.index[st.session_state.master_df['מספר אישי'] == del_mi.strip()].tolist()
                if idx_list:
                    st.session_state.master_df = st.session_state.master_df.drop(idx_list)
                    save_changes_to_cloud(st.session_state.master_df)
                    st.success("החייל נמחק!")
                    time.sleep(1)
                    st.rerun()

    st.divider()
    if st.button("🔄 למחזור דיווח חדש"):
        st.session_state.master_df['נוכח'] = False
        st.session_state.master_df['זמן דיווח'] = ""
        save_changes_to_cloud(st.session_state.master_df)
        active_soldiers = st.session_state.master_df[st.session_state.master_df['פעיל'] == True]
        count = send_push(active_soldiers)
        st.success(f"אופס ונשלחו {count} התראות!")
        time.sleep(2)
        st.rerun()

# --- 4. לוגיקה ראשית ---
df = st.session_state.master_df

if not df.empty:
    active_mask = (df['פעיל'] == True)
    total_present = len(df[active_mask & (df['נוכח'] == True)])
    total_active = len(df[active_mask])
    
    st.progress(total_present / total_active if total_active > 0 else 0, 
                text=f"נוכחים: {total_present}/{total_active}")

    st.divider()

    frames = sorted(df['מסגרת'].unique().tolist())
    selected_frame = st.selectbox("בחר מחלקה:", frames)
    
    if 'show_inactive_view' not in st.session_state:
        st.session_state.show_inactive_view = False
        
    btn_label = "👁️ רשימת פעילים" if st.session_state.show_inactive_view else "👁️ רשימת לא פעילים"
    if st.button(btn_label, use_container_width=True):
        st.session_state.show_inactive_view = not st.session_state.show_inactive_view
        st.rerun()
        
    is_active_view = not st.session_state.show_inactive_view
    frame_mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == is_active_view)
    
    original_display_df = df.loc[frame_mask, ['נוכח', 'פעיל', 'שם מלא', 'מספר אישי', 'מפקד']].copy()
    display_df = original_display_df.copy()
    
    if is_active_view:
        if st.checkbox(f"✅ סמן הכל ({selected_frame})", key=f"all_p_{selected_frame}"):
            display_df['נוכח'] = True
    else:
        if st.checkbox(f"✅ סמן הכל כפעילים ({selected_frame})", key=f"all_a_{selected_frame}"):
            display_df['פעיל'] = True

    editor_key = f"ed_{selected_frame}_{st.session_state.show_inactive_view}"
    edited_df = st.data_editor(
        display_df,
        column_config={
            "נוכח": st.column_config.CheckboxColumn("🟢", default=False, width="small"),
            "פעיל": st.column_config.CheckboxColumn("פעיל", default=True, width="small"),
            "שם מלא": st.column_config.TextColumn("שם"),
        },
        disabled=["שם מלא", "מספר אישי", "מפקד"],
        hide_index=True,
        key=editor_key,
        use_container_width=True
    )

    if not edited_df.equals(original_display_df):
        if st.button("💾 שמור שינויים", use_container_width=True):
            current_time = datetime.now().strftime("%H:%M")
            for _, row in edited_df.iterrows():
                mi = row['מספר אישי']
                idx_list = st.session_state.master_df.index[st.session_state.master_df['מספר אישי'] == mi].tolist()
                if idx_list:
                    idx = idx_list[0]
                    old_present = st.session_state.master_df.at[idx, 'נוכח']
                    st.session_state.master_df.at[idx, 'נוכח'] = row['נוכח']
                    st.session_state.master_df.at[idx, 'פעיל'] = row['פעיל']
                    if row['נוכח'] and not old_present:
                        st.session_state.master_df.at[idx, 'זמן דיווח'] = current_time
            
            save_changes_to_cloud(st.session_state.master_df)
            st.success("הנתונים סונכרנו!")
            time.sleep(0.5)
            st.rerun()
else:
    st.warning("לא נמצאו נתונים.")
