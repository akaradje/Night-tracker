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

st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa; border: 1px solid #dee2e6;
        padding: 15px; border-radius: 10px; margin-bottom: 20px; text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .redeemed-card { background-color: #e9ecef; color: #495057; border: 1px solid #ced4da; }
    .remaining-card { background-color: #d1e7dd; color: #0f5132; border: 1px solid #badbcc; }
    .total-card { background-color: #cff4fc; color: #055160; border: 1px solid #b6effb; }
    .stDataFrame { font-size: 14px; }
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

# --- Function: คำนวณเวลาและสถานะ ---
def process_claim_status(iso_str, tx_id):
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        days = total_seconds // 86400
        
        # Logic การแยกสถานะ
        # 1. ถ้ามี Tx ID = เคลมไปแล้ว (Redeemed)
        if tx_id is not None and len(str(tx_id)) > 5:
             return {"text": "✅ เคลมแล้ว", "type": "redeemed", "date": dt_thai, "sort": 999999}
        
        # 2. ถ้าไม่มี Tx ID -> เช็คเวลา
        if total_seconds <= 0:
            return {"text": "🟢 พร้อมถอน", "type": "ready", "date": dt_thai, "sort": -999999}
        else:
            return {"text": f"🔒 รอ {days} วัน", "type": "locked", "date": dt_thai, "sort": total_seconds}
            
    except:
        return {"text": "-", "type": "unknown", "date": None, "sort": 999999}

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
st.title("🌙 NIGHT Tracker: รายงานสถานะตามจริง")

col_top1, col_top2 = st.columns([3, 1])

# โหลดไฟล์กระเป๋า
df_input = None
if os.path.exists('wallets.xlsx'): df_input = pd.read_excel('wallets.xlsx')
elif os.path.exists('active_wallets.csv'): df_input = pd.read_csv('active_wallets.csv')

# ปุ่มอัปเดต
with col_top2:
    if df_input is not None:
        if st.button("🔄 ดึงข้อมูลใหม่ (Update)", type="secondary", use_container_width=True):
            with st.spinner("⏳ กำลังโหลดจาก Blockchain..."):
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

    # ตัวแปรสรุปยอดรวมทั้งพอร์ต
    grand_redeemed = 0
    grand_remaining = 0
    grand_total = 0
    
    wallets_data = {}
    
    # Loop คำนวณ
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            
            # ยอดรายกระเป๋า
            w_redeemed = 0
            w_remaining = 0
            w_total = 0
            
            claims_list = []
            
            for t in thaws:
                tx_id = t.get('transaction_id') # จุดสำคัญ: เช็ค Tx ID
                status_info = process_claim_status(t['thawing_period_start'], tx_id)
                amt = t['amount'] / 1_000_000
                
                # บวกยอดรวม
                w_total += amt
                if status_info['type'] == 'redeemed':
                    w_redeemed += amt
                else:
                    w_remaining += amt
                
                claims_list.append({
                    "date": status_info['date'].strftime('%d/%m/%Y') if status_info['date'] else "-",
                    "amount": amt,
                    "status": status_info['text'],
                    "type": status_info['type'],
                    "sort": status_info['sort']
                })

            # บวกเข้ายอดรวมใหญ่
            grand_redeemed += w_redeemed
            grand_remaining += w_remaining
            grand_total += w_total
            
            # เก็บข้อมูลไว้โชว์
            if w_total > 0:
                if w_name not in wallets_data: 
                    wallets_data[w_name] = {"redeemed": 0, "remaining": 0, "total": 0, "addrs": {}}
                
                wallets_data[w_name]["redeemed"] += w_redeemed
                wallets_data[w_name]["remaining"] += w_remaining
                wallets_data[w_name]["total"] += w_total
                
                wallets_data[w_name]["addrs"][addr] = {
                    "redeemed": w_redeemed,
                    "remaining": w_remaining,
                    "total": w_total,
                    "claims": claims_list
                }

    # --- 📊 แสดงผล Dashboard แบบ Official ---
    st.divider()
    
    # Row 1: Dashboard ใหญ่
    c1, c2, c3 = st.columns(3)
    
    # การ์ด 1: Redeemed (เคลมไปแล้ว)
    c1.markdown(f"""
    <div class="metric-card redeemed-card">
        <h5>✅ Redeemed so far</h5>
        <h2>{grand_redeemed:,.2f} NIGHT</h2>
        <small>ได้รับแล้ว: ฿{grand_redeemed * p_thb:,.2f}</small>
    </div>""", unsafe_allow_html=True)
    
    # การ์ด 2: Left to redeem (เหลือ)
    c2.markdown(f"""
    <div class="metric-card remaining-card">
        <h5>⏳ Total left to redeem</h5>
        <h2>{grand_remaining:,.2f} NIGHT</h2>
        <small>รอเคลม: ฿{grand_remaining * p_thb:,.2f}</small>
    </div>""", unsafe_allow_html=True)
    
    # การ์ด 3: Total Allocation (ทั้งหมด)
    c3.markdown(f"""
    <div class="metric-card total-card">
        <h5>📦 Total allocation size</h5>
        <h2>{grand_total:,.2f} NIGHT</h2>
        <small>มูลค่ารวม: ฿{grand_total * p_thb:,.2f}</small>
    </div>""", unsafe_allow_html=True)

    # รายละเอียดรายกระเป๋า
    st.subheader("📂 รายละเอียดรายกระเป๋า")
    
    # เรียงตามยอดที่เหลือ (จะได้โฟกัสอันที่ยังไม่เคลม)
    sorted_wallets = sorted(wallets_data.items(), key=lambda x: x[1]['remaining'], reverse=True)
    
    for w_name, data in sorted_wallets:
        icon = "🟢" if data['remaining'] > 0 else "⚪"
        
        with st.expander(f"{icon} {w_name} | เหลือ: {data['remaining']:,.2f} | รับแล้ว: {data['redeemed']:,.2f} (รวม {data['total']:,.2f})"):
            for addr, info in data['addrs'].items():
                st.markdown(f"**Address:** `{addr}`")
                
                # ตารางสรุปย่อย
                c_a, c_b, c_c = st.columns(3)
                c_a.info(f"รับแล้ว: {info['redeemed']:,.2f}")
                c_b.success(f"เหลือ: {info['remaining']:,.2f}")
                c_c.write(f"รวม: {info['total']:,.2f}")
                
                # รายละเอียดงวด
                df_claims = pd.DataFrame(info['claims']).sort_values('sort')
                df_show = df_claims[['date', 'amount', 'status']]
                df_show.columns = ["วันที่", "จำนวน", "สถานะ"]
                
                # ไฮไลท์สีตามสถานะ
                def highlight_status(s):
                    if '✅' in s: return 'background-color: #e2e3e5; color: #6c757d' # เทา (จบแล้ว)
                    if '🟢' in s: return 'background-color: #d1e7dd; color: #0f5132' # เขียว (พร้อม)
                    return ''
                
                st.dataframe(
                    df_show.style.format({"จำนวน": "{:,.2f}"})
                    .map(highlight_status, subset=['สถานะ']),
                    use_container_width=True, hide_index=True
                )
                st.markdown("---")
