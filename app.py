import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Official + Alerts)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG & KEY
# ==============================================================================
CACHE_FILE = "vesting_data.json"
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f"
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
# ==============================================================================

# CSS: Official Style + Alert Style
st.markdown("""
<style>
    .thaw-header {
        background-color: #f8f9fa; padding: 12px 16px; border-radius: 8px 8px 0 0;
        font-weight: 600; color: #333; display: flex; justify-content: space-between; align-items: center;
        border: 1px solid #e0e0e0; border-bottom: none;
    }
    .card-body {
        border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 8px 8px;
        padding: 20px; margin-bottom: 20px; background-color: white;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }
    .purple-box {
        background-color: #f3f0ff; border: 1px solid #dcd0ff; border-radius: 8px;
        padding: 15px; color: #5b4da8; margin-bottom: 15px;
    }
    .purple-box h2 { margin: 0; padding: 5px 0; font-size: 1.8em; font-weight: 700; color: #4a3b89; }
    
    /* Stats Row */
    .detail-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.9em; }
    .detail-label { color: #666; }
    .detail-val { font-weight: 600; color: #333; }

    /* Alert Box override */
    .stAlert { margin-top: 20px; margin-bottom: 20px; }
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

# --- Function: คำนวณสถานะ ---
def process_claim_status(iso_str, tx_id):
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        # 1. Redeemed
        if tx_id is not None and len(str(tx_id)) > 5:
             return {"text": "✅ Redeemed", "status": "redeemed", "date": dt_thai, "sort": 999999, "urgent": False}
        
        # 2. Ready (Redeemable Now)
        if total_seconds <= 0:
            return {"text": "🟣 Redeemable Now", "status": "ready", "date": dt_thai, "sort": -999999, "urgent": True}
        
        # 3. Locked
        else:
            days = total_seconds // 86400
            urgent = True if days <= 7 else False
            icon = "🔥" if urgent else "🔒"
            return {"text": f"{icon} Locked ({days}d)", "status": "locked", "date": dt_thai, "sort": total_seconds, "urgent": urgent}
            
    except:
        return {"text": "-", "status": "unknown", "date": None, "sort": 999999, "urgent": False}

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
st.title("🌙 NIGHT Tracker (Full Option)")

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
    st.error("⚠️ ไฟล์ข้อมูลยังว่างอยู่! กรุณากดปุ่ม **'🔄 ดึงข้อมูลใหม่'** ที่มุมขวาบน 1 ครั้ง")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    
    # ดึงราคา
    with st.spinner("..เช็คราคา.."):
        p_usd, p_thb = get_market_price()

    # --- ส่วนคำนวณยอดรวม (Global Calculation) ---
    grand_redeemable_now = 0
    grand_left = 0
    grand_total = 0
    urgent_items_list = [] # เก็บรายการด่วน

    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']

            for t in thaws:
                amt = t['amount'] / 1_000_000
                tx_id = t.get('transaction_id')
                status_info = process_claim_status(t['thawing_period_start'], tx_id)
                
                grand_total += amt
                if status_info['status'] == 'ready': 
                    grand_redeemable_now += amt
                
                if status_info['status'] != 'redeemed': 
                    grand_left += amt

                # เก็บเข้า Alert List (ถ้า พร้อมถอน หรือ < 7 วัน)
                if status_info['urgent']:
                    urgent_items_list.append({
                        "Wallet": w_name,
                        "Address": addr,
                        "Amount": amt,
                        "Value (THB)": amt * p_thb,
                        "Status": status_info['text'],
                        "Date": status_info['date'].strftime('%d/%m/%Y'),
                        "_sort": status_info['sort']
                    })

    # --- 1. แสดงภาพรวม (Big Metrics) ---
    st.markdown("### 📊 ภาพรวมทั้งหมด")
    m1, m2, m3 = st.columns(3)
    m1.metric("🟣 Redeemable Now (พร้อมถอน)", f"{grand_redeemable_now:,.2f}", f"฿{grand_redeemable_now*p_thb:,.2f}")
    m2.metric("⏳ Total Left (เหลือ)", f"{grand_left:,.2f}", f"฿{grand_left*p_thb:,.2f}")
    m3.metric("📦 Total Allocation (ทั้งหมด)", f"{grand_total:,.2f}", f"฿{grand_total*p_thb:,.2f}")
    
    # --- 2. แจ้งเตือน (ALERTS) กลับมาแล้ว! ---
    if urgent_items_list:
        st.error(f"🚨 แจ้งเตือน: พบ {len(urgent_items_list)} รายการต้องเคลม (พร้อมถอน หรือ < 7 วัน)")
        df_urg = pd.DataFrame(urgent_items_list).sort_values("_sort").drop(columns=["_sort"])
        
        # แต่งตาราง Alert
        st.dataframe(
            df_urg.style.format({"Amount": "{:,.2f}", "Value (THB)": "฿{:,.2f}"})
            .map(lambda x: "background-color: #d4edda; color: green; font-weight: bold" if "🟣" in str(x) else "color: red", subset=["Status"]),
            use_container_width=True, hide_index=True
        )
    else:
        st.success("✅ สบายใจได้! ไม่มีรายการด่วนใน 7 วันนี้")

    st.divider()

    # --- 3. แสดงผลรายกระเป๋า (Official Style + Data Table) ---
    st.subheader("📂 รายละเอียดรายกระเป๋า (Official Cards)")
    
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            
            w_alloc = 0
            w_redeemed = 0
            w_left = 0
            w_redeemable_now = 0
            
            total_thaws = len(thaws)
            redeemed_count = 0
            next_thaw_date = None
            
            claims_data = []

            for t in thaws:
                tx_id = t.get('transaction_id')
                status_info = process_claim_status(t['thawing_period_start'], tx_id)
                amt = t['amount'] / 1_000_000
                w_alloc += amt
                
                if status_info['status'] == 'redeemed':
                    w_redeemed += amt
                    redeemed_count += 1
                else:
                    w_left += amt
                    if status_info['status'] == 'ready':
                        w_redeemable_now += amt
                    elif status_info['status'] == 'locked':
                        if next_thaw_date is None or (status_info['date'] and status_info['date'] < next_thaw_date):
                            next_thaw_date = status_info['date']

                claims_data.append({
                    "Date": status_info['date'].strftime('%d/%m/%Y') if status_info['date'] else "-",
                    "Amount": amt,
                    "Status": status_info['text'],
                    "_sort": status_info['sort']
                })

            # คำนวณ Current Thaw
            curr_thaw = redeemed_count + 1
            if curr_thaw > total_thaws: curr_thaw = total_thaws
            
            # คำนวณเวลาถอยหลัง
            countdown_text = "Completed"
            if w_redeemable_now > 0: countdown_text = "Available Now!"
            elif next_thaw_date:
                diff = next_thaw_date - (datetime.utcnow() + timedelta(hours=7))
                d = diff.days
                countdown_text = f"Thaws in: {d} days"

            # --- RENDER CARD ---
            # ใช้ st.container เพื่อวาดกรอบ
            with st.expander(f"💼 {w_name} | {w_redeemable_now:,.2f} Ready", expanded=True):
                
                # 3.1 Header (Current Thaw)
                st.markdown(f"""
                <div class="thaw-header">
                    <span>Current thaw: {curr_thaw}/{total_thaws}</span>
                    <span style="font-size:0.9em; color:#666;">{countdown_text}</span>
                </div>
                """, unsafe_allow_html=True)
                
                # 3.2 Body
                st.markdown('<div class="card-body">', unsafe_allow_html=True)
                
                # กล่องม่วง (Redeemable)
                purple_sub = f"≈ ฿{w_redeemable_now * p_thb:,.2f}" if w_redeemable_now > 0 else "Tokens become available after current thaw"
                st.markdown(f"""
                <div class="purple-box">
                    <small>Redeemable now:</small>
                    <h2>{w_redeemable_now:,.2f} NIGHT</h2>
                    <small>{purple_sub}</small>
                </div>
                """, unsafe_allow_html=True)

                # สรุป 3 บรรทัด
                st.markdown(f"""
                <div class="detail-row"><span class="detail-label">Redeemed so far:</span> <span class="detail-val">{w_redeemed:,.2f}</span></div>
                <div class="detail-row"><span class="detail-label">Total left to redeem:</span> <span class="detail-val">{w_left:,.2f}</span></div>
                <div class="detail-row"><span class="detail-label">Total allocation size:</span> <span class="detail-val">{w_alloc:,.2f}</span></div>
                </div>
                """, unsafe_allow_html=True)

                # 3.3 Data Table (อยู่ข้างใน Expander เลย)
                st.caption("📄 Transaction Details:")
                df_show = pd.DataFrame(claims_data).sort_values("_sort")
                def color_table(val):
                    if "✅" in str(val): return 'color: green'
                    if "🟣" in str(val): return 'color: purple; font-weight: bold'
                    return 'color: gray'

                st.dataframe(
                    df_show[['Date', 'Amount', 'Status']].style.applymap(color_table, subset=['Status']),
                    use_container_width=True, hide_index=True
                )
