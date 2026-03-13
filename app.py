import streamlit as st
import pandas as pd
from datetime import datetime
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
    return val_str in ['true', '1', '1.0', 'v', 'yes', 'כן', 't']

# פונקציית טעינה כללית לגיליונות שונים
def load_sheet(worksheet_name, ttl=2):
    try:
        df = run_with_retry(lambda: conn.read(worksheet=worksheet_name, ttl=ttl))
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except:
        return pd.DataFrame()
def generate_shvatzak(missions_df, soldiers_df, leave_df, history_df, start_hour):
    # --- הכנת הנתונים ---
    # הפיכת זמנים לאובייקטים של פייתון
    now = datetime.now()
    plan_start = datetime.combine(now.date(), start_hour)
    if plan_start < now: plan_start += timedelta(days=1)
    
    # טבלת תוצאה: 24 שעות בחלוקה לחצי שעה (48 משבצות)
    time_slots = [plan_start + timedelta(minutes=30*i) for i in range(48)]
    schedule = []

    # רשימת החיילים שבאמת בבסיס (כולל סינון יציאות)
    available_soldiers = leave_df[leave_df['סטטוס'] == "בבסיס"]['מספר אישי'].tolist()
    
    # --- לוגיקת השיבוץ ---
    for slot in time_slots:
        is_night = (slot.hour >= 22 or slot.hour < 5)
        
        for _, mission in missions_df.iterrows():
            # בדיקה אם זו שעת החלפה למשימה
            is_change_time = False
            if mission['סוג'] == "בלוק":
                # חילוף רק ב-05:00, 13:00, 21:00
                if slot.hour in [5, 13, 21] and slot.minute == 0: is_change_time = True
            else: # רצף
                # חילוף לפי 'משך משמרת'
                shift_duration = float(mission['משך משמרת'])
                # חישוב פשוט של מודולו זמן
                total_minutes = (slot - plan_start).total_seconds() / 60
                if total_minutes % (shift_duration * 60) == 0: is_change_time = True

            if is_change_time:
                # מציאת החייל הכי מתאים (Scoring)
                best_soldier = None
                best_score = -999999
                
                for s_id in available_soldiers:
                    score = 0
                    
                    # 1. בדיקת מנוחה (מההיסטוריה)
                    s_hist = history_df[history_df['מספר אישי'] == s_id]
                    if not s_hist.empty:
                        last_end = pd.to_datetime(s_hist['זמן התחלה']).max()
                        rest_hours = (slot - last_end).total_seconds() / 3600
                        score += rest_hours * 10 # 10 נקודות על כל שעת מנוחה
                    else:
                        score += 100 # בונוס למי שלא עשה כלום שבוע
                    
                    # 2. קנס קושי (48 שעות אחרונות)
                    recent_load = s_hist[pd.to_datetime(s_hist['זמן התחלה']) > (slot - timedelta(days=2))]
                    load_sum = (recent_load['קושי'].astype(float)).sum()
                    score -= load_sum * 5
                    
                    # 3. הגנת יציאה
                    s_leave = leave_df[leave_df['מספר אישי'] == s_id].iloc[0]
                    leave_time_str = s_leave['שעת יציאה חריגה'] if s_leave['שעת יציאה חריגה'] else st.session_state.get('g_out', "")
                    if leave_time_str:
                        try:
                            # הערכת זמן יציאה (פשטני לצורך הקוד)
                            leave_dt = datetime.strptime(leave_time_str, "%d/%m %H:%M").replace(year=now.year)
                            time_to_leave = (leave_dt - slot).total_seconds() / 3600
                            if 0 < time_to_leave < 12 and is_night:
                                score -= 500 # קנס כבד - לא עולה לילה לפני יציאה
                        except: pass

                    # 4. בדיקת 02:00 בלילה
                    if slot.hour == 2:
                        # מי שכבר עשה לילה השבוע - יקבל קנס
                        night_shifts = s_hist[s_hist['משקל לילה'].astype(float) > 0]
                        score -= len(night_shifts) * 20
                    
                    if score > best_score:
                        best_score = score
                        best_soldier = s_id
                
                if best_soldier:
                    # משיכת שם החייל
                    s_name = soldiers_df[soldiers_df['מספר אישי'] == best_soldier]['שם מלא'].iloc[0]
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

