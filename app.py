import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (THB)", page_icon="🌙", layout="wide")

# ==============================================================================
# 🔑 ส่วนตั้งค่า KEY (ใส่ให้แล้วครับ)
# ==============================================================================
YOUR_KEY_HERE = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
# ==============================================================================

# Config อื่นๆ
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f" # Contract NIGHT

# CSS แต่งสวย
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa; border: 1px solid #dee2e6;
        padding: 20px; border-radius: 10px; margin-bottom: 20px; text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .price-card { background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
    .value-card { background-color: #d1e7dd; color: #0f5132; border: 1px solid #badbcc; }
    .stAlert {margin-top: 10px;}
</style>
""", unsafe_allow_html=True)

# --- Function: ดึงราคา THB/USD ---
def get_exchange_rate():
    try:
        resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=3)
        if resp.status_code == 200:
            return resp.json().get("rates", {}).get("THB", 34.0)
        return 34.0
    except:
        return 34.0

# --- Function: ดึงราคา Token + คำนวณเป็นบาท ---
def get_token_price_thb(api_key):
    if not api_key or "วาง_KEY" in api_key:
        return 0, 0
    
    # ดึงราคา USD ของเหรียญจาก Moralis
    usd_price = 0
    url = f"https://deep-index.moralis.io/api/v2/erc20/{TOKEN_ADDRESS}/price?chain=bsc"
    headers = {"X-API-Key": api_key}
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            usd_price = response.json().get("usdPrice", 0)
    except Exception as e:
        print(f"Error fetching token price: {e}")

    # คำนวณราคาไทย
    thb_rate = get_exchange_rate()
    thb_price = usd_price * thb_rate
    
    return usd_price, thb_price

# --- Helper: คำนวณเวลา (Logic ใหม่: แยกแยะสถานะชัดเจน) ---
def process_claim_time(iso_str, now_thai):
    try:
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7) # แปลงเป็นเวลาไทย
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        # กรณีเลยกำหนดแล้ว (ติดลบ) = เคลมได้ทันที
        if total_seconds <= 0:
            return {"text": "✅ เคลมได้เลย (Ready)", "sort": -999999, "urgent": True, "status": "ready", "date": dt_thai}
        
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        
        parts = []
        if days > 0: parts.append(f"{days}วัน")
        if hours > 0: parts.append(f"{hours}ชม.")
        if days == 0 and minutes > 0: parts.append(f"{minutes}น.")
        
        countdown_text = " ".join(parts) if parts else "เร็วๆ นี้"
        
        # กรณีใกล้ถึง (น้อยกว่า 7 วัน)
        if days <= 7:
            return {
                "text": f"🔥 อีก {countdown_text}",
                "sort": total_seconds,
                "urgent": True,
                "status": "urgent",
                "date": dt_thai
            }
        
        # กรณีรอปกติ
        return {
            "text": f"⏳ รอ {countdown_text}",
            "sort": total_seconds,
            "urgent": False,
            "status": "wait",
            "date": dt_thai
        }
    except:
        return {"text": "-", "sort": 999999999, "urgent": False, "status": "unknown", "date": iso_str}

# --- Function: สแกน Vesting (ใช้ API ตัวใหม่ Correct URL) ---
async def fetch_vesting_data(session, wallet_name, address, api_key):
    # URL แบบใหม่ที่ถูกต้อง (เอา Address แทรกกลาง)
    url = f"https://mainnet.prod.gd.midnighttge.io/thaws/{address}/schedule"
    
    headers = {}
    if api_key and "วาง_KEY" not in api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        
    try:
        async with session.get(url, headers=headers, timeout=10) as response:
            if response.status == 200:
                data = await response.json()
                return {"wallet": wallet_name, "address": address, "data": data, "status": "ok"}
            elif response.status == 404:
                # 404 = ไม่มีข้อมูล Vesting (Wallet ว่างเปล่า)
                return {"wallet": wallet_name, "address": address, "data": {"thaws": []}, "status": "ok"}
            else:
                return {"wallet": wallet_name, "address": address, "status": "error"}
    except:
        return {"wallet": wallet_name, "address": address, "status": "fail"}

async def run_scan(df, api_key):
    results = []
    # ลดความเร็วลงนิดหน่อยเพื่อความเสถียร (10 request พร้อมกัน)
    sem = asyncio.Semaphore(10)
    
    async def task(session, row):
        async with sem:
            return await fetch_vesting_data(session, row['Wallet_Name'], row['Address'], api_key)

    async with aiohttp.ClientSession() as session:
        tasks = [task(session, row) for index, row in df.iterrows()]
        progress_bar = st.progress(0)
        status_text = st.empty()
        completed = 0
        total = len(tasks)
        
        for f in asyncio.as_completed(tasks):
            res = await f
            results.append(res)
            completed += 1
            if completed % 5 == 0 or completed == total:
                progress_bar.progress(completed / total)
                status_text.text(f"⏳ กำลังสแกนจาก Blockchain... {completed}/{total}")
        progress_bar.empty()
        status_text.empty()
            
    return results

# --- MAIN UI ---
st.title("🌙 NIGHT Tracker (Corrected API Ver.) 🇹🇭")

# โหลดไฟล์
df_input = None
if os.path.exists('active_wallets.csv'):
    st.success(f"📂 พบข้อมูลเดิม (active_wallets.csv) - พร้อมทำงานทันที")
    df_input = pd.read_csv('active_wallets.csv')
elif os.path.exists('wallets.xlsx'):
    st.info(f"📂 พบไฟล์ wallets.xlsx -> กดปุ่มเพื่อเริ่มสแกน")
    df_input = pd.read_excel('wallets.xlsx')
else:
    uploaded = st.file_uploader("อัปโหลดไฟล์ (xlsx/csv)", type=['xlsx', 'csv'])
    if uploaded:
        df_input = pd.read_csv(uploaded) if uploaded.name.endswith('.csv') else pd.read_excel(uploaded)

if df_input is not None:
    if st.button("🚀 เริ่มสแกน / อัปเดตราคา", type="primary", use_container_width=True):
        
        # 1. ดึงข้อมูลและราคา
        raw_data = asyncio.run(run_scan(df_input, YOUR_KEY_HERE))
        
        with st.spinner("💸 กำลังเช็คราคา NIGHT และค่าเงินบาท..."):
            price_usd, price_thb = get_token_price_thb(YOUR_KEY_HERE)
        
        # 2. ประมวลผล
        now_thai = datetime.utcnow() + timedelta(hours=7)
        total_night = 0
        wallets_data = {}
        urgent_items = []
        active_list = []

        for item in raw_data:
            if item['status'] == 'ok':
                thaws = item['data'].get('thaws', [])
                w_name = item['wallet']
                addr = item['address']
                
                sum_amt = sum(t['amount'] for t in thaws) / 1_000_000
                if sum_amt > 0:
                    total_night += sum_amt
                    if w_name not in wallets_data: wallets_data[w_name] = {"total": 0, "addrs": {}}
                    wallets_data[w_name]["total"] += sum_amt
                    
                    addr_info = {"amt": sum_amt, "claims": []}
                    for t in thaws:
                        time_data = process_claim_time(t['thawing_period_start'], now_thai)
                        amt = t['amount'] / 1_000_000
                        
                        addr_info["claims"].append({
                            "date": time_data['date'].strftime('%d/%m/%Y %H:%M'),
                            "amount": amt,
                            "countdown": time_data['text'],
                            "sort": time_data['sort'],
                            "status": time_data['status']
                        })
                        
                        # เก็บรายการด่วน (เคลมได้แล้ว หรือ < 7 วัน)
                        if time_data['urgent']:
                            urgent_items.append({
                                "Wallet": w_name,
                                "Address": addr,
                                "Amount": amt,
                                "Value (THB)": amt * price_thb,
                                "Status": time_data['text'],
                                "Date": time_data['date'].strftime('%d/%m %H:%M'),
                                "_sort": time_data['sort']
                            })
                            
                    wallets_data[w_name]["addrs"][addr] = addr_info
                    active_list.append({"Wallet_Name": w_name, "Address": addr})

        # --- แสดงผล ---
        st.divider()
        st.write(f"🕒 อัปเดตล่าสุด: {now_thai.strftime('%d/%m/%Y %H:%M:%S')}")

        # Cards
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(f'<div class="metric-card"><h5>🌙 NIGHT ทั้งหมด</h5><h2>{total_night:,.2f}</h2></div>', unsafe_allow_html=True)
        
        price_text = f"฿{price_thb:,.4f}" if price_thb > 0 else "N/A"
        m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคาไทย (THB)</h5><h2 style="color:#856404">{price_text}</h2><small>(${price_usd:,.4f})</small></div>', unsafe_allow_html=True)
        
        val_thb = total_night * price_thb
        m3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าพอร์ต (บาท)</h5><h2>฿{val_thb:,.2f}</h2></div>', unsafe_allow_html=True)
        
        m4.markdown(f'<div class="metric-card"><h5>📝 Active Wallets</h5><h2>{len(active_list)}</h2></div>', unsafe_allow_html=True)

        # รายการด่วน (ตารางสีแดง)
        if urgent_items:
            st.error(f"🚨 ต้องรีบเคลม! พบ {len(urgent_items)} รายการ (เคลมได้แล้ว หรือ < 7 วัน)")
            df_urg = pd.DataFrame(urgent_items).sort_values("_sort").drop(columns=["_sort"])
            # Format ให้สวยงาม
            st.dataframe(
                df_urg.style.format({"Amount": "{:,.2f}", "Value (THB)": "฿{:,.2f}"})
                .map(lambda x: "background-color: #d4edda" if "✅" in str(x) else "", subset=["Status"]),
                use_container_width=True, 
                hide_index=True
            )
        else:
            st.success("✅ สบายใจได้! ไม่มีรายการด่วนใน 7 วันนี้")

        # รายละเอียด
        st.subheader("📂 รายละเอียดรายกระเป๋า (บาท)")
        for w_name, data in sorted(wallets_data.items(), key=lambda x: x[1]['total'], reverse=True):
            val = data['total'] * price_thb
            with st.expander(f"💼 {w_name} | รวม: {data['total']:,.2f} NIGHT (฿{val:,.2f})"):
                for addr, info in data['addrs'].items():
                    claims = sorted(info['claims'], key=lambda x: x['sort'])
                    nearest = claims[0] if claims else {}
                    
                    c1, c2, c3 = st.columns([3, 2, 2])
                    c1.markdown(f"**Address:** `{addr}`")
                    c2.markdown(f"**ยอดรวม:** {info['amt']:,.2f}")
                    
                    # สีของสถานะ
                    status_color = "gray"
                    if nearest.get('status') == 'ready': status_color = "green"
                    elif nearest.get('status') == 'urgent': status_color = "red"
                    
                    c3.markdown(f"**สถานะ:** <span style='color:{status_color}'><b>{nearest.get('countdown', '-')}</b></span>", unsafe_allow_html=True)
                    
                    # ตารางย่อย
                    df_sub = pd.DataFrame(claims).drop(columns=['sort', 'status'])
                    st.dataframe(df_sub, use_container_width=True, hide_index=True)
                    st.markdown("---")

        # Auto-Save CSV
        if active_list:
            pd.DataFrame(active_list).to_csv('active_wallets.csv', index=False)
