import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta # <--- 1. เพิ่ม timedelta
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
            
        # --- ประมวลผล (ปรับเวลาไทยตรงนี้) ---
        # 2. ตั้งค่าเวลาไทย (UTC+7)
        now_thai = datetime.utcnow() + timedelta(hours=7)
        today = now_thai 
        
        # แสดงเวลา Update ล่าสุดให้เห็นชัดๆ
        st.write(f"🕒 **อัปเดตล่าสุด:** {now_thai.strftime('%d/%m/%Y %H:%M:%S')} (เวลาไทย)")
        
        wallet_stats = {}
        address_details = {}
        grand_total = 0
        active_wallets_set = set()
        active_address_list = [] 
        
        # ตัวแปรเก็บรายการด่วน (Urgent)
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
                        address_details[key] = {"total": 0, "records": []}
                    address_details[key]["total"] += addr_total
                    
                    for thaw in thaws:
                        # แปลง string วันที่จาก API เป็น datetime object
                        unlock_date_obj = datetime.strptime(thaw['thawing_period_start'][:10], "%Y-%m-%d")
                        
                        # คำนวณวันคงเหลือ (เทียบกับ today ที่เป็นเวลาไทยแล้ว)
                        days_left = (unlock_date_obj - today).days + 1 # +1 เพื่อปัดเศษวันให้ make sense
                        
                        status = "รอ"
                        # เช็คเงื่อนไข 7 วัน
                        if 0 <= days_left <= 7:
                            status = "⚠️ ใกล้เคลม"
                            # เพิ่มลงรายการด่วน
                            urgent_list.append({
                                "Wallet": w_name,
                                "Address": addr,
                                "Date": thaw['thawing_period_start'][:10],
                                "Amount": thaw['amount'] / 1000000,
                                "Days Left": days_left
                            })
                            
                        address_details[key]["records"].append({
                            "Date": thaw['thawing_period_start'][:10],
                            "Amount": thaw['amount'] / 1000000,
                            "Days Left": days_left,
                            "Status": status
                        })

        # --- แสดงผล Dashboard ---
        st.markdown("---")
        
        # 1. Metric Cards
        m1, m2 = st.columns(2)
        with m1:
            st.markdown(f"""
            <div class="metric-card" style="background-color:#d4edda; color:#155724;">
                <h3>💰 ยอดรวม (NIGHT)</h3>
                <h1 style="font-size: 3em;">{grand_total:,.2f}</h1>
            </div>""", unsafe_allow_html=True)
        with m2:
            st.markdown(f"""
            <div class="metric-card" style="background-color:#cff4fc; color:#055160;">
                <h3>💼 กระเป๋า Active</h3>
                <h1 style="font-size: 3em;">{len(active_wallets_set)}</h1>
            </div>""", unsafe_allow_html=True)

        # 2. ปุ่ม Download / Reset
        if active_address_list and source_type != "active":
            df_active = pd.DataFrame(active_address_list)
            st.download_button("📥 โหลด active_wallets.csv", df_active.to_csv(index=False).encode('utf-8'), "active_wallets.csv", "text/csv")
        
        if source_type == "active":
            if st.button("🔄 Reset เพื่อสแกนใหม่"):
                os.remove("active_wallets.csv")
                st.rerun()

        st.markdown("---")

        # ==========================================
        # 🔥 ส่วนที่เพิ่มใหม่: แจ้งเตือน 7 วัน
        # ==========================================
        st.header("🚨 รายการที่ต้องรีบเคลม (ภายใน 7 วัน)")
        
        if urgent_list:
            # แปลงเป็น DataFrame และเรียงตามวันที่เหลือ (น้อยไปมาก)
            df_urgent = pd.DataFrame(urgent_list).sort_values(by="Days Left")
            
            # โชว์ข้อความเตือน
            st.error(f"🔥 พบ {len(urgent_list)} รายการที่ใกล้ถึงกำหนด! กรุณาตรวจสอบด้านล่าง")
            
            # แสดงตาราง (ปรับแต่งสี)
            st.dataframe(
                df_urgent.style.format({"Amount": "{:,.2f}"})
                .background_gradient(cmap="Reds", subset=["Days Left"]),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.success("✅ สบายใจได้! ไม่มีรายการที่ต้องเคลมใน 7 วันนี้")
        
        st.markdown("---")
        # ==========================================

        # 3. รายละเอียดแยกตามกระเป๋า (เหมือนเดิม)
        if active_wallets_set:
            sorted_wallets = sorted(list(active_wallets_set), key=lambda x: wallet_stats[x])
            st.subheader("📂 รายละเอียดแยกตามกระเป๋า (ยอดน้อย -> มาก)")
            
            for w in sorted_wallets:
                w_total = wallet_stats[w]
                with st.expander(f"💼 {w} (รวม: {w_total:,.2f} NIGHT)"):
                    this_wallet_keys = [k for k in address_details.keys() if k[0] == w]
                    sorted_keys = sorted(this_wallet_keys, key=lambda k: address_details[k]['total'])
                    
                    # ตารางสรุป
                    summary_data = []
                    for k in sorted_keys:
                        min_days = min([r['Days Left'] for r in address_details[k]['records']]) if address_details[k]['records'] else 999
                        summary_data.append({
                            "Address": k[1],
                            "Total": address_details[k]['total'],
                            "Next Claim (Days)": min_days,
                            "Status": "⚠️ เตรียมเคลม" if min_days <= 7 else "ปกติ"
                        })
                    st.dataframe(pd.DataFrame(summary_data).style.format({"Total": "{:,.2f}"}), use_container_width=True, hide_index=True)
                    
                    # เจาะลึก
                    st.divider()
                    st.write("##### 🔍 ดูรายละเอียดแต่ละ Address")
                    options = sorted_keys
                    format_func = lambda k: f"{k[1]} ({address_details[k]['total']:,.2f})"
                    selected_key = st.selectbox("เลือก Address:", options=options, format_func=format_func, key=f"sel_{w}")
                    
                    if selected_key:
                        records = address_details[selected_key]['records']
                        st.dataframe(pd.DataFrame(records).style.format({"Amount": "{:,.2f}"}), use_container_width=True, hide_index=True)
