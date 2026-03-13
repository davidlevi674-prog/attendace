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

    div.stButton > button { 
        background-color: #D4AF37 !important; 
        border-radius: 10px !important; 
        border: none !important; 
        color: black !important;
        font-weight: bold !important;
        width: 100%;
        height: 3em;
    }
    
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

# --- 2. פונקציות עזר ---
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
    return val_str in ['true', '1', '1.0', 'v', 'yes', 'כן', 't', 'true']

def load_sheet(worksheet_name, ttl=2):
    try:
        df = run_with_retry(lambda: conn.read(worksheet=worksheet_name, ttl=ttl))
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

def generate_shvatzak(missions_df, soldiers_df, leave_df, history_df, start_hour):
    now = datetime.now()
    plan_start = datetime.combine(now.date(), start_hour)
    if plan_start < now: plan_start += timedelta(days=1)
    
    time_slots = [plan_start + timedelta(minutes=30*i) for i in range(48)]
    schedule = []
    
    # --- פנקס היסטוריה וירטואלי (מעקב בזמן אמת) ---
    # מפתח: מספר אישי, ערך: זמן סיום משמרת אחרון (כולל אלו ששובצו הרגע)
    virtual_history = {}
    
    # אתחול הפנקס לפי ההיסטוריה הקיימת בגיליון
    if not history_df.empty:
        for _, row in history_df.iterrows():
            s_id = str(row['מספר אישי']).split('.')[0].strip()
            try:
                # הנחה שזמן התחלה + משך משמרת (אם קיים) או פשוט זמן התחלה
                end_t = pd.to_datetime(row['זמן התחלה'])
                if s_id not in virtual_history or end_t > virtual_history[s_id]:
                    virtual_history[s_id] = end_t
            except: pass

    available_ids = leave_df[leave_df['סטטוס'] == "בבסיס"]['מספר אישי'].astype(str).str.split('.').str[0].tolist()
    
    if not available_ids:
        return pd.DataFrame()

    for slot in time_slots:
        is_night = (slot.hour >= 22 or slot.hour < 5)
        
        # מיון משימות לפי קושי (קודם נשבץ את הקשות כדי שלא ניתקע בלי אנשים)
        sorted_missions = missions_df.sort_values(by='קושי', ascending=False)
        
        for _, mission in sorted_missions.iterrows():
            m_name = mission['משימה']
            m_type = mission['סוג']
            try: m_dur = float(mission['משך משמרת'])
            except: m_dur = 2.0
            
            try: num_req = int(float(mission['סדכ בעמדה']))
            except: num_req = 1
            
            is_change_time = False
            if m_type == "בלוק":
                if slot.hour in [5, 13, 21] and slot.minute == 0: is_change_time = True
            else: 
                total_min = (slot - plan_start).total_seconds() / 60
                if total_min % (m_dur * 60) == 0: is_change_time = True

            if is_change_time:
                chosen_ids = []
                for i in range(num_req):
                    best_soldier = None
                    best_score = -999999
                    
                    for s_id in available_ids:
                        s_id_clean = str(s_id).split('.')[0].strip()
                        
                        # --- חוקי ברזל (Constraints) ---
                        # 1. לא משובץ פעמיים לאותה משימה באותו זמן
                        if s_id_clean in chosen_ids: continue
                        
                        # 2. האם הוא כרגע במשמרת אחרת?
                        last_end = virtual_history.get(s_id_clean, plan_start - timedelta(days=7))
                        if slot < last_end: continue
                        
                        # 3. חוק מנוחה מינימלי: חייב לנוח לפחות אורך משמרת אחת לפני שעולה שוב
                        # (מונע את הלופ של ערן/רועי)
                        if slot < last_end + timedelta(hours=1): # מינימום שעה לכל משימה
                            continue

                        # --- חישוב ניקוד (Scoring) ---
                        score = 0
                        rest_h = (slot - last_end).total_seconds() / 3600
                        score += rest_h * 20 # בונוס מנוחה גבוה
                        
                        # קנס עומס היסטורי (מגיליון ההיסטוריה המקורי)
                        s_hist_real = history_df[history_df['מספר אישי'].astype(str).str.contains(s_id_clean)]
                        if not s_hist_real.empty:
                            recent = s_hist_real[pd.to_datetime(s_hist_real['זמן התחלה']) > (slot - timedelta(days=2))]
                            score -= (recent['קושי'].astype(float).sum()) * 15

                        # הגנת יציאה
                        s_leave_data = leave_df[leave_df['מספר אישי'].astype(str).str.contains(s_id_clean)]
                        if not s_leave_data.empty:
                            s_leave = s_leave_data.iloc[0]
                            l_out = s_leave.get('שעת יציאה חריגה', "")
                            l_str = l_out if l_out else st.session_state.get('g_out', "")
                            if l_str:
                                try:
                                    l_dt = datetime.strptime(l_str, "%d/%m %H:%M").replace(year=now.year)
                                    if 0 < (l_dt - slot).total_seconds() / 3600 < 12 and is_night:
                                        score -= 2000
                                except: pass

                        if score > best_score:
                            best_score = score
                            best_soldier = s_id_clean
                    
                    if best_soldier:
                        # עדכון הפנקס הוירטואלי מיד!
                        virtual_history[best_soldier] = slot + timedelta(hours=m_dur)
                        chosen_ids.append(best_soldier)
                        
                        s_name_match = soldiers_df[soldiers_df['מספר אישי'].astype(str).str.contains(best_soldier)]['שם מלא']
                        s_name = s_name_match.iloc[0] if not s_name_match.empty else f"חייל {best_soldier}"
                        
                        schedule.append({
                            "שעה": slot.strftime("%H:%M"),
                            "משימה": m_name,
                            "חייל": s_name,
                            "מ.א": best_soldier,
                            "עד שעה": (slot + timedelta(hours=m_dur)).strftime("%H:%M")
                        })
    
    return pd.DataFrame(schedule)

