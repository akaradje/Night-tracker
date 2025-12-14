import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Offline Mode)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG & KEY
# ==============================================================================
CACHE_FILE = "vesting_data.json"  # ไฟล์สำหรับบันทึกข้อมูล
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f" # Contract NIGHT
# ใส่ Key ของคุณให้แล้วครับ
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
# ==============================================================================

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
    .update-btn { margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

# --- Function: ดึงราคา (Real-time) ---
def get_market_price():
    # 1. ค่าเงินบาท
    thb_rate = 34.0
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=2)
        if r.status_code == 200: thb_rate = r.json().get("rates", {}).get("THB", 34.0)
    except: pass

    # 2. ราคาเหรียญ (USD) โดยใช้ Key ของคุณ
    usd_price = 0
    try:
        url = f"https://deep-index.moralis.io/api/v2/erc20/{TOKEN_ADDRESS}/price?chain=bsc"
        headers = {"X-API-Key": MY_API_KEY} # ใช้ Key ตรงนี้
        
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200: 
            usd_price = r.json().get("usdPrice", 0)
    except Exception as e: 
        print(f"Price Error: {e}")
    
    return usd_price, usd_price * thb_rate

# --- Function: คำนวณเวลา ---
def process_claim_time(iso_str):
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        if total_seconds <= 0:
            return {"text": "✅ เคลมได้เลย", "sort": -999999, "urgent": True, "status": "ready", "date": dt_thai}
        
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        
        parts = []
        if days > 0: parts.append(f"{days}วัน")
        if hours > 0: parts.append(f"{hours}ชม.")
        
        countdown = " ".join(parts) if parts else "เร็วๆ นี้"
        status = "urgent" if days <= 7 else "wait"
        urgent = True if days <= 7 else False
        
        icon = "🔥" if days <= 7 else "⏳"
        return {"text": f"{icon} {countdown}", "sort": total_seconds, "urgent": urgent, "status": status, "date": dt_thai}
    except:
        return {"text": "-", "sort": 999999, "urgent": False, "status": "unknown", "date": None}

# --- Function: ดึงข้อมูลจาก API (ใช้ Headers) ---
async def fetch_vesting_data(session, wallet_name, address):
    url = f"https://mainnet.prod.gd.midnighttge.io/thaws/{address}/schedule"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Origin": "https://redeem.midnight.gd",
        "Referer": "https://redeem.midnight.gd/",
    }
    try:
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status == 200:
                data = await response.json()
                return {"wallet": wallet_name, "address": address, "data": data, "status": "ok"}
            elif response.status == 404:
                return {"wallet": wallet_name, "address": address, "data": {"thaws": []}, "status": "ok"}
            return {"wallet": wallet_name, "address": address, "status": "error"}
    except:
        return {"wallet": wallet_name, "address": address, "status": "fail"}

# --- Function: อัปเดตฐานข้อมูล (Sync) ---
async def update_database(df):
    results = []
    sem = asyncio.Semaphore(10) # 10 จอพร้อมกัน
    async def task(session, row):
        async with sem:
            return await fetch_vesting_data(session, row['Wallet_Name'], row['Address'])

    async with aiohttp.ClientSession() as session:
        tasks = [task(session, row) for index, row in df.iterrows()]
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, f in enumerate(asyncio.as_completed(tasks)):
            res = await f
            results.append(res)
            progress = (i + 1) / len(tasks)
            progress_bar.progress(progress)
            status_text.text(f"📥 กำลังโหลดข้อมูลจาก Blockchain... {i+1}/{len(tasks)}")
            
        progress_bar.empty()
        status_text.empty()
    return results

# ==============================================================================
# 🖥️ MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker (Saved Data Mode)")

col_top1, col_top2 = st.columns([3, 1])

# --- ส่วนโหลดไฟล์รายชื่อกระเป๋า ---
df_input = None
if os.path.exists('wallets.xlsx'):
    df_input = pd.read_excel('wallets.xlsx')
elif os.path.exists('active_wallets.csv'):
    df_input = pd.read_csv('active_wallets.csv')

# --- ปุ่มอัปเดตข้อมูล (มุมขวาบน) ---
with col_top2:
    if df_input is not None:
        if st.button("🔄 ดึงข้อมูลใหม่ (Update)", type="secondary", use_container_width=True):
            if df_input is not None:
                with st.spinner("⏳ กำลังเชื่อมต่อ Blockchain (รอแป๊บ)..."):
                    raw_data = asyncio.run(update_database(df_input))
                    
                    # บันทึกลงไฟล์ JSON
                    save_data = {
                        "updated_at": datetime.now().isoformat(),
                        "wallets": raw_data
                    }
                    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(save_data, f, ensure_ascii=False, indent=4)
                    
                    st.success("✅ อัปเดตข้อมูลเรียบร้อย!")
                    st.rerun()

