import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker", page_icon="🌙", layout="wide")
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6; 
        padding: 20px; 
        border-radius: 10px; 
        margin-bottom: 20px; 
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .stAlert {margin-top: 10px;}
    .urgent-box {
        border: 2px solid #ff4b4b;
        background-color: #ffe6e6;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

API_URL = "https://aysqjcborxgdnivlisxl.supabase.co/functions/v1/thaw-schedule"

# --- Helper Function: แปลงเวลาและคำนวณ Countdown ---
def process_claim_time(iso_str, now_thai):
    try:
        # 1. แปลง string จาก API (UTC) ให้เป็น datetime
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        
        # 2. แปลงเป็นเวลาไทย (UTC+7)
        dt_thai = dt_utc + timedelta(hours=7)
        
        # 3. คำนวณเวลาที่เหลือ
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        # 4. สร้างข้อความนับถอยหลัง
        if total_seconds <= 0:
            countdown_str = "✅ เคลมได้เลย"
            sort_val = -1
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            
            # จัด format สวยๆ
            parts = []
            if days > 0: parts.append(f"{days}วัน")
            if hours > 0: parts.append(f"{hours}ชม.")
            if days == 0 and minutes > 0: parts.append(f"{minutes}น.") 
            
            countdown_str = " ".join(parts) if parts else "เร็วๆ นี้"
            sort_val = total_seconds

        # คืนค่ากลับไปใช้
        return {
            "thai_date_str": dt_thai.strftime('%Y-%m-%d %H:%M'), 
            "countdown": countdown_str,
            "sort_val": sort_val,
            "is_urgent": 0 <= days <= 7 if total_seconds > 0 else False
        }
    except:
        return {"thai_date_str": iso_str, "countdown": "-", "sort_val": 999999999, "is_urgent": False}

# --- 2. ฟังก์ชันโหลดข้อมูล ---
async def fetch_data(session, wallet_name, address):
    try:
        async with session.get(API_URL, params={"address": address}) as response:
            if response.status == 200:
                data = await response.json()
                return {"wallet": wallet_name, "address": address, "data": data, "status": "ok"}
            return {"wallet": wallet_name, "address": address, "status": "error"}
    except:
        return {"wallet": wallet_name, "address": address, "status": "fail"}

async def process_all_wallets(df):
    results = []
    sem = asyncio.Semaphore(50) 
    
    async def get_with_limit(session, row):
        async with sem:
            return await fetch_data(session, row['Wallet_Name'], row['Address'])

    async with aiohttp.ClientSession() as session:
        tasks = [get_with_limit(session, row) for index, row in df.iterrows()]
        progress_text = st.empty()
        bar = st.progress(0)
        total = len(tasks)
        completed = 0
        
        for task in asyncio.as_completed(tasks):
            result = await task
            results.append(result)
            completed += 1
            if completed % 10 == 0 or completed == total:
                bar.progress(completed / total)
                progress_text.text(f"⏳ กำลังตรวจสอบ... {completed}/{total}")
            
        progress_text.empty()
        bar.empty()
            
    return results

# --- 3. ส่วนแสดงผล ---
st.title("🌙 NIGHT Vesting Dashboard")

df_input = None
should_run = False
source_type = ""

# --- Logic การเลือกไฟล์ ---
if os.path.exists('active_wallets.csv'):
    st.success("⚡ พบไฟล์ active_wallets.csv -> เริ่มสแกนอัตโนมัติ!")
    df_input = pd.read_csv('active_wallets.csv')
    should_run = True
    source_type = "active"
elif os.path.exists('wallets.xlsx'):
    st.info("📂 พบไฟล์ wallets.xlsx -> กดปุ่มเพื่อเริ่มสแกน")
    df_input = pd.read_excel('wallets.xlsx')
    should_run = False
    source_type = "full"
else:
    uploaded_file = st.file_uploader("📂 ไม่พบไฟล์ กรุณาอัปโหลด (xlsx/csv)", type=['xlsx', 'csv'])
    if uploaded_file:
        if uploaded_file.name.endswith('.csv'):
            df_input = pd.read_csv(uploaded_file)
        else:
            df_input = pd.read_excel(uploaded_file)
        should_run = False

# --- ส่วนการทำงาน ---
if df_input is not None:
    if not should_run:
        st.write(f"✅ พร้อมตรวจสอบทั้งหมด: **{len(df_input)} Address**")
        if st.button("🚀 เริ่มสแกน (Start Scan)", type="primary"):
            should_run = True

    if should_run:
        with st.spinner('กำลังดึงข้อมูล...'):
            raw_results = asyncio.run(process_all_wallets(df_input))
            
        # --- ประมวลผล ---
        now_thai = datetime.utcnow() + timedelta(hours=7)
        st.write(f"🕒 **อัปเดตล่าสุด:** {now_thai.strftime('%d/%m/%Y %H:%M:%S')} (เวลาไทย)")
        
        wallet_stats = {}
        address_details = {}
        grand_total = 0
        active_wallets_set = set()
        active_address_list = [] 
        urgent_list = []

        for res in raw_results:
            if res['status'] == 'ok':
                thaws = res['data'].get('thaws', [])
                w_name = res['wallet']
                addr = res['address']
                
                if w_name not in wallet_stats:
                    wallet_stats[w_name] = 0

                addr_total = sum(t['amount'] for t in thaws) / 1000000
                
                if addr_total > 0:
                    grand_total += addr_total
                    active_wallets_set.add(w_name)
                    wallet_stats[w_name] += addr_total
                    
                    active_address_list.append({"Wallet_Name": w_name, "Address": addr})
                    
                    key = (w_name, addr)
                    if key not in address_details:
                        address_details[key] = {"total": 0, "records": [], "min_sort": 999999999}
                    address_details[key]["total"] += addr_total
                    
                    for thaw in thaws:
                        time_info = process_claim_time(thaw['thawing_period_start'], now_thai)
                        
                        address_details[key]["records"].append({
                            "Date (Thai)": time_info['thai_date_str'],
                            "Amount": thaw['amount'] / 1000000,
                            "Countdown": time_info['countdown'],
                            "Status": "⚠️ ใกล้เคลม" if time_info['is_urgent'] else "รอ",
                            "_sort": time_info['sort_val'] 
                        })
                        
                        if time_info['sort_val'] < address_details[key]["min_sort"] and time_info['sort_val'] > 0:
                            address_details[key]["min_sort"] = time_info['sort_val']

                        if time_info['is_urgent']:
                            urgent_list.append({
                                "Wallet": w_name,
                                "Address": addr,
                                "Date (Thai)": time_info['thai_date_str'],
                                "Amount": thaw['amount'] / 1000000,
                                "Countdown": time_info['countdown'],
                                "_sort": time_info['sort_val']
                            })

        # --- แสดงผล Dashboard ---
        st.markdown("---")
        
        m1, m2 = st.columns(2)
        with m1:
            st.markdown(f"""
            <div class="metric-card" style="background-color:#d4edda; color:#155724;">
                <h3>💰 ยอดรวม (NIGHT)</h3>
                <h1 style="font-size: 3em;">{grand_total:,.2f}</h1>
            </div>""", unsafe_allow_html=True)
        with m2:
            # === แก้ตรงนี้: เปลี่ยนเป็น Address ทั้งหมด ===
            st.markdown(f"""
            <div class="metric-card" style="background-color:#cff4fc; color:#055160;">
                <h3>📝 Address ทั้งหมด</h3>
                <h1 style="font-size: 3em;">{len(active_address_list)}</h1>
            </div>""", unsafe_allow_html=True)

        if active_address_list and source_type != "active":
            df_active = pd.DataFrame(active_address_list)
            st.download_button("📥 โหลด active_wallets.csv", df_active.to_csv(index=False).encode('utf-8'), "active_wallets.csv", "text/csv")
        
        if source_type == "active":
            if st.button("🔄 Reset เพื่อสแกนใหม่"):
                os.remove("active_wallets.csv")
                st.rerun()

        st.markdown("---")

        # ==========================================
        # 🔥 ตารางแจ้งเตือนด่วน
        # ==========================================
        st.header("🚨 รายการที่ต้องรีบเคลม (ภายใน 7 วัน)")
        
        if urgent_list:
            df_urgent = pd.DataFrame(urgent_list).sort_values(by="_sort")
            df_show = df_urgent.drop(columns=["_sort"])
            
            st.error(f"🔥 พบ {len(urgent_list)} รายการ! ดูเวลาถอยหลังช่องขวาสุด")
            
            st.dataframe(
                df_show.style.format({"Amount": "{:,.2f}"}),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.success("✅ สบายใจได้! ไม่มีรายการด่วนใน 7 วันนี้")
        
        st.markdown("---")

        # 3. รายละเอียดแยกตามกระเป๋า
        if active_wallets_set:
            sorted_wallets = sorted(list(active_wallets_set), key=lambda x: wallet_stats[x])
            st.subheader("📂 รายละเอียดแยกตามกระเป๋า")
            
            for w in sorted_wallets:
                w_total = wallet_stats[w]
                with st.expander(f"💼 {w} (รวม: {w_total:,.2f} NIGHT)"):
                    this_wallet_keys = [k for k in address_details.keys() if k[0] == w]
                    sorted_keys = sorted(this_wallet_keys, key=lambda k: address_details[k]['min_sort'])
                    
                    summary_data = []
                    for k in sorted_keys:
                        recs = address_details[k]['records']
                        recs_sorted = sorted(recs, key=lambda r: r['_sort'])
                        nearest = recs_sorted[0] if recs_sorted else {}
                        
                        summary_data.append({
                            "Address": k[1],
                            "Total": address_details[k]['total'],
                            "Next Claim": nearest.get('Date (Thai)', '-'),
                            "Countdown": nearest.get('Countdown', '-')
                        })
                    
                    st.dataframe(pd.DataFrame(summary_data).style.format({"Total": "{:,.2f}"}), use_container_width=True, hide_index=True)
                    
                    st.divider()
                    st.write("##### 🔍 ตารางเวลาเคลมละเอียด")
                    options = sorted_keys
                    format_func = lambda k: f"{k[1]} ({address_details[k]['total']:,.2f})"
                    selected_key = st.selectbox("เลือก Address:", options=options, format_func=format_func, key=f"sel_{w}")
                    
                    if selected_key:
                        records = address_details[selected_key]['records']
                        df_recs = pd.DataFrame(records).sort_values(by="_sort").drop(columns=["_sort"])
                        st.dataframe(df_recs.style.format({"Amount": "{:,.2f}"}), use_container_width=True, hide_index=True)
