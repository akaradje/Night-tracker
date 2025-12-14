import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Complete)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG & KEY
# ==============================================================================
CACHE_FILE = "vesting_data.json"
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f"
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
REDEEM_URL = "https://redeem.midnight.gd/"
# ==============================================================================

# CSS Styling
st.markdown("""
<style>
    /* Card Style like Official */
    .card-container {
        border: 1px solid #e0e0e0; border-radius: 12px; margin-bottom: 20px;
        background-color: white; overflow: hidden;
    }
    .thaw-header {
        background-color: #f8f9fa; padding: 12px 16px; 
        font-weight: 600; color: #333; display: flex; justify-content: space-between; align-items: center;
        border-bottom: 1px solid #e0e0e0;
    }
    .card-body { padding: 20px; }
    
    /* Purple Box */
    .purple-box {
        background-color: #f3f0ff; border: 1px solid #dcd0ff; border-radius: 8px;
        padding: 15px; color: #5b4da8; margin-bottom: 15px; text-align: center;
    }
    .purple-box h2 { margin: 0; padding: 5px 0; font-size: 2em; font-weight: 700; color: #4a3b89; }
    
    /* Stats Details */
    .detail-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.9em; }
    .detail-label { color: #666; }
    .detail-val { font-weight: 600; color: #333; }
    
    /* Buttons & Links */
    .redeem-link {
        display: inline-block; width: 100%; text-align: center;
        background-color: #6f42c1; color: white !important; padding: 8px; 
        border-radius: 6px; text-decoration: none; font-weight: bold; margin-top: 10px;
    }
    .redeem-link:hover { background-color: #5a32a3; }

    /* Alert Box */
    .stAlert { margin-top: 10px; margin-bottom: 20px; }
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
        
        if tx_id is not None and len(str(tx_id)) > 5:
             return {"text": "✅ Redeemed", "status": "redeemed", "date": dt_thai, "sort": 999999, "urgent": False}
        
        if total_seconds <= 0:
            return {"text": "🟣 Redeemable Now", "status": "ready", "date": dt_thai, "sort": -999999, "urgent": True}
        
        else:
            days = total_seconds // 86400
            urgent = True if days <= 7 else False
            return {"text": f"🔒 Locked ({days}d)", "status": "locked", "date": dt_thai, "sort": total_seconds, "urgent": urgent}
            
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
            else:
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
st.title("🌙 NIGHT Tracker (Complete)")

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
                st.success("✅ อัปเดตเสร็จสิ้น!")
                st.rerun()

if not os.path.exists(CACHE_FILE):
    st.warning("⚠️ ไม่พบข้อมูล: กรุณากดปุ่ม **'🔄 ดึงข้อมูลใหม่'** ที่มุมขวาบน 1 ครั้ง")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    
    # ดึงราคา
    with st.spinner("..เช็คราคา.."):
        p_usd, p_thb = get_market_price()

    # --- ส่วนคำนวณ Global ---
    grand_redeemable = 0
    grand_left = 0
    grand_total = 0
    urgent_list = []

    # วนลูปเพื่อคำนวณยอดรวมและหา Alert
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            for t in thaws:
                amt = t['amount'] / 1_000_000
                info = process_claim_status(t['thawing_period_start'], t.get('transaction_id'))
                
                grand_total += amt
                if info['status'] == 'ready': grand_redeemable += amt
                if info['status'] != 'redeemed': grand_left += amt
                
                if info['urgent']:
                    urgent_list.append({
                        "Wallet": w_name,
                        "Address": addr,
                        "Amount": amt,
                        "Value (THB)": amt * p_thb,
                        "Status": info['text'],
                        "Date": info['date'].strftime('%d/%m') if info['date'] else "-",
                        "_sort": info['sort']
                    })

    # --- 1. Metrics ด้านบน (ยอดรวม) ---
    m1, m2, m3 = st.columns(3)
    m1.metric("🟣 พร้อมถอน (Now)", f"{grand_redeemable:,.2f}", f"฿{grand_redeemable*p_thb:,.2f}")
    m2.metric("⏳ เหลือ (Left)", f"{grand_left:,.2f}", f"฿{grand_left*p_thb:,.2f}")
    m3.metric("📦 ทั้งหมด (Alloc)", f"{grand_total:,.2f}", f"฿{grand_total*p_thb:,.2f}")

    # --- 2. Alert Box (สีแดง) ---
    if urgent_list:
        st.error(f"🚨 แจ้งเตือนด่วน: พบ {len(urgent_list)} รายการต้องเคลม (ภายใน 7 วัน)")
        df_urg = pd.DataFrame(urgent_list).sort_values("_sort").drop(columns=["_sort"])
        st.dataframe(
            df_urg.style.format({"Amount": "{:,.2f}", "Value (THB)": "฿{:,.2f}"})
            .map(lambda x: "color: green; font-weight: bold" if "🟣" in str(x) else "color: red", subset=["Status"]),
            use_container_width=True, hide_index=True
        )

    st.divider()

    # --- 3. รายละเอียดกระเป๋า (Accordion Style) ---
    st.subheader("📂 รายละเอียดรายกระเป๋า (จากข้อมูลที่บันทึกไว้)")
    
    # วนลูปแสดงกระเป๋า (ซ่อนรายละเอียดไว้ใน Expander)
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            w_name = item['wallet']
            address = item['address']
            thaws = item['data'].get('thaws', [])
            
            # คำนวณยอดเฉพาะกระเป๋านี้
            w_redeemable = sum(t['amount']/1000000 for t in thaws if process_claim_status(t['thawing_period_start'], t.get('transaction_id'))['status'] == 'ready')
            w_total_left = sum(t['amount']/1000000 for t in thaws if process_claim_status(t['thawing_period_start'], t.get('transaction_id'))['status'] != 'redeemed')
            
            # ไอคอนสถานะหน้าชื่อกระเป๋า
            status_icon = "🟢" if w_redeemable > 0 else "⚪"
            
            # >>> EXPANDER: กดเพื่อดูไส้ใน <<<
            with st.expander(f"{status_icon} {w_name} | พร้อมถอน: {w_redeemable:,.2f} NIGHT (฿{w_redeemable*p_thb:,.0f})", expanded=False):
                
                # แสดง Address และ Card แบบ Official ข้างในนี้
                st.markdown(f"**Address:** `{address}`")
                
                # --- สร้าง Card Official ---
                total_thaws = len(thaws)
                redeemed_count = 0
                w_redeemed = 0
                w_alloc = 0
                claims_data = []
                next_date = None

                for t in thaws:
                    amt = t['amount'] / 1_000_000
                    w_alloc += amt
                    info = process_claim_status(t['thawing_period_start'], t.get('transaction_id'))
                    
                    if info['status'] == 'redeemed':
                        w_redeemed += amt
                        redeemed_count += 1
                    elif info['status'] == 'locked':
                        if next_date is None or (info['date'] and info['date'] < next_date):
                            next_date = info['date']
                    
                    claims_data.append({"Date": info['date'].strftime('%d/%m/%Y') if info['date'] else "-", "Amount": amt, "Status": info['text'], "_sort": info['sort']})

                curr_thaw = min(redeemed_count + 1, total_thaws)
                countdown = "Available Now!" if w_redeemable > 0 else f"Thaws in: {(next_date - (datetime.utcnow()+timedelta(hours=7))).days} days" if next_date else "Completed"
                
                # HTML Card Structure
                st.markdown(f"""
                <div class="card-container">
                    <div class="thaw-header">
                        <span>Current thaw: {curr_thaw}/{total_thaws}</span>
                        <span style="font-size:0.9em; color:#555;">{countdown}</span>
                    </div>
                    <div class="card-body">
                        <div class="purple-box">
                            <small>Redeemable now:</small>
                            <h2>{w_redeemable:,.2f} NIGHT</h2>
                            <small>≈ ฿{w_redeemable * p_thb:,.2f}</small>
                            <br>
                            <a href="{REDEEM_URL}" target="_blank" class="redeem-link">👉 ไปที่หน้ากดเคลม (Redeem Site)</a>
                        </div>
                        <div class="detail-row"><span class="detail-label">Redeemed so far:</span> <span class="detail-val">{w_redeemed:,.2f}</span></div>
                        <div class="detail-row"><span class="detail-label">Total left to redeem:</span> <span class="detail-val">{w_total_left:,.2f}</span></div>
                        <div class="detail-row"><span class="detail-label">Total allocation size:</span> <span class="detail-val">{w_alloc:,.2f}</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Table Data
                st.caption("Transactions:")
                df_show = pd.DataFrame(claims_data).sort_values("_sort")
                def color_row(val):
                    if "✅" in str(val): return 'color: green'
                    if "🟣" in str(val): return 'color: purple; font-weight: bold'
                    return 'color: gray'
                st.dataframe(df_show[['Date', 'Amount', 'Status']].style.applymap(color_row, subset=['Status']), use_container_width=True, hide_index=True)