# --- ส่วนแสดงผล Dashboard ---
if not os.path.exists(CACHE_FILE):
    st.info("👋 ยินดีต้อนรับ! กรุณากดปุ่ม **'🔄 ดึงข้อมูลใหม่'** ด้านบนขวา เพื่อโหลดข้อมูลครั้งแรกครับ")
else:
    # 1. โหลดข้อมูลจากไฟล์ (เร็วมาก)
    with open(CACHE_FILE, 'r', encoding='utf-8') as f:
        cached = json.load(f)
    
    last_update = datetime.fromisoformat(cached.get("updated_at", "")).strftime("%d/%m/%Y %H:%M")
    with col_top1:
        st.caption(f"💾 ข้อมูลบันทึกล่าสุดเมื่อ: **{last_update}** (กดปุ่มขวาบนเพื่ออัปเดต)")

    # 2. ดึงราคา Real-time (แยกต่างหาก)
    with st.spinner("..เช็คราคาตลาด.."):
        p_usd, p_thb = get_market_price()

    # 3. ประมวลผล
    total_night = 0
    wallets_data = {}
    urgent_items = []
    
    # วนลูปข้อมูลที่โหลดจากไฟล์
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
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
                    # คำนวณเวลาใหม่ทุกครั้งที่เปิดหน้าเว็บ (เผื่อวันเปลี่ยน)
                    time_data = process_claim_time(t['thawing_period_start'])
                    amt = t['amount'] / 1_000_000
                    
                    addr_info["claims"].append({
                        "date_str": time_data['date'].strftime('%d/%m/%Y') if time_data['date'] else "-",
                        "amount": amt,
                        "status_text": time_data['text'],
                        "status_code": time_data['status'],
                        "sort": time_data['sort']
                    })
                    
                    if time_data['urgent']:
                        urgent_items.append({
                            "Wallet": w_name,
                            "Address": addr,
                            "Amount": amt,
                            "Value (THB)": amt * p_thb,
                            "Status": time_data['text'],
                            "Date": time_data['date'].strftime('%d/%m'),
                            "_sort": time_data['sort']
                        })
                
                wallets_data[w_name]["addrs"][addr] = addr_info

    # --- แสดงผล Cards ---
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.markdown(f'<div class="metric-card"><h5>🌙 NIGHT ทั้งหมด</h5><h2>{total_night:,.2f}</h2></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคา (Real-time)</h5><h2 style="color:#856404">฿{p_thb:,.4f}</h2><small>${p_usd:,.4f}</small></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่ารวม (บาท)</h5><h2>฿{total_night * p_thb:,.2f}</h2></div>', unsafe_allow_html=True)

    # --- แจ้งเตือนด่วน ---
    if urgent_items:
        st.error(f"🚨 แจ้งเตือน: พบ {len(urgent_items)} รายการต้องเคลม (ภายใน 7 วัน)")
        df_urg = pd.DataFrame(urgent_items).sort_values("_sort").drop(columns=["_sort"])
        st.dataframe(
            df_urg.style.format({"Amount": "{:,.2f}", "Value (THB)": "฿{:,.2f}"})
            .map(lambda x: "background-color: #d4edda" if "✅" in str(x) else "", subset=["Status"]),
            use_container_width=True, hide_index=True
        )

    # --- รายละเอียด ---
    st.subheader("📂 รายละเอียดกระเป๋า (จากข้อมูลที่บันทึกไว้)")
    for w_name, data in sorted(wallets_data.items(), key=lambda x: x[1]['total'], reverse=True):
        val = data['total'] * p_thb
        with st.expander(f"💼 {w_name} | {data['total']:,.2f} NIGHT (฿{val:,.2f})"):
            for addr, info in data['addrs'].items():
                claims = sorted(info['claims'], key=lambda x: x['sort'])
                nearest = claims[0] if claims else {}
                
                c1, c2, c3 = st.columns([3, 2, 2])
                c1.text(f"{addr}")
                c2.markdown(f"**{info['amt']:,.2f}** NIGHT")
                
                s_color = "green" if nearest.get('status_code') == 'ready' else "red" if nearest.get('status_code') == 'urgent' else "gray"
                c3.markdown(f"<span style='color:{s_color}'><b>{nearest.get('status_text', '-')}</b></span>", unsafe_allow_html=True)
                
                df_sub = pd.DataFrame(claims)[["date_str", "amount", "status_text"]]
                df_sub.columns = ["วันที่ปลดล็อค", "จำนวน", "สถานะ"]
                st.dataframe(df_sub.style.format({"จำนวน": "{:,.2f}"}), use_container_width=True, hide_index=True)
                st.markdown("---")
