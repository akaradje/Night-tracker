import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Official Style)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG & KEY
# ==============================================================================
CACHE_FILE = "vesting_data.json"
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f"
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
# ==============================================================================

# CSS: แต่งให้เหมือนเว็บ Official (กล่องม่วง, ตัวหนังสือ, เส้นขีด)
st.markdown("""
<style>
    .midnight-card {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 24px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        font-family: sans-serif;
    }
    .thaw-header {
        background-color: #f9f9f9;
        padding: 12px 16px;
        border-radius: 8px;
        font-weight: 600;
        color: #333;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 16px;
    }
    .purple-box {
        background-color: #f3f0ff; /* สีพื้นหลังม่วงอ่อน */
        border: 1px solid #dcd0ff;
        border-radius: 8px;
        padding: 20px;
        color: #5b4da8; /* สีตัวหนังสือม่วงเข้ม */
        margin-bottom: 20px;
    }
    .purple-box h2 {
        margin: 0;
        padding: 5px 0;
        font-size: 2em;
        font-weight: 700;
        color: #4a3b89;
    }
    .detail-section {
        margin-top: 10px;
        border-top: 1px solid #eee;
        padding-top: 15px;
    }
    .detail-row {
        display: flex;
        justify-content: space-between;
        padding: 8px 0;
        font-size: 0.95em;
        border-bottom: 1px solid #f5f5f5;
    }
    .detail-label { color: #666; }
    .detail-val { font-weight: 600; color: #333; }
    
    /* Status Badges for Table */
    .badge-redeemed { background-color: #e2e3e5; color: #383d41; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
    .badge-ready { background-color: #d1e7dd; color: #0f5132; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; font-weight: bold; }
    .badge-locked { background-color: #fff3cd; color: #856404; padding: 2px 8px; border-radius: 4px; font-size: 0.8em; }
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

# --- Function: คำนวณสถานะ (สำคัญมาก Logic นี้) ---
def process_claim_status(iso_str, tx_id):
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        # Logic ตาม Official
        # 1. มี Transaction ID = Redeemed (รับไปแล้ว)
        if tx_id is not None and len(str(tx_id)) > 5:
             return {"text": "✅ Redeemed", "status": "redeemed", "date": dt_thai, "sort": 999999, "days_left": 0}
        
        # 2. ไม่มี Tx ID แต่เวลาผ่านไปแล้ว = Redeemable Now (พร้อมรับ)
        if total_seconds <= 0:
            return {"text": "🟣 Redeemable Now", "status": "ready", "date": dt_thai, "sort": -999999, "days_left": 0}
        
        # 3. ยังไม่ถึงเวลา = Locked
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return {"text": f"🔒 Locked ({days}d {hours}h)", "status": "locked", "date": dt_thai, "sort": total_seconds, "days_left": days}
            
    except:
        return {"text": "-", "status": "unknown", "date": None, "sort": 999999, "days_left": 0}

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
            status_text.text(f"📥 กำลังโหลดข้อมูล... {i+1}/{len(tasks)}")
        progress_bar.empty()
        status_text.empty()
    return results

# ==============================================================================
# MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker (Official Layout)")

col_top1, col_top2 = st.columns([3, 1])

# โหลดไฟล์กระเป๋า
df_input = None
if os.path.exists('wallets.xlsx'): df_input = pd.read_excel('wallets.xlsx')
elif os.path.exists('active_wallets.csv'): df_input = pd.read_csv('active_wallets.csv')

# ปุ่มอัปเดต
with col_top2:
    if df_input is not None:
        if st.button("🔄 ดึงข้อมูลใหม่ (Update)", type="primary", use_container_width=True):
            with st.spinner("⏳ กำลังเชื่อมต่อ Blockchain..."):
                raw_data = asyncio.run(update_database(df_input))
                save_data = {"updated_at": datetime.now().isoformat(), "wallets": raw_data}
                with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=4)
                st.success("✅ อัปเดตเสร็จสิ้น! (กรุณารอรีเฟรช)")
                st.rerun()

if not os.path.exists(CACHE_FILE):
    st.warning("⚠️ ไม่พบไฟล์ข้อมูล: กรุณากดปุ่ม **'🔄 ดึงข้อมูลใหม่'** ด้านบนขวา 1 ครั้ง เพื่อเริ่มระบบครับ")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    
    # ดึงราคา
    with st.spinner("..เช็คราคา.."):
        p_usd, p_thb = get_market_price()

    # ยอดรวม Dashboard บนสุด
    grand_redeemable_now = 0
    grand_left = 0
    grand_total = 0

    # คำนวณยอดรวมก่อน
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            for t in thaws:
                amt = t['amount'] / 1_000_000
                tx_id = t.get('transaction_id')
                status = process_claim_status(t['thawing_period_start'], tx_id)['status']
                
                grand_total += amt
                if status == 'ready': grand_redeemable_now += amt
                if status != 'redeemed': grand_left += amt

    # แสดงยอดรวมใหญ่ (Big Summary)
    st.markdown("### 📊 ภาพรวมทั้งหมด")
    m1, m2, m3 = st.columns(3)
    m1.metric("🟣 Redeemable Now (พร้อมถอน)", f"{grand_redeemable_now:,.2f}", f"฿{grand_redeemable_now*p_thb:,.2f}")
    m2.metric("⏳ Total Left (เหลือ)", f"{grand_left:,.2f}", f"฿{grand_left*p_thb:,.2f}")
    m3.metric("📦 Total Allocation (ทั้งหมด)", f"{grand_total:,.2f}", f"฿{grand_total*p_thb:,.2f}")
    st.divider()

    # --- ส่วนแสดงผลรายกระเป๋า (Official Style) ---
    st.markdown("### 💼 รายละเอียดรายกระเป๋า")
    
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            
            # ตัวแปรสำหรับ Card นี้
            w_alloc = 0
            w_redeemed = 0
            w_left = 0
            w_redeemable_now = 0
            
            # สำหรับหา Current Thaw
            total_thaws = len(thaws)
            redeemed_count = 0
            next_thaw_date = None
            
            claims_data = []

            for t in thaws:
                tx_id = t.get('transaction_id')
                status_info = process_claim_status(t['thawing_period_start'], tx_id)
                amt = t['amount'] / 1_000_000
                
                w_alloc += amt
                
                # Logic การนับยอด
                if status_info['status'] == 'redeemed':
                    w_redeemed += amt
                    redeemed_count += 1
                else:
                    w_left += amt # รวมทั้ง Ready และ Locked
                    if status_info['status'] == 'ready':
                        w_redeemable_now += amt
                    elif status_info['status'] == 'locked':
                        # หาวันที่ปลดล็อคที่ใกล้ที่สุด
                        if next_thaw_date is None or (status_info['date'] and status_info['date'] < next_thaw_date):
                            next_thaw_date = status_info['date']

                claims_data.append({
                    "Date": status_info['date'].strftime('%d/%m/%Y') if status_info['date'] else "-",
                    "Amount": amt,
                    "Status": status_info['text'],
                    "_raw_status": status_info['status'],
                    "_sort": status_info['sort']
                })

            # คำนวณ Current Thaw (เช่น 2/4)
            # ถ้า Redeemed ไปแล้ว 1 แปลว่าตอนนี้รออันที่ 2 -> index = 1+1 = 2
            curr_thaw = redeemed_count + 1
            if curr_thaw > total_thaws: curr_thaw = total_thaws # กรณีครบแล้ว
            
            thaw_text = f"Current thaw: {curr_thaw}/{total_thaws}"
            
            # คำนวณ Countdown (Thaws in...)
            countdown_text = "Completed"
            if w_redeemable_now > 0:
                countdown_text = "Available Now!"
            elif next_thaw_date:
                diff = next_thaw_date - (datetime.utcnow() + timedelta(hours=7))
                d = diff.days
                h = diff.seconds // 3600
                m = (diff.seconds % 3600) // 60
                countdown_text = f"Thaws in: {d}d / {h}h / {m}m"

            # --- RENDER CARD (HTML/CSS Injection) ---
            with st.expander(f"🔹 {w_name} ({addr[:6]}...{addr[-4:]})", expanded=True):
                
                # 1. Header (Gray Bar)
                st.markdown(f"""
                <div class="thaw-header">
                    <span>{thaw_text} <small style="color:#666; font-weight:normal;">(Alloc: {w_alloc:,.2f})</small></span>
                    <span style="font-size:0.9em;">{countdown_text}</span>
                </div>
                """, unsafe_allow_html=True)
                
                # 2. Purple Box (Redeemable Now)
                purple_content = f"{w_redeemable_now:,.2f} NIGHT"
                purple_sub = f"≈ ฿{w_redeemable_now * p_thb:,.2f}"
                if w_redeemable_now == 0:
                    purple_sub = "NIGHT tokens become available after current thaw"
                
                st.markdown(f"""
                <div class="purple-box">
                    <small>Redeemable now:</small>
                    <h2>{purple_content}</h2>
                    <small>{purple_sub}</small>
                </div>
                """, unsafe_allow_html=True)

                # 3. Details Section (3 Lines)
                st.markdown(f"""
                <div class="detail-section">
                    <div class="detail-row">
                        <span class="detail-label">Redeemed so far:</span>
                        <span class="detail-val">{w_redeemed:,.2f} NIGHT</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Total left to redeem:</span>
                        <span class="detail-val">{w_left:,.2f} NIGHT</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Your total allocation size:</span>
                        <span class="detail-val">{w_alloc:,.2f} NIGHT</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # 4. Data Table (ข้อมูลที่ห้ามเอาออก)
                st.caption("📄 Transaction Details:")
                df_show = pd.DataFrame(claims_data).sort_values("_sort")
                
                # Function แต่งสีในตาราง
                def color_table(val):
                    if "✅" in str(val): return 'color: green'
                    if "🟣" in str(val): return 'color: purple; font-weight: bold'
                    return 'color: gray'

                st.dataframe(
                    df_show[['Date', 'Amount', 'Status']].style.applymap(color_table, subset=['Status']),
                    use_container_width=True,
                    hide_index=True
                )
