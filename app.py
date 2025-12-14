import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Split View)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG & KEY
# ==============================================================================
CACHE_FILE = "vesting_data.json"
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f"
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
# ==============================================================================

st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa; border: 1px solid #dee2e6;
        padding: 15px; border-radius: 10px; margin-bottom: 20px; text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .ready-card { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    .locked-card { background-color: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
    .total-card { background-color: #cff4fc; color: #055160; border: 1px solid #b6effb; }
    .update-btn { margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

# --- Function: ดึงราคา ---
def get_market_price():
    thb_rate = 34.0
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=2)
        if r.status_code == 200: thb_rate = r.json().get("rates", {}).get("THB", 34.0)
    except: pass

    usd_price = 0
    try:
        url = f"https://deep-index.moralis.io/api/v2/erc20/{TOKEN_ADDRESS}/price?chain=bsc"
        headers = {"X-API-Key": MY_API_KEY}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200: usd_price = r.json().get("usdPrice", 0)
    except: pass
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
        
        # ✅ ผ่านกำหนดแล้ว = พร้อมเคลม (Ready)
        if total_seconds <= 0:
            return {"text": "✅ พร้อมเคลม", "sort": -999999, "is_ready": True, "urgent": True, "date": dt_thai}
        
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        
        parts = []
        if days > 0: parts.append(f"{days}วัน")
        if hours > 0: parts.append(f"{hours}ชม.")
        
        countdown = " ".join(parts) if parts else "เร็วๆ นี้"
        urgent = True if days <= 7 else False
        
        # 🔥 ใกล้ถึง หรือ ⏳ รอ
        icon = "🔥" if days <= 7 else "🔒"
        return {"text": f"{icon} อีก {countdown}", "sort": total_seconds, "is_ready": False, "urgent": urgent, "date": dt_thai}
    except:
        return {"text": "-", "sort": 999999, "is_ready": False, "urgent": False, "date": None}

# --- Function: API ---
async def fetch_vesting_data(session, wallet_name, address):
    url = f"https://mainnet.prod.gd.midnighttge.io/thaws/{address}/schedule"
    headers = {
        "User-Agent": "Mozilla/5.0",
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

# --- Function: Update DB ---
async def update_database(df):
    results = []
    sem = asyncio.Semaphore(10)
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
            progress_bar.progress((i + 1) / len(tasks))
            status_text.text(f"📥 กำลังโหลด... {i+1}/{len(tasks)}")
        progress_bar.empty()
        status_text.empty()
    return results

# ==============================================================================
# MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker: แยกยอด พร้อมใช้ vs ล็อค")

col_top1, col_top2 = st.columns([3, 1])

# โหลดไฟล์กระเป๋า
df_input = None
if os.path.exists('wallets.xlsx'): df_input = pd.read_excel('wallets.xlsx')
elif os.path.exists('active_wallets.csv'): df_input = pd.read_csv('active_wallets.csv')

# ปุ่มอัปเดต
with col_top2:
    if df_input is not None:
        if st.button("🔄 ดึงข้อมูลใหม่ (Update)", type="secondary", use_container_width=True):
            with st.spinner("⏳ กำลังโหลด..."):
                raw_data = asyncio.run(update_database(df_input))
                save_data = {"updated_at": datetime.now().isoformat(), "wallets": raw_data}
                with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=4)
                st.success("✅ อัปเดตเสร็จสิ้น!")
                st.rerun()

if not os.path.exists(CACHE_FILE):
    st.info("👋 กดปุ่ม '🔄 ดึงข้อมูลใหม่' มุมขวาบนเพื่อเริ่มใช้งานครับ")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    
    # ดึงราคา
    with st.spinner("..เช็คราคา.."):
        p_usd, p_thb = get_market_price()

    total_ready = 0
    total_locked = 0
    wallets_data = {}
    urgent_items = []
    
    # Loop คำนวณ
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            
            w_ready = 0
            w_locked = 0
            
            addr_info = {"claims": []}
            
            for t in thaws:
                time_data = process_claim_time(t['thawing_period_start'])
                amt = t['amount'] / 1_000_000
                
                # แยกยอด Ready vs Locked
                if time_data['is_ready']:
                    total_ready += amt
                    w_ready += amt
                else:
                    total_locked += amt
                    w_locked += amt
                
                addr_info["claims"].append({
                    "date": time_data['date'].strftime('%d/%m/%y') if time_data['date'] else "-",
                    "amount": amt,
                    "status": time_data['text'],
                    "is_ready": time_data['is_ready'],
                    "sort": time_data['sort']
                })
                
                if time_data['urgent'] or time_data['is_ready']:
                    urgent_items.append({
                        "Wallet": w_name,
                        "Type": "✅ พร้อมถอน" if time_data['is_ready'] else "🔥 ใกล้ถึง",
                        "Amount": amt,
                        "Value (THB)": amt * p_thb,
                        "Status": time_data['text'],
                        "_sort": time_data['sort']
                    })
            
            # เก็บข้อมูลถ้ามียอด
            if w_ready + w_locked > 0:
                if w_name not in wallets_data: wallets_data[w_name] = {"ready": 0, "locked": 0, "addrs": {}}
                wallets_data[w_name]["ready"] += w_ready
                wallets_data[w_name]["locked"] += w_locked
                
                # เก็บรายละเอียด Address
                addr_info["summary"] = f"พร้อม: {w_ready:,.2f} | ล็อค: {w_locked:,.2f}"
                wallets_data[w_name]["addrs"][addr] = addr_info

    # --- 📊 แสดงผลแบบแยกยอด ---
    st.divider()
    
    # Row 1: Dashboard ใหญ่
    c1, c2, c3 = st.columns(3)
    
    # การ์ด 1: พร้อมถอน (สำคัญสุด)
    val_ready = total_ready * p_thb
    c1.markdown(f"""
    <div class="metric-card ready-card">
        <h5>🟢 พร้อมถอนทันที (Ready)</h5>
        <h2>{total_ready:,.2f} NIGHT</h2>
        <small>มูลค่า: ฿{val_ready:,.2f}</small>
    </div>""", unsafe_allow_html=True)
    
    # การ์ด 2: รอล็อค (อนาคต)
    val_locked = total_locked * p_thb
    c2.markdown(f"""
    <div class="metric-card locked-card">
        <h5>🔒 รอปลดล็อค (Locked)</h5>
        <h2>{total_locked:,.2f} NIGHT</h2>
        <small>มูลค่า: ฿{val_locked:,.2f}</small>
    </div>""", unsafe_allow_html=True)
    
    # การ์ด 3: รวมทั้งหมด
    total_all = total_ready + total_locked
    val_all = total_all * p_thb
    c3.markdown(f"""
    <div class="metric-card total-card">
        <h5>💰 ยอดคงเหลือรวม (Total)</h5>
        <h2>{total_all:,.2f} NIGHT</h2>
        <small>รวมทั้งพอร์ต: ฿{val_all:,.2f}</small>
    </div>""", unsafe_allow_html=True)

    # ตารางแจ้งเตือน
    if urgent_items:
        st.error(f"🚨 รายการที่ต้องจัดการ ({len(urgent_items)} รายการ)")
        df_urg = pd.DataFrame(urgent_items).sort_values("_sort").drop(columns=["_sort"])
        st.dataframe(df_urg, use_container_width=True, hide_index=True)

    # รายละเอียดรายกระเป๋า
    st.subheader("📂 รายละเอียดรายกระเป๋า")
    # เรียงตามยอดพร้อมถอนก่อน (จะได้รู้ว่าอันไหนสำคัญ)
    sorted_wallets = sorted(wallets_data.items(), key=lambda x: x[1]['ready'], reverse=True)
    
    for w_name, data in sorted_wallets:
        total_w = data['ready'] + data['locked']
        ready_icon = "🟢" if data['ready'] > 0 else "⚪"
        
        with st.expander(f"{ready_icon} {w_name} | พร้อม: {data['ready']:,.2f} | ล็อค: {data['locked']:,.2f} (รวม {total_w:,.2f})"):
            for addr, info in data['addrs'].items():
                st.write(f"**Address:** `{addr}`")
                
                # แปลงเป็น DataFrame สวยๆ
                df_claims = pd.DataFrame(info['claims'])[['date', 'amount', 'status']]
                df_claims.columns = ["วันที่", "จำนวน (NIGHT)", "สถานะ"]
                
                # ไฮไลท์แถวที่พร้อมเคลม
                st.dataframe(
                    df_claims.style.format({"จำนวน (NIGHT)": "{:,.2f}"})
                    .apply(lambda x: ['background-color: #d4edda' if '✅' in str(val) else '' for val in x], axis=1),
                    use_container_width=True, hide_index=True
                )
                st.markdown("---")
