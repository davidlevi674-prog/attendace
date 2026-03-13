import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
from streamlit_gsheets import GSheetsConnection
import requests
import time
import os

# --- 1. הגדרות ועיצוב ---
st.set_page_config(page_title="ניהול פלוגת גרביל", layout="wide", page_icon="logo.png")

st.markdown("""
    <style>
    .stApp { background-color: #4B5320; color: white; direction: rtl; text-align: right; }
    div[data-testid="stText"], div[data-testid="stMarkdownContainer"] { text-align: right; direction: rtl; }
    h1, h2, h3, h4, span, label, p { color: white !important; }
    div[data-baseweb="input"] input { color: black !important; }
    div[data-baseweb="select"] span { color: black !important; }
    
    [data-testid="collapsedControl"] { display: none !important; }
    [data-testid="stSidebar"] { display: none !important; }
    
    .main .block-container { padding-top: 1.5rem !important; }

    /* עיצוב כפתורים זהב */
    div.stButton > button { 
        background-color: #D4AF37 !important; 
        border-radius: 10px !important; 
        border: none !important; 
        color: black !important;
        font-weight: bold !important;
        width: 100%;
        height: 3em;
    }
    
    /* כפתורי מסך בית - גדולים */
    .home-btn > div > button {
        height: 6em !important;
        font-size: 1.2rem !important;
    }
    
    .stButton button[kind="primary"] {
        background-color: #ff4b4b !important;
        color: white !important;
    }
    
    div[data-testid="stDataEditor"] { direction: rtl; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. חיבור ופונקציות עזר ---
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
    if isinstance(val, bool): return val
    if pd.isna(val): return False
    val_str = str(val).strip().lower()
    return val_str in ['true', '1', '1.0', 'v', 'yes', 'כן', 't', 'TRUE']

def load_sheet(worksheet_name, ttl=2):
    try:
        df = run_with_retry(lambda: conn.read(worksheet=worksheet_name, ttl=ttl))
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

# --- מנוע השבצ"ק (הלוגיקה המתמטית) ---
def generate_shvatzak(missions_df, soldiers_df, leave_df, history_df, start_hour):
    now = datetime.now()
    plan_start = datetime.combine(now.date(), start_hour)
    if plan_start < now: plan_start += timedelta(days=1)
    
    time_slots = [plan_start + timedelta(minutes=30*i) for i in range(48)]
    schedule = []
    
    available_soldiers = leave_df[leave_df['סטטוס'] == "בבסיס"]['מספר אישי'].tolist()
    
    if not available_soldiers:
        return pd.DataFrame()

    for slot in time_slots:
        is_night = (slot.hour >= 22 or slot.hour < 5)
        
        for _, mission in missions_df.iterrows():
            is_change_time = False
            if mission['סוג'] == "בלוק":
                if slot.hour in [5, 13, 21] and slot.minute == 0: is_change_time = True
            else: 
                try:
                    shift_dur = float(mission['משך משמרת'])
                    total_min = (slot - plan_start).total_seconds() / 60
                    if total_min % (shift_dur * 60) == 0: is_change_time = True
                except: is_change_time = False

            if is_change_time:
                best_soldier = None
                best_score = -999999
                
                for s_id in available_soldiers:
                    score = 0
                    s_hist = history_df[history_df['מספר אישי'] == str(s_id)]
                    
                    if not s_hist.empty:
                        last_end = pd.to_datetime(s_hist['זמן התחלה']).max()
                        rest_hours = (slot - last_end).total_seconds() / 3600
                        score += rest_hours * 10 
                    else:
                        score += 100 
                    
                    if not s_hist.empty:
                        recent_load = s_hist[pd.to_datetime(s_hist['זמן התחלה']) > (slot - timedelta(days=2))]
                        score -= (recent_load['קושי'].astype(float).sum()) * 5
                    
                    # בדיקת הגנת יציאה
                    s_leave_data = leave_df[leave_df['מספר אישי'] == s_id]
                    if not s_leave_data.empty:
                        s_leave = s_leave_data.iloc[0]
                        leave_time_str = s_leave['שעת יציאה חריגה'] if s_leave['שעת יציאה חריגה'] else st.session_state.get('g_out', "")
                        if leave_time_str:
                            try:
                                leave_dt = datetime.strptime(leave_time_str, "%d/%m %H:%M").replace(year=now.year)
                                if 0 < (leave_dt - slot).total_seconds() / 3600 < 12 and is_night:
                                    score -= 500
                            except: pass

                    if score > best_score:
                        best_score = score
                        best_soldier = s_id
                
                if best_soldier:
                    s_name_match = soldiers_df[soldiers_df['מספר אישי'] == best_soldier]['שם מלא']
                    s_name = s_name_match.iloc[0] if not s_name_match.empty else f"חייל {best_soldier}"
                    schedule.append({
                        "זמן": slot.strftime("%H:%M"),
                        "משימה": mission['משימה'],
                        "חייל": s_name,
                        "מספר אישי": best_soldier
                    })
    
    return pd.DataFrame(schedule)

# --- 3. ניהול ניווט (Navigation) ---
if "current_page" not in st.session_state:
    st.session_state.current_page = "home"

# --- מסך הבית ---
if st.session_state.current_page == "home":
    col_l1, col_l2, col_l3 = st.columns([1,1,1])
    with col_l2:
        if os.path.exists("logo.png"): st.image("logo.png", width=120)
        else: st.markdown("<h2 style='text-align: center;'>🇮🇱</h2>", unsafe_allow_html=True)
    
    st.markdown("<h1 style='text-align: center;'>תיק פלוגה דיגיטלי - גרביל</h1>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    st.markdown("<div class='home-btn'>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🟢 ירוק בעיניים\n(נוכחות)"):
            st.session_state.current_page = "attendance"; st.rerun()
    with c2:
        if st.button("🔦 ציוד ואמל''ח\n(החתמות)"):
            st.session_state.current_page = "equipment"; st.rerun()
    with c3:
        if st.button("📋 מחולל שבצ''ק\n(שיבוץ כוחות)"):
            st.session_state.current_page = "shvatzak"; st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# --- דף בדיקת נוכחות ---
elif st.session_state.current_page == "attendance":
    if st.button("🏠 חזור למסך הראשי"):
        st.session_state.current_page = "home"; st.rerun()
    
    st.title("בדיקת נוכחות גרביל")

    def load_attendance_data(force_fresh=False):
        ttl = 0 if force_fresh else 2
        df = load_sheet("Sheet1", ttl=ttl)
        if df.empty: return df
        if 'מסגרת' in df.columns: 
            df['מסגרת'] = df['מסגרת'].fillna("ללא מחלקה").astype(str)
        if 'מספר אישי' in df.columns: 
            df['מספר אישי'] = df['מספר אישי'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
        for col in ['נוכח', 'זמן דיווח', 'פעיל', 'מפקד']:
            if col not in df.columns: df[col] = "" 
        df['נוכח'] = df['נוכח'].apply(parse_bool)
        df['פעיל'] = df['פעיל'].apply(parse_bool)
        return df

    df = load_attendance_data()
    if not df.empty:
        active_mask = (df['פעיל'] == True)
        total_present = len(df[active_mask & (df['נוכח'] == True)])
        total_active = len(df[active_mask])
        st.progress(total_present/total_active if total_active > 0 else 0, text=f"נוכחים: {total_present}/{total_active}")
        
        frames = sorted(df['מסגרת'].unique().tolist())
        selected_frame = st.selectbox("בחר מחלקה:", frames)
        
        frame_mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == True)
        display_df = df.loc[frame_mask, ['נוכח', 'שם מלא', 'מספר אישי']].copy()
        
        edited_df = st.data_editor(display_df, column_config={"נוכח": st.column_config.CheckboxColumn("🟢")}, disabled=["שם מלא", "מספר אישי"], hide_index=True, use_container_width=True)

        if st.button("💾 שמור דיווח"):
            latest_df = load_attendance_data(force_fresh=True)
            for _, row in edited_df.iterrows():
                mi = row['מספר אישי']
                idx = latest_df.index[latest_df['מספר אישי'] == mi].tolist()[0]
                latest_df.at[idx, 'נוכח'] = row['נוכח']
            run_with_retry(lambda: conn.update(worksheet="Sheet1", data=latest_df))
            st.success("נשמר!"); time.sleep(1); st.rerun()

# --- דף ציוד ואמל"ח ---
elif st.session_state.current_page == "equipment":
    if st.button("🏠 חזור למסך הראשי"):
        st.session_state.current_page = "home"; st.rerun()
    st.title("🔦 ניהול ציוד ואמל''ח")
    eq_df = load_sheet("Equipment")
    if not eq_df.empty:
        st.data_editor(eq_df, use_container_width=True, hide_index=True)

# --- דף מחולל שבצ"ק ---
elif st.session_state.current_page == "shvatzak":
    if st.button("🏠 חזור למסך הראשי"):
        st.session_state.current_page = "home"; st.rerun()
    st.title("📋 מחולל שבצ''ק פלוגתי")
    
    t_gen, t_cfg, t_lv = st.tabs(["🚀 חולל שיבוץ", "⚙️ הגדרות משימות", "🏠 ניהול יציאות"])
    
    with t_cfg:
        m_df = load_sheet("Missions_Config")
        if not m_df.empty:
            ed_m = st.data_editor(m_df, hide_index=True, use_container_width=True)
            if st.button("💾 שמור משימות"):
                run_with_retry(lambda: conn.update(worksheet="Missions_Config", data=ed_m))
                st.success("עודכן!")

    with t_lv:
        l_raw = load_sheet("Leave_Tracker")
        s_raw = load_sheet("Sheet1")
        if not l_raw.empty:
            l_display = l_raw.merge(s_raw[['מספר אישי', 'שם מלא']], on='מספר אישי', how='left')
            l_display['יוצא בסבב'] = l_display['יוצא בסבב'].apply(parse_bool).fillna(False).astype(bool)
            l_display = l_display.fillna("")
            
            ed_l = st.data_editor(l_display, column_config={"יוצא בסבב": st.column_config.CheckboxColumn("יוצא?")}, disabled=["שם מלא", "מספר אישי"], hide_index=True, use_container_width=True)
            
            if st.button("💾 שמור יציאות"):
                to_save = ed_l.drop(columns=['שם מלא'])
                to_save['יוצא בסבב'] = to_save['יוצא בסבב'].astype(str).str.upper()
                run_with_retry(lambda: conn.update(worksheet="Leave_Tracker", data=to_save))
                st.success("נשמר!")

    with t_gen:
        st.subheader("ייצור שבצ''ק")
        start_t = st.time_input("שעת התחלה:", dt_time(8, 0))
        if st.button("🚀 חולל הצעת שיבוץ אוטומטית"):
            with st.spinner("מחשב..."):
                m_df = load_sheet("Missions_Config")
                l_df = load_sheet("Leave_Tracker")
                h_df = load_sheet("Shvatzak_History")
                s_df = load_sheet("Sheet1")
                
                # ניקוי לפורמט אחיד
                l_df['סטטוס'] = l_df['סטטוס'].fillna("בבסיס")
                
                result_df = generate_shvatzak(m_df, s_df, l_df, h_df, start_t)
                if not result_df.empty:
                    st.success("השבצ''ק חולל!")
                    st.dataframe(result_df, use_container_width=True)
                else:
                    st.error("לא נמצאו חיילים זמינים או משימות.")
