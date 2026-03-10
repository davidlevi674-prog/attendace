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
    
    /* רקע סרגל צד */
    [data-testid="stSidebar"] { background-color: #3b4218 !important; }
    
    /* יישור טקסט */
    div[data-testid="stText"], div[data-testid="stMarkdownContainer"] { text-align: right; direction: rtl; }
    
    /* צבע טקסט כללי ללבן */
    h1, h2, h3, h4, span, label, p { color: white !important; }
    
    /* צבע שחור לטקסט בתוך תיבות טקסט */
    div[data-baseweb="input"] input { color: black !important; }
    div[data-baseweb="select"] span { color: black !important; }
    
    /* עיצוב כפתורים - רקע זהב, טקסט שחור מודגש */
    div.stButton > button { 
        background-color: #D4AF37 !important; 
        border-radius: 10px !important; 
        border: none !important; 
    }
    div.stButton > button p, div.stButton > button span { 
        color: black !important; 
        font-weight: bold !important; 
    }
    
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

def send_push(active_df):
    app_link = "https://attendace-4wq3edrxk6hwohjswi4hjm.streamlit.app/"
    count = 0
    my_bar = st.progress(0, text="שולח התראות...")
    total = len(active_df)
    for index, row in active_df.iterrows():
        mi = str(row['מספר אישי']).strip()
        try:
            requests.post(f"https://ntfy.sh/toto_{mi}", 
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

# --- כפתורי ניהול בסרגל צד ---
with st.sidebar:
    st.header("⚙️ מנהל")
    
    with st.expander("➕ הוספת חייל חדש"):
        n_name = st.text_input("שם מלא:")
        n_mi = st.text_input("מספר אישי:")
        frames_list = sorted(st.session_state.master_df['מסגרת'].unique().tolist()) if not st.session_state.master_df.empty else ["1"]
        n_frame = st.selectbox("מסגרת (מחלקה):", frames_list)
        n_is_comm = st.checkbox("מפקד?")
        
        if st.button("הוסף לרשימה"):
            if n_name and n_mi:
                new_row = pd.DataFrame([{
                    "שם מלא": n_name, "מסגרת": str(n_frame), "מספר אישי": str(n_mi).strip(), 
                    "מפקד": n_is_comm, "נוכח": False, "זמן דיווח": "", "פעיל": True
                }])
                st.session_state.master_df = pd.concat([st.session_state.master_df, new_row], ignore_index=True)
                with st.spinner('מעדכן נתונים...'):
                    save_changes_to_cloud(st.session_state.master_df)
                    st.success("החייל הוסף בהצלחה!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.warning("נא למלא שם ומספר אישי.")

    st.divider()
    
    if st.button("🔄 למחזור דיווח חדש"):
        st.session_state.master_df['נוכח'] = False
        st.session_state.master_df['זמן דיווח'] = ""
        
        with st.spinner("מאפס יום חדש..."):
            save_changes_to_cloud(st.session_state.master_df)
            
            for key in list(st.session_state.keys()):
                if key.startswith("editor_") or key.startswith("select_all_"):
                    del st.session_state[key]
            
            active_soldiers = st.session_state.master_df[st.session_state.master_df['פעיל'] == True]
            count = send_push(active_soldiers)
            st.success(f"נשלחו {count} התראות. מחזור חדש התחיל!")
            time.sleep(2)
            st.rerun()

# --- 4. לוגיקה ראשית ---

col_ref, col_info = st.columns([1, 4])
with col_ref:
    if st.button("🔄 רענן נתונים"):
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
                text=f"סה''כ נוכחים: {total_present} מתוך {total_active} פעילים")

st.divider()

if not df.empty:
    frames = sorted(df['מסגרת'].unique().tolist())
    selected_frame = st.selectbox("בחר מחלקה לצפייה וסימון:", frames)
    
    # --- כפתור חדש לרשימת הלא פעילים ---
    if 'show_inactive_view' not in st.session_state:
        st.session_state.show_inactive_view = False
        
    if st.button("👁️ חזור לרשימת פעילים" if st.session_state.show_inactive_view else "👁️ רשימת לא פעילים"):
        st.session_state.show_inactive_view = not st.session_state.show_inactive_view
        st.rerun()
        
    if st.session_state.show_inactive_view:
        frame_mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == False)
        st.subheader("רשימת חיילים לא פעילים (בחר 'פעיל' ושמור כדי להחזירם)")
    else:
        frame_mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == True)
        
    display_df = df.loc[frame_mask, ['נוכח', 'פעיל', 'שם מלא', 'מספר אישי', 'מפקד']].copy()
    
    select_all_key = f"select_all_{selected_frame}_{st.session_state.show_inactive_view}"
    # מציג את אופציית 'סמן הכל' רק כשאנחנו בטבלת הפעילים
    if not st.session_state.show_inactive_view:
        if st.checkbox(f"✅ סמן את כל מחלקה {selected_frame} כנוכחים", key=select_all_key):
            display_df.loc[display_df['פעיל'] == True, 'נוכח'] = True 
    
    # --- העיצוב ---
    def style_table(row):
        styles = [''] * len(row)
        if not row['פעיל']:
            return ['color: #666666; text-decoration: line-through; background-color: #333333;'] * len(row)
        else:
            for i, col in enumerate(row.index):
                if col == 'נוכח':
                    styles[i] = 'background-color: rgba(40, 167, 69, 0.2);'
            return styles
            
    styled_df = display_df.style.apply(style_table, axis=1)
        
    editor_key = f"editor_{selected_frame}_{st.session_state.show_inactive_view}"
    edited_df = st.data_editor(
        styled_df,
        column_config={
            "נוכח": st.column_config.CheckboxColumn("🟢 נמצא?", default=False),
            "פעיל": st.column_config.CheckboxColumn("פעיל?", default=True),
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
        st.warning("⚠️ ביצעת שינויים. לחץ כאן כדי לשמור בענן:")
        
        if st.button("💾 שמור נתונים", type="primary", use_container_width=True):
            current_time = datetime.now().strftime("%H:%M")
            
            for _, row in edited_df.iterrows():
                mi = row['מספר אישי']
                new_val_active = row['פעיל']
                new_val_present = row['נוכח'] if new_val_active else False
                
                df_indices = st.session_state.master_df.index[st.session_state.master_df['מספר אישי'] == mi].tolist()
                if df_indices:
                    idx = df_indices[0]
                    old_val_present = st.session_state.master_df.at[idx, 'נוכח']
                    
                    st.session_state.master_df.at[idx, 'נוכח'] = new_val_present
                    st.session_state.master_df.at[idx, 'פעיל'] = new_val_active
                    
                    if new_val_present == True and old_val_present == False:
                        st.session_state.master_df.at[idx, 'זמן דיווח'] = current_time
            
            with st.spinner('מעדכן נתונים בענן...'):
                save_changes_to_cloud(st.session_state.master_df)
                
                if select_all_key in st.session_state:
                    del st.session_state[select_all_key]
                if editor_key in st.session_state:
                    del st.session_state[editor_key]
                
                st.success("הנתונים נשמרו בהצלחה!")
                time.sleep(0.5)
                st.rerun()