# --- דף בדיקת נוכחות (ירוק בעיניים) ---
elif st.session_state.current_page == "attendance":
    if st.button("🏠 חזור למסך הראשי"):
        st.session_state.current_page = "home"; st.rerun()
    
    st.title("בדיקת נוכחות גרביל")

    def load_attendance_data(force_fresh=False):
        ttl = 0 if force_fresh else 2
        df = load_sheet("Sheet1", ttl=ttl)
        if df.empty: return df
        
        def clean_frame(val):
            if pd.isna(val): return "ללא מחלקה"
            try: return str(int(float(val))) if float(val).is_integer() else str(val)
            except: return str(val)
            
        if 'מסגרת' in df.columns: df['מסגרת'] = df['מסגרת'].apply(clean_frame)
        if 'מספר אישי' in df.columns: 
            df['מספר אישי'] = df['מספר אישי'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            
        for col in ['נוכח', 'זמן דיווח', 'פעיל', 'מפקד']:
            if col not in df.columns: df[col] = "" 
            
        df['נוכח'] = df['נוכח'].apply(parse_bool)
        df['פעיל'] = df['פעיל'].apply(parse_bool)
        return df

    def send_push(active_df):
        app_link = "https://attendace-4wq3edrxk6hwohjswi4hjm.streamlit.app/"
        count = 0
        total = len(active_df)
        my_bar = st.progress(0, text="שולח התראות...")
        for index, row in active_df.iterrows():
            mi = "".join(filter(str.isdigit, str(row['מספר אישי'])))
            if not mi: continue
            try:
                requests.post(f"https://ntfy.sh/toto_{mi}", 
                    data="Attendance Check is open".encode('utf-8'),
                    headers={"Title": "נוכחות גרביל", "Message": "דיווח ירוק החל!", "Click": app_link}, timeout=5)
                count += 1
                my_bar.progress(count / total)
            except: pass
        time.sleep(1); my_bar.empty()
        return count

    col_ref, col_info = st.columns([1, 4])
    with col_ref:
        if st.button("🔄 רענן נתונים"):
            st.cache_data.clear(); st.rerun()

    df = load_attendance_data()
    if not df.empty:
        active_mask = (df['פעיל'] == True)
        total_present = len(df[active_mask & (df['נוכח'] == True)])
        total_active = len(df[active_mask])
        with col_info:
            st.progress(total_present/total_active if total_active > 0 else 0, text=f"נוכחים: {total_present}/{total_active}")

        st.divider()
        frames = sorted(df['מסגרת'].unique().tolist())
        selected_frame = st.selectbox("בחר מחלקה:", frames)
        
        if 'show_inactive_view' not in st.session_state: st.session_state.show_inactive_view = False
        if st.button("👁️ " + ("פעילים" if st.session_state.show_inactive_view else "לא פעילים")):
            st.session_state.show_inactive_view = not st.session_state.show_inactive_view; st.rerun()
            
        is_active_view = not st.session_state.show_inactive_view
        frame_mask = (df['מסגרת'] == selected_frame) & (df['פעיל'] == is_active_view)
        original_display_df = df.loc[frame_mask, ['נוכח', 'פעיל', 'שם מלא', 'מספר אישי', 'מפקד']].copy()
        display_df = original_display_df.copy()
        
        if is_active_view:
            if st.checkbox(f"✅ סמן הכל כנוכחים ({selected_frame})"): display_df['נוכח'] = True
        else:
            if st.checkbox(f"✅ סמן הכל כפעילים ({selected_frame})"): display_df['פעיל'] = True

        editor_key = f"ed_{selected_frame}_{st.session_state.show_inactive_view}"
        edited_df = st.data_editor(display_df, column_config={"נוכח": st.column_config.CheckboxColumn("🟢"), "פעיל": st.column_config.CheckboxColumn("פעיל?")}, disabled=["שם מלא", "מספר אישי", "מפקד"], hide_index=True, key=editor_key, use_container_width=True)

        if not edited_df.equals(original_display_df):
            if st.button("💾 שמור דיווח", use_container_width=True):
                with st.spinner("סנכרון..."):
                    curr_time = datetime.now().strftime("%H:%M")
                    latest_df = load_attendance_data(force_fresh=True)
                    updated = False
                    for _, row in edited_df.iterrows():
                        mi = row['מספר אישי']
                        orig = original_display_df[original_display_df['מספר אישי'] == mi].iloc[0]
                        if row['נוכח'] != orig['נוכח'] or row['פעיל'] != orig['פעיל']:
                            idx = latest_df.index[latest_df['מספר אישי'] == mi].tolist()[0]
                            old_pres = latest_df.at[idx, 'נוכח']
                            latest_df.at[idx, 'נוכח'], latest_df.at[idx, 'פעיל'] = row['נוכח'], row['פעיל']
                            if row['נוכח'] and not old_pres: latest_df.at[idx, 'זמן דיווח'] = curr_time
                            updated = True
                    if updated:
                        run_with_retry(lambda: conn.update(worksheet="Sheet1", data=latest_df))
                        st.cache_data.clear(); st.success("נשמר!")
                        if editor_key in st.session_state: del st.session_state[editor_key]
                        time.sleep(1); st.rerun()

        with st.expander("⚙️ אזור מפקדים"):
            col_a, col_b = st.columns(2)
            n_name = col_a.text_input("שם חייל חדש:")
            n_mi = col_b.text_input("מ.א חייל חדש:")
            if st.button("➕ הוסף חייל"):
                if n_name and n_mi:
                    ld = load_attendance_data(force_fresh=True)
                    new = pd.DataFrame([{"שם מלא": n_name, "מספר אישי": n_mi, "מסגרת": selected_frame, "פעיל": True, "נוכח": False, "מפקד": False}])
                    run_with_retry(lambda: conn.update(worksheet="Sheet1", data=pd.concat([ld, new])))
                    st.success("נוסף!"); st.rerun()
            st.divider()
            if st.button("🚨 פתח דיווח ירוק (אפס ושלח Push)"):
                ld = load_attendance_data(force_fresh=True)
                ld['נוכח'] = False
                run_with_retry(lambda: conn.update(worksheet="Sheet1", data=ld))
                count = send_push(ld[ld['פעיל'] == True])
                st.success(f"נשלחו {count} התראות!"); time.sleep(2); st.rerun()

# --- דף ציוד ואמל"ח ---
elif st.session_state.current_page == "equipment":
    if st.button("🏠 חזור למסך הראשי"):
        st.session_state.current_page = "home"; st.rerun()
    st.title("🔦 ניהול ציוד ואמל''ח")
    
    eq_df = load_sheet("Equipment")
    soldiers_df = load_sheet("Sheet1")
    
    if not eq_df.empty:
        st.subheader("📝 חתימה על פריט")
        available = eq_df[eq_df['סטטוס'].isin(['פנוי', '', None])]
        if not available.empty:
            item_list = available['סוג ציוד'] + " (" + available['מספר צ'].astype(str) + ")"
            sel_item = st.selectbox("בחר פריט:", item_list)
            u_id = st.text_input("הזן מספר אישי לחתימה:")
            if st.button("חתום על ציוד"):
                match = soldiers_df[soldiers_df['מספר אישי'] == u_id.strip()]
                if not match.empty:
                    tsadi = sel_item.split("(")[1].replace(")", "")
                    idx = eq_df.index[eq_df['מספר צ'].astype(str) == tsadi].tolist()[0]
                    eq_df.at[idx, 'סטטוס'], eq_df.at[idx, 'מספר אישי חותם'] = 'חתום', u_id
                    eq_df.at[idx, 'זמן חתימה'] = datetime.now().strftime("%d/%m %H:%M")
                    run_with_retry(lambda: conn.update(worksheet="Equipment", data=eq_df))
                    st.success(f"נחתם על ידי {match['שם מלא'].iloc[0]}!"); time.sleep(1); st.rerun()
        
        st.divider()
        st.subheader("🔍 ציוד בחוץ")
        signed = eq_df[eq_df['סטטוס'] == 'חתום']
        if not signed.empty:
            for _, row in signed.iterrows():
                with st.expander(f"📦 {row['סוג ציוד']} ({row['מספר צ']}) - חתום ע''י {row['מספר אישי חותם']}"):
                    if st.button(f"החזר פריט {row['מספר צ']}", type="primary"):
                        idx = eq_df.index[eq_df['מספר צ'] == row['מספר צ']].tolist()[0]
                        eq_df.at[idx, 'סטטוס'], eq_df.at[idx, 'מספר אישי חותם'], eq_df.at[idx, 'זמן חתימה'] = 'פנוי', '', ''
                        run_with_retry(lambda: conn.update(worksheet="Equipment", data=eq_df))
                        st.success("הוחזר!"); time.sleep(1); st.rerun()

# --- דף מחולל שבצ"ק מעודכן (מתוקן משגיאות סוג נתונים) ---
elif st.session_state.current_page == "shvatzak":
    if st.button("🏠 חזור למסך הראשי"):
        st.session_state.current_page = "home"; st.rerun()
    st.title("📋 מחולל שבצ''ק פלוגתי")
    
    t_gen, t_cfg, t_lv = st.tabs(["🚀 חולל שיבוץ", "⚙️ הגדרות משימות", "🏠 ניהול יציאות"])
    
    with t_cfg:
        m_df = load_sheet("Missions_Config")
        if not m_df.empty:
            st.subheader("הגדרת משימות")
            ed_m = st.data_editor(m_df, hide_index=True, use_container_width=True)
            if st.button("💾 שמור הגדרות משימות"):
                run_with_retry(lambda: conn.update(worksheet="Missions_Config", data=ed_m))
                st.success("הגדרות עודכנו!")

    with t_lv:
        st.subheader("ניהול סבב יציאות פלוגתי")
        
        # 1. הגדרת זמני סבב גלובליים
        with st.container(border=True):
            st.markdown("##### ⏱️ זמני סבב גלובליים (לכל מי שמסומן ב-V)")
            c_dt = datetime.now().strftime("%d/%m")
            col_g1, col_g2 = st.columns(2)
            global_out = col_g1.text_input("שעת יציאה פלוגתית:", value=st.session_state.get('g_out', f"{c_dt} 12:00"))
            global_in = col_g2.text_input("שעת חזרה פלוגתית:", value=st.session_state.get('g_in', f"{c_dt} 12:00"))
            st.session_state['g_out'] = global_out
            st.session_state['g_in'] = global_in

        # 2. טבלת ניהול חריגים
        l_raw = load_sheet("Leave_Tracker")
        s_raw = load_sheet("Sheet1")
        
        if not l_raw.empty:
            # מיזוג שמות
            l_display = l_raw.merge(s_raw[['מספר אישי', 'שם מלא']], on='מספר אישי', how='left')
            
            # --- תיקון השגיאה: אתחול והמרת סוגי נתונים ---
            # וודוא עמודות קיימות ומילוי ערכים ריקים בערכי ברירת מחדל נכונים לסוג הטור
            if 'יוצא בסבב' not in l_display.columns: 
                l_display['יוצא בסבב'] = False
            else:
                l_display['יוצא בסבב'] = l_display['יוצא בסבב'].apply(parse_bool).fillna(False).astype(bool)
            
            if 'שעת יציאה חריגה' not in l_display.columns: l_display['שעת יציאה חריגה'] = ""
            if 'שעת חזרה חריגה' not in l_display.columns: l_display['שעת חזרה חריגה'] = ""
            if 'סטטוס' not in l_display.columns: l_display['סטטוס'] = "בבסיס"
            
            # ניקוי NaN כללי לטקסט
            l_display = l_display.fillna("")
            
            st.markdown("##### רשימת חיילים וחריגים")
            ed_l = st.data_editor(
                l_display, 
                column_config={
                    "יוצא בסבב": st.column_config.CheckboxColumn("יוצא?"),
                    "שעת יציאה חריגה": st.column_config.TextColumn("יציאה חריגה"),
                    "שעת חזרה חריגה": st.column_config.TextColumn("חזרה חריגה"),
                    "סטטוס": st.column_config.SelectboxColumn("סטטוס נוכחי", options=["בבסיס", "בבית"])
                },
                disabled=["שם מלא", "מספר אישי"],
                hide_index=True, 
                use_container_width=True
            )
            
            if st.button("💾 שמור נתוני יציאה וחריגים"):
                # הסרת עמודת ה'שם מלא' שנוספה רק לצורך תצוגה
                cols_to_save = [c for c in ed_l.columns if c != 'שם מלא']
                to_save = ed_l[cols_to_save].copy()
                
                # המרה חזרה לטקסט עבור גוגל שיטס
                to_save['יוצא בסבב'] = to_save['יוצא בסבב'].astype(str).str.upper()
                
                run_with_retry(lambda: conn.update(worksheet="Leave_Tracker", data=to_save))
                st.success("הנתונים נשמרו בבסיס הנתונים")

  with t_gen:
        st.subheader("ייצור שבצ''ק")
        if st.button("🚀 חולל הצעת שיבוץ אוטומטית"):
            with st.spinner("המנוע מחשב 'צדק פלוגתי'..."):
                # טעינת נתונים
                m_df = load_sheet("Missions_Config")
                l_df = load_sheet("Leave_Tracker")
                h_df = load_sheet("Shvatzak_History")
                s_df = load_sheet("Sheet1")
                
                # הרצת המנוע
                result_df = generate_shvatzak(m_df, s_df, l_df, h_df, start_time)
                
                if not result_df.empty:
                    st.success("השבצ''ק חולל!")
                    st.table(result_df) # הצגת הטבלה
                    
                    if st.button("💾 אשר והפץ היסטוריה"):
                        # כאן נוסיף פקודה שכותבת ל-Shvatzak_History כדי שהמערכת תזכור למחר
                        st.info("השבצ''ק נשמר בהיסטוריה השבועית.")
                else:
                    st.error("לא ניתן היה לחולל שבצ''ק. וודא שיש חיילים בבסיס ומשימות מוגדרות.")