# --- 3. ניווט ותצוגה ---
if "current_page" not in st.session_state:
    st.session_state.current_page = "home"

if st.session_state.current_page == "home":
    col_l1, col_l2, col_l3 = st.columns([1,1,1])
    with col_l2:
        if os.path.exists("logo.png"): st.image("logo.png", width=120)
        else: st.markdown("<h2 style='text-align: center;'>🇮🇱</h2>", unsafe_allow_html=True)
    st.markdown("<h1 style='text-align: center;'>תיק פלוגה דיגיטלי - גרביל</h1>", unsafe_allow_html=True)
    st.markdown("<div class='home-btn'>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🟢 ירוק בעיניים"): st.session_state.current_page = "attendance"; st.rerun()
    with c2:
        if st.button("🔦 ציוד ואמל''ח"): st.session_state.current_page = "equipment"; st.rerun()
    with c3:
        if st.button("📋 מחולל שבצ''ק"): st.session_state.current_page = "shvatzak"; st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

# --- דף שבצ"ק ---
elif st.session_state.current_page == "shvatzak":
    if st.button("🏠 חזור למסך הראשי"):
        st.session_state.current_page = "home"; st.rerun()
    
    st.title("📋 מחולל שבצ''ק פלוגתי")
    t_gen, t_cfg, t_lv = st.tabs(["🚀 חולל שיבוץ", "⚙️ הגדרות", "🏠 יציאות"])
    
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
            ed_l = st.data_editor(l_display.fillna(""), column_config={"יוצא בסבב": st.column_config.CheckboxColumn("יוצא?")}, disabled=["שם מלא", "מספר אישי"], hide_index=True, use_container_width=True)
            if st.button("💾 שמור יציאות"):
                to_save = ed_l.drop(columns=['שם מלא'])
                to_save['יוצא בסבב'] = to_save['יוצא בסבב'].astype(str).str.upper()
                run_with_retry(lambda: conn.update(worksheet="Leave_Tracker", data=to_save))
                st.success("נשמר!")

    with t_gen:
        st.subheader("ייצור שבצ''ק ל-24 שעות")
        start_t = st.time_input("שעת התחלת שבצ''ק:", dt_time(8, 0))
        
        if st.button("🚀 חולל הצעת שיבוץ אוטומטית"):
            with st.spinner("מבצע אופטימיזציה של כוחות..."):
                m_df = load_sheet("Missions_Config")
                l_df = load_sheet("Leave_Tracker")
                h_df = load_sheet("Shvatzak_History")
                s_df = load_sheet("Sheet1")
                
                # הגנות נתונים
                l_df['סטטוס'] = l_df['סטטוס'].fillna("בבסיס")
                
                result = generate_shvatzak(m_df, s_df, l_df, h_df, start_t)
                
                if not result.empty:
                    st.success("השבצ''ק מוכן!")
                    # הצגת התוצאה בטבלה מעוצבת ורחבה
                    st.dataframe(result, use_container_width=True, hide_index=True)
                    
                    st.download_button("📥 הורד שבצ''ק כקובץ", result.to_csv(index=False).encode('utf-8-sig'), "shvatzak.csv", "text/csv")
                else:
                    st.error("לא נמצאו חיילים פנויים בבסיס המקיימים את חוקי המנוחה.")

# (שאר הדפים - attendance ו-equipment נשארים אותו דבר)
elif st.session_state.current_page == "attendance":
    if st.button("🏠 חזור"): st.session_state.current_page = "home"; st.rerun()
    st.write("בדיקת נוכחות פעילה...")
    # ... הקוד המקורי שלך ...

elif st.session_state.current_page == "equipment":
    if st.button("🏠 חזור"): st.session_state.current_page = "home"; st.rerun()
    st.write("ניהול ציוד פעיל...")
    # ... הקוד המקורי שלך ...

