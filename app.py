import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Final)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG & KEY
# ==============================================================================
CACHE_FILE = "vesting_data.json"  # ไฟล์สำหรับบันทึกข้อมูล
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f" # Contract NIGHT
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
REDEEM_URL = "https://redeem.midnight.gd/"
# ==============================================================================

# CSS แต่งสวย (Official Style)
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa; border: 1px solid #dee2e6;
        padding: 20px; border-radius: 10px; margin-bottom: 20px; text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .price-card { background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
    .value-card { background-color: #d1e7dd; color: #0f5132; border: 1px solid #badbcc; }
    .redeemed-card { background-color: #e2e3e5; color: #383d41; border: 1px solid #d6d8db; }
    .stAlert {margin-top: 10px;}
    .update-btn { margin-bottom: 20px; }
    
    /* Official Card CSS */
    .official-card-container {
        border: 1px solid #e0e0e0; border-radius: 12px; background-color: white; 
        overflow: hidden; margin-top: 10px; margin-bottom: 10px;
    }
    .thaw-header {
        background-color: #f8f9fa; padding: 12px 16px; 
        font-weight: 600; color: #333; display: flex; justify-content: space-between; align-items: center;
        border-bottom: 1px solid #e0e0e0;
    }
    .card-body { padding: 20px; }
    .purple-box {
        background-color: #f3f0ff; border: 1px solid #dcd0ff; border-radius: 8px;
        padding: 15px; color: #5b4da8; margin-bottom: 15px; text-align: center;
    }
    .purple-box h2 { margin: 0; padding: 5px 0; font-size: 2em; font-weight: 700; color: #4a3b89; }
    .detail-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #f5f5f5; font-size: 0.9em; }
    
    /* Button */
    .redeem-btn {
        display: inline-block; width: 100%; text-align: center;
        background-color: #6f42c1; color: white !important; padding: 10px; 
        border-radius: 6px; text-decoration: none; font-weight: bold; margin-top: 10px;
        transition: background 0.3s;
    }
    .redeem-btn:hover { background-color: #5a32a3; }
</style>
""", unsafe_allow_html=True)

# --- Function: ดึงราคา (Real-time) ---
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
def process_claim_time(iso_str, tx_id):
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        # 1. เช็คว่าเคลมแล้วหรือยัง (มี Tx ID)
        if tx_id is not None and len(str(tx_id)) > 5:
             return {"text": "✅ เคลมแล้ว", "status": "redeemed", "date": dt_thai, "sort": 999999, "urgent": False}

        # 2. เช็คเวลา (พร้อมเคลม)
        if total_seconds <= 0:
            return {"text": "🟣 พร้อมเคลม (Ready)", "status": "ready", "date": dt_thai, "sort": -999999, "urgent": True}
        
        # 3. ยังไม่ถึงเวลา
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        countdown = f"{days}วัน {hours}ชม."
        
        status = "urgent" if days <= 7 else "wait"
        urgent = True if days <= 7 else False
        icon = "🔥" if days <= 7 else "⏳"
        
        return {"text": f"{icon} {countdown}", "status": "locked", "date": dt_thai, "sort": total_seconds, "urgent": urgent}
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
            progress = (i + 1) / len(tasks)
            progress_bar.progress(progress)
            status_text.text(f"📥 กำลังโหลดข้อมูล... {i+1}/{len(tasks)}")
        progress_bar.empty()
        status_text.empty()
    return results

# ==============================================================================
# MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker (Final)")

col_top1, col_top2 = st.columns([3, 1])

# โหลดไฟล์
df_input = None
if os.path.exists('wallets.xlsx'): df_input = pd.read_excel('wallets.xlsx')
elif os.path.exists('active_wallets.csv'): df_input = pd.read_csv('active_wallets.csv')

# ปุ่มอัปเดต
with col_top2:
    if df_input is not None:
        if st.button("🔄 ดึงข้อมูลใหม่ (Update)", type="secondary", use_container_width=True):
            if df_input is not None:
                with st.spinner("⏳ กำลังเชื่อมต่อ Blockchain..."):
                    raw_data = asyncio.run(update_database(df_input))
                    save_data = {"updated_at": datetime.now().isoformat(), "wallets": raw_data}
                    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                        json.dump(save_data, f, ensure_ascii=False, indent=4)
                    st.success("✅ อัปเดตข้อมูลเรียบร้อย!")
                    st.rerun()

if not os.path.exists(CACHE_FILE):
    st.info("👋 ยินดีต้อนรับ! กรุณากดปุ่ม **'🔄 ดึงข้อมูลใหม่'** ด้านบนขวา เพื่อเริ่มใช้งาน")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    
    last_update = datetime.fromisoformat(cached.get("updated_at", "")).strftime("%d/%m/%Y %H:%M")
    with col_top1:
        st.caption(f"💾 อัปเดตล่าสุด: **{last_update}**")

    # ดึงราคา
    with st.spinner("..เช็คราคาตลาด.."):
        p_usd, p_thb = get_market_price()

    # --- Processing Data ---
    grouped_wallets = {}
    urgent_items = []
    
    grand_alloc = 0
    grand_ready = 0
    grand_left = 0
    grand_redeemed = 0

    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            w_name = item['wallet']
            addr = item['address']
            thaws = item['data'].get('thaws', [])
            
            if w_name not in grouped_wallets:
                grouped_wallets[w_name] = {
                    'alloc': 0, 'redeemed': 0, 'left': 0, 'ready': 0,
                    'addresses': [], 'history': [],
                    'total_thaws': 0, 'redeemed_thaws': 0, 'next_unlock': None
                }
            
            for t in thaws:
                amt = t['amount'] / 1_000_000
                info = process_claim_time(t['thawing_period_start'], t.get('transaction_id'))
                
                # สะสมยอด
                grouped_wallets[w_name]['alloc'] += amt
                grouped_wallets[w_name]['total_thaws'] += 1
                
                if info['status'] == 'redeemed':
                    grouped_wallets[w_name]['redeemed'] += amt
                    grouped_wallets[w_name]['redeemed_thaws'] += 1
                else:
                    grouped_wallets[w_name]['left'] += amt
                    if info['status'] == 'ready':
                        grouped_wallets[w_name]['ready'] += amt
                    elif info['status'] == 'locked':
                        curr_next = grouped_wallets[w_name]['next_unlock']
                        if curr_next is None or (info['date'] and info['date'] < curr_next):
                            grouped_wallets[w_name]['next_unlock'] = info['date']
                
                # Alerts (เฉพาะที่ยังไม่เคลม)
                if info['urgent'] and info['status'] != 'redeemed':
                    urgent_items.append({
                        "Wallet": w_name, "Amount": amt, "Value (THB)": amt * p_thb,
                        "Status": info['text'], "_sort": info['sort']
                    })
                
                grouped_wallets[w_name]['history'].append({
                    "Date": info['date'].strftime('%d/%m/%Y') if info['date'] else "-",
                    "Amount": amt, "Status": info['text'], "_sort": info['sort'], "Address": addr
                })
            
            grouped_wallets[w_name]['addresses'].append(addr)

    # Grand Totals
    for data in grouped_wallets.values():
        grand_alloc += data['alloc']
        grand_ready += data['ready']
        grand_left += data['left']
        grand_redeemed += data['redeemed']

    # --- Metrics Cards ---
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    
    # 1. ยอดทั้งหมด
    m1.markdown(f'<div class="metric-card"><h5>📦 NIGHT ทั้งหมด (Alloc)</h5><h2>{grand_alloc:,.2f}</h2></div>', unsafe_allow_html=True)
    
    # 2. ราคา (เอากลับมาแล้ว!)
    m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคา (Real-time)</h5><h2 style="color:#856404">฿{p_thb:,.4f}</h2><small>${p_usd:,.4f}</small></div>', unsafe_allow_html=True)
    
    # 3. มูลค่ารวม (บาท)
    val_total = grand_alloc * p_thb
    m3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่ารวม (บาท)</h5><h2>฿{val_total:,.2f}</h2></div>', unsafe_allow_html=True)
    
    # 4. ยอดที่เหลือ
    m4.markdown(f'<div class="metric-card"><h5>⏳ NIGHT ที่เหลือ</h5><h2>{grand_left:,.2f}</h2></div>', unsafe_allow_html=True)

    # --- Alert Box ---
    if urgent_items:
        st.error(f"🚨 แจ้งเตือน: พบ {len(urgent_items)} รายการต้องเคลม (ภายใน 7 วัน)")
        df_urg = pd.DataFrame(urgent_items).sort_values("_sort").drop(columns=["_sort"])
        st.dataframe(
            df_urg,
            column_config={
                "Amount": st.column_config.NumberColumn("Amount", format="%.2f"),
                "Value (THB)": st.column_config.NumberColumn("Value (THB)", format="฿%.2f"),
                "Link": st.column_config.LinkColumn("Action", display_text="🚀 กดเคลม", default_value=REDEEM_URL)
            },
            hide_index=True, use_container_width=True
        )

    # --- Wallet Details (Grouped & Official UI) ---
    st.subheader("📂 รายละเอียดกระเป๋า (จากข้อมูลที่บันทึกไว้)")
    
    for w_name, data in sorted(grouped_wallets.items(), key=lambda x: x[1]['ready'], reverse=True):
        val_ready = data['ready'] * p_thb
        val_total_wallet = data['alloc'] * p_thb
        icon = "🟢" if data['ready'] > 0 else "⚪"
        
        # Countdown
        countdown = "Completed"
        if data['ready'] > 0: countdown = "Available Now!"
        elif data['next_unlock']:
            diff = data['next_unlock'] - (datetime.utcnow()+timedelta(hours=7))
            countdown = f"Thaws in: {diff.days} days"
            
        # Thaw Count (Approx)
        addr_count = len(data['addresses']) if len(data['addresses']) > 0 else 1
        curr_thaw = int(data['redeemed_thaws'] / addr_count) + 1
        total_thaws_avg = int(data['total_thaws'] / addr_count)
        if curr_thaw > total_thaws_avg: curr_thaw = total_thaws_avg

        with st.expander(f"{icon} {w_name} | พร้อมถอน: {data['ready']:,.2f} (฿{val_ready:,.0f}) | รวม: {data['alloc']:,.2f} (฿{val_total_wallet:,.0f})"):
            
            # Official Card
            st.markdown(f"""
            <div class="official-card-container">
                <div class="thaw-header">
                    <span>Current thaw: ~{curr_thaw}/{total_thaws_avg}</span>
                    <span style="font-size:0.9em; color:#555;">{countdown}</span>
                </div>
                <div class="card-body">
                    <div class="purple-box">
                        <small>Redeemable now:</small>
                        <h2>{data['ready']:,.2f} NIGHT</h2>
                        <small>≈ ฿{val_ready:,.2f}</small>
                        <br>
                        <a href="{REDEEM_URL}" target="_blank" class="redeem-btn">👉 ไปที่หน้ากดเคลม (Redeem Site)</a>
                    </div>
                    <div class="detail-row"><span style="color:#666">Redeemed so far:</span> <span style="font-weight:bold">{data['redeemed']:,.2f} NIGHT</span></div>
                    <div class="detail-row"><span style="color:#666">Total left to redeem:</span> <span style="font-weight:bold">{data['left']:,.2f} NIGHT</span></div>
                    <div class="detail-row"><span style="color:#666">Total allocation size:</span> <span style="font-weight:bold">{data['alloc']:,.2f} NIGHT</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            st.caption("Transactions History:")
            df_hist = pd.DataFrame(data['history']).sort_values("_sort")
            def color_row(val):
                if "✅" in str(val): return 'color: green'
                if "🟣" in str(val): return 'color: purple; font-weight: bold'
                return 'color: gray'
            st.dataframe(df_hist[['Date', 'Amount', 'Status', 'Address']].style.applymap(color_row, subset=['Status']), use_container_width=True, hide_index=True)
