import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Fixed)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG & KEY
# ==============================================================================
CACHE_FILE = "vesting_data.json"
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f"
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
# ==============================================================================

# CSS Styling
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
    }
    .purple-box {
        background-color: #f3f0ff; border: 1px solid #dcd0ff; border-radius: 8px;
        padding: 15px; color: #5b4da8; margin-bottom: 15px; text-align: center;
    }
    .purple-box h2 { margin: 0; padding: 5px 0; font-size: 2em; font-weight: 700; color: #4a3b89; }
    
    .detail-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.9em; }
    .detail-label { color: #666; }
    .detail-val { font-weight: 600; color: #333; }
    
    /* ปรับแต่ง Alert ให้เห็นชัด */
    .stAlert { margin-top: 10px; margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

# --- Function: ดึงราคา (ใช้ Logic เดิมที่เคยใช้ได้) ---
def get_market_price():
    thb_rate = 34.0
    try:
        # 1. ดึงค่าเงินบาท
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=2)
        if r.status_code == 200: thb_rate = r.json().get("rates", {}).get("THB", 34.0)
    except: pass

    usd_price = 0
    try:
        # 2. ดึงราคา NIGHT
        url = f"https://deep-index.moralis.io/api/v2/erc20/{TOKEN_ADDRESS}/price?chain=bsc"
        headers = {"X-API-Key": MY_API_KEY}
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200: usd_price = r.json().get("usdPrice", 0)
    except: pass
    
    return usd_price, usd_price * thb_rate

# --- Function: คำนวณสถานะ (Logic Official) ---
def process_claim_status(iso_str, tx_id):
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        # 1. มี Tx ID = เคลมแล้ว (Redeemed)
        if tx_id is not None and len(str(tx_id)) > 5:
             return {"text": "✅ Redeemed", "status": "redeemed", "date": dt_thai, "sort": 999999, "urgent": False}
        
        # 2. ไม่มี Tx ID และ เวลาติดลบ = พร้อมเคลม (Ready)
        if total_seconds <= 0:
            return {"text": "🟣 Redeemable Now", "status": "ready", "date": dt_thai, "sort": -999999, "urgent": True}
        
        # 3. ยังไม่ถึงเวลา = ล็อค (Locked)
        else:
            days = total_seconds // 86400
            urgent = True if days <= 7 else False # แจ้งเตือนถ้าเหลือน้อยกว่า 7 วัน
            return {"text": f"🔒 Locked ({days}d)", "status": "locked", "date": dt_thai, "sort": total_seconds, "urgent": urgent}
            
    except:
        return {"text": "-", "status": "unknown", "date": None, "sort": 999999, "urgent": False}

# --- Function: ดึง API (ใช้ Headers ชุดที่ Bypass ผ่านแน่นอน) ---
async def fetch_vesting_data(session, wallet_name, address):
    url = f"https://mainnet.prod.gd.midnighttge.io/thaws/{address}/schedule"
    
    # Headers สำคัญมาก ห้ามเอาออก
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
                # 404 แปลว่ากระเป๋าเปล่า แต่ไม่ Error
                return {"wallet": wallet_name, "address": address, "data": {"thaws": []}, "status": "ok"}
            else:
                return {"wallet": wallet_name, "address": address, "status": "error"}
    except:
        return {"wallet": wallet_name, "address": address, "status": "fail"}

# --- Function: Loop Update ---
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
st.title("🌙 NIGHT Tracker (Official + Alerts)")

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
                
                # บันทึกไฟล์
                save_data = {"updated_at": datetime.now().isoformat(), "wallets": raw_data}
                with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=4)
                
                st.success("✅ อัปเดตเสร็จสิ้น!")
                st.rerun()

# ตรวจสอบว่ามีไฟล์ Cache ไหม
if not os.path.exists(CACHE_FILE):
    st.warning("⚠️ ไม่พบข้อมูลเก่า: กรุณากดปุ่ม **'🔄 ดึงข้อมูลใหม่'** ที่มุมขวาบนเพื่อเริ่มระบบครับ")
else:
    # โหลดข้อมูล
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    
    # ดึงราคา
    with st.spinner("..เช็คราคา.."):
        p_usd, p_thb = get_market_price()

    # --- คำนวณยอดรวม (Summary) ---
    grand_redeemable = 0
    grand_left = 0
    grand_total = 0
    urgent_list = []

    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            
            for t in thaws:
                amt = t['amount'] / 1_000_000
                tx_id = t.get('transaction_id')
                info = process_claim_status(t['thawing_period_start'], tx_id)
                
                grand_total += amt
                if info['status'] == 'ready': 
                    grand_redeemable += amt
                if info['status'] != 'redeemed':
                    grand_left += amt
                
                # เก็บรายการแจ้งเตือน
                if info['urgent']:
                    urgent_list.append({
                        "Wallet": w_name,
                        "Amount": amt,
                        "Value (THB)": amt * p_thb,
                        "Status": info['text'],
                        "Date": info['date'].strftime('%d/%m/%Y'),
                        "_sort": info['sort']
                    })

    # --- 1. แจ้งเตือน (Alerts) ---
    if urgent_list:
        st.error(f"🚨 แจ้งเตือน: พบ {len(urgent_list)} รายการต้องเคลมด่วน!")
        df_urg = pd.DataFrame(urgent_list).sort_values("_sort").drop(columns=["_sort"])
        st.dataframe(
            df_urg.style.format({"Amount": "{:,.2f}", "Value (THB)": "฿{:,.2f}"})
            .map(lambda x: "color: green; font-weight: bold" if "🟣" in str(x) else "color: red", subset=["Status"]),
            use_container_width=True, hide_index=True
        )
    else:
        st.success("✅ ไม่มีรายการด่วน (ภายใน 7 วัน)")

    # --- 2. ภาพรวม (Metrics) ---
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.metric("🟣 Redeemable Now (พร้อมถอน)", f"{grand_redeemable:,.2f}", f"฿{grand_redeemable*p_thb:,.2f}")
    m2.metric("⏳ Total Left (เหลือ)", f"{grand_left:,.2f}", f"฿{grand_left*p_thb:,.2f}")
    m3.metric("📦 Total Allocation (ทั้งหมด)", f"{grand_total:,.2f}", f"฿{grand_total*p_thb:,.2f}")

    # --- 3. รายละเอียดรายกระเป๋า (Official Cards) ---
    st.markdown("### 💼 รายละเอียดรายกระเป๋า")
    
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            
            # ตัวแปรประจำกระเป๋า
            w_alloc = 0
            w_redeemed = 0
            w_left = 0
            w_ready = 0
            
            claims_data = []
            
            # นับจำนวนงวด
            total_thaws_count = len(thaws)
            redeemed_count = 0
            next_unlock = None

            for t in thaws:
                tx_id = t.get('transaction_id')
                info = process_claim_status(t['thawing_period_start'], tx_id)
                amt = t['amount'] / 1_000_000
                
                w_alloc += amt
                
                if info['status'] == 'redeemed':
                    w_redeemed += amt
                    redeemed_count += 1
                else:
                    w_left += amt
                    if info['status'] == 'ready':
                        w_ready += amt
                    elif info['status'] == 'locked':
                        # หาวันที่ปลดล็อคถัดไป
                        if next_unlock is None or (info['date'] and info['date'] < next_unlock):
                            next_unlock = info['date']

                claims_data.append({
                    "Date": info['date'].strftime('%d/%m/%Y') if info['date'] else "-",
                    "Amount": amt,
                    "Status": info['text'],
                    "_sort": info['sort']
                })
            
            # คำนวณงวดปัจจุบัน (เช่น 2/4)
            current_thaw = redeemed_count + 1
            if current_thaw > total_thaws_count: current_thaw = total_thaws_count
            
            # ข้อความนับถอยหลัง
            countdown_msg = "Completed"
            if w_ready > 0: countdown_msg = "Available Now!"
            elif next_unlock:
                diff = next_unlock - (datetime.utcnow() + timedelta(hours=7))
                d = diff.days
                h = diff.seconds // 3600
                countdown_msg = f"Thaws in: {d}d {h}h"

            # --- RENDER CARD ---
            with st.expander(f"🔹 {w_name} | พร้อมถอน: {w_ready:,.2f}", expanded=True):
                
                # Header
                st.markdown(f"""
                <div class="thaw-header">
                    <span>Current thaw: {current_thaw}/{total_thaws_count}</span>
                    <span style="font-size:0.9em; color:#555;">{countdown_msg}</span>
                </div>
                """, unsafe_allow_html=True)
                
                # Body
                st.markdown('<div class="card-body">', unsafe_allow_html=True)
                
                # Purple Box
                sub_text = f"≈ ฿{w_ready * p_thb:,.2f}" if w_ready > 0 else "Tokens become available after current thaw"
                st.markdown(f"""
                <div class="purple-box">
                    <small>Redeemable now:</small>
                    <h2>{w_ready:,.2f} NIGHT</h2>
                    <small>{sub_text}</small>
                </div>
                """, unsafe_allow_html=True)
                
                # 3 Lines Summary
                st.markdown(f"""
                <div class="detail-row"><span class="detail-label">Redeemed so far:</span> <span class="detail-val">{w_redeemed:,.2f}</span></div>
                <div class="detail-row"><span class="detail-label">Total left to redeem:</span> <span class="detail-val">{w_left:,.2f}</span></div>
                <div class="detail-row"><span class="detail-label">Total allocation size:</span> <span class="detail-val">{w_alloc:,.2f}</span></div>
                </div>
                """, unsafe_allow_html=True)
                
                # Table
                st.caption("📄 Transaction Details:")
                df_table = pd.DataFrame(claims_data).sort_values("_sort")
                
                def color_table(val):
                    if "✅" in str(val): return 'color: green'
                    if "🟣" in str(val): return 'color: purple; font-weight: bold'
                    return 'color: gray'

                st.dataframe(
                    df_table[['Date', 'Amount', 'Status']].style.applymap(color_table, subset=['Status']),
                    use_container_width=True, hide_index=True
                )
