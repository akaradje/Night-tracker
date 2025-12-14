import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Smart Sort)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG & KEY
# ==============================================================================
CACHE_FILE = "vesting_data.json"  # ไฟล์สำหรับบันทึกข้อมูล
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f" # Contract NIGHT
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
REDEEM_URL = "https://redeem.midnight.gd/"
# ==============================================================================

# CSS Styling
st.markdown("""
<style>
    /* Metric Cards */
    .metric-card {
        background-color: #f8f9fa; border: 1px solid #dee2e6;
        padding: 20px; border-radius: 10px; margin-bottom: 20px; text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .price-card { background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
    .value-card { background-color: #d1e7dd; color: #0f5132; border: 1px solid #badbcc; }
    
    /* Official Card Style */
    .official-card-container {
        border: 1px solid #e0e0e0; border-radius: 12px; background-color: white; overflow: hidden;
        margin-top: 15px; margin-bottom: 15px;
    }
    .official-header {
        background-color: #f9fafb; padding: 15px 20px; border-bottom: 1px solid #e0e0e0;
        display: flex; justify-content: space-between; align-items: center; font-weight: 600; color: #111827;
    }
    .official-body { padding: 24px; }
    
    /* Purple Box */
    .purple-redeem-box {
        background-color: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 8px;
        padding: 20px; margin-bottom: 24px; text-align: center;
    }
    .purple-amount { font-size: 2em; font-weight: 700; color: #111827; margin: 10px 0; }
    .purple-sub { font-size: 0.9em; color: #6b7280; margin-bottom: 15px; }
    
    /* Details */
    .details-section { border-top: 1px solid #e5e7eb; padding-top: 20px; }
    .detail-row { display: flex; justify-content: space-between; padding: 8px 0; font-size: 0.95em; border-bottom: 1px solid #f3f4f6; }
    .detail-label { color: #4b5563; }
    .detail-value { font-weight: 600; color: #111827; }
    
    /* Button */
    .redeem-btn-active {
        display: block; width: 100%; text-align: center; background-color: #7c3aed; color: white !important;
        padding: 10px 0; border-radius: 6px; text-decoration: none; font-weight: 600; transition: background 0.2s;
    }
    .redeem-btn-active:hover { background-color: #6d28d9; }
    
    .redeem-btn-full {
        display: block; width: 100%; text-align: center; background-color: #d1d5db; color: #374151;
        padding: 10px 0; border-radius: 6px; text-decoration: none; font-weight: 600; cursor: not-allowed;
    }
    
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

# --- Function: คำนวณสถานะ (สำคัญ: กรอง Redeemed ออกจาก Urgent) ---
def process_claim_status(iso_str, tx_id):
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        # 1. มี Tx ID = เคลมแล้ว (Redeemed) -> Urgent = False แน่นอน
        if tx_id is not None and len(str(tx_id)) > 5:
             return {"text": "✅ เคลมแล้ว (Redeemed)", "status": "redeemed", "date": dt_thai, "sort": 999999, "urgent": False}
        
        # 2. เวลาผ่านไปแล้ว & ไม่มี Tx = พร้อมเคลม (Ready) -> Urgent = True
        if total_seconds <= 0:
            return {"text": "🟣 พร้อมถอน (Ready)", "status": "ready", "date": dt_thai, "sort": -999999, "urgent": True}
        
        # 3. ยังไม่ถึงเวลา = Locked
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
st.title("🌙 NIGHT Tracker (Smart Sort & Clean Alert)")

col_top1, col_top2 = st.columns([3, 1])

df_input = None
if os.path.exists('wallets.xlsx'): df_input = pd.read_excel('wallets.xlsx')
elif os.path.exists('active_wallets.csv'): df_input = pd.read_csv('active_wallets.csv')

with col_top2:
    if df_input is not None:
        if st.button("🔄 ดึงข้อมูลใหม่ (Update)", type="secondary", use_container_width=True):
            with st.spinner("⏳ กำลังเชื่อมต่อ Blockchain..."):
                raw_data = asyncio.run(update_database(df_input))
                save_data = {"updated_at": datetime.now().isoformat(), "wallets": raw_data}
                with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=4)
                st.success("✅ อัปเดตเสร็จสิ้น!")
                st.rerun()

if not os.path.exists(CACHE_FILE):
    st.info("👋 กดปุ่ม **'🔄 ดึงข้อมูลใหม่'** ด้านบนขวาเพื่อเริ่มใช้งานครับ")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    
    last_update = datetime.fromisoformat(cached.get("updated_at", "")).strftime("%d/%m/%Y %H:%M")
    with col_top1:
        st.caption(f"💾 อัปเดตล่าสุด: {last_update}")

    with st.spinner("..เช็คราคา.."):
        p_usd, p_thb = get_market_price()

    # --- Processing Grouping & Alerts ---
    grouped = {} 
    urgent_items = []
    
    grand_ready = 0
    grand_alloc = 0
    grand_left = 0

    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            w_name = item['wallet']
            addr = item['address']
            thaws = item['data'].get('thaws', [])
            
            if w_name not in grouped:
                grouped[w_name] = {
                    'alloc': 0, 'redeemed': 0, 'left': 0, 'ready': 0,
                    'addr_map': {}, # เก็บยอดแยกตาม Address เพื่อเอามาเรียงลำดับ
                    'history': [],
                    'total_thaws_count': 0, 'redeemed_thaws_count': 0,
                    'next_unlock': None
                }
            
            # เตรียมตัวแปรเก็บยอดราย Address นี้
            if addr not in grouped[w_name]['addr_map']:
                grouped[w_name]['addr_map'][addr] = {'ready': 0}

            for t in thaws:
                amt = t['amount'] / 1_000_000
                info = process_claim_status(t['thawing_period_start'], t.get('transaction_id'))
                
                # รวมยอด
                grouped[w_name]['alloc'] += amt
                grouped[w_name]['total_thaws_count'] += 1
                
                if info['status'] == 'redeemed':
                    grouped[w_name]['redeemed'] += amt
                    grouped[w_name]['redeemed_thaws_count'] += 1
                else:
                    grouped[w_name]['left'] += amt
                    if info['status'] == 'ready':
                        grouped[w_name]['ready'] += amt
                        grouped[w_name]['addr_map'][addr]['ready'] += amt # สะสมยอดพร้อมถอนราย Address
                    elif info['status'] == 'locked':
                        if grouped[w_name]['next_unlock'] is None or (info['date'] and info['date'] < grouped[w_name]['next_unlock']):
                            grouped[w_name]['next_unlock'] = info['date']
                
                # --- Alert Logic (แก้ใหม่: ห้ามเอา Redeemed มาใส่) ---
                # เช็ค info['urgent'] เป็น True และ status ต้องไม่ใช่ redeemed
                if info['urgent'] and info['status'] != 'redeemed':
                    urgent_items.append({
                        "Wallet": w_name, "Amount": amt, "Value (THB)": amt * p_thb,
                        "Status": info['text'], "_sort": info['sort']
                    })
                
                grouped[w_name]['history'].append({
                    "Date": info['date'].strftime('%d/%m/%Y') if info['date'] else "-",
                    "Amount": amt, "Status": info['text'], "_sort": info['sort'], "Address": addr
                })

    for data in grouped.values():
        grand_alloc += data['alloc']
        grand_ready += data['ready']
        grand_left += data['left']

    # --- Dashboard ---
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.markdown(f'<div class="metric-card"><h5>🟣 พร้อมถอน (Now)</h5><h2>{grand_ready:,.2f}</h2><small>฿{grand_ready*p_thb:,.2f}</small></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคา (Real-time)</h5><h2 style="color:#856404">฿{p_thb:,.4f}</h2><small>${p_usd:,.4f}</small></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card value-card"><h5>📦 มูลค่ารวม (บาท)</h5><h2>฿{grand_alloc * p_thb:,.2f}</h2></div>', unsafe_allow_html=True)

    # --- Alert Box (เฉพาะที่ยังไม่เคลม) ---
    if urgent_items:
        st.error(f"🚨 แจ้งเตือน: พบ {len(urgent_items)} รายการต้องเคลม (ภายใน 7 วัน)")
        df_urg = pd.DataFrame(urgent_items).sort_values("_sort").drop(columns=["_sort"])
        st.dataframe(
            df_urg.style.format({"Amount": "{:,.2f}", "Value (THB)": "฿{:,.2f}"})
            .map(lambda x: "background-color: #d4edda" if "🟣" in str(x) else "color: red", subset=["Status"]),
            use_container_width=True, hide_index=True
        )

    # --- Details ---
    st.subheader("📂 รายละเอียดกระเป๋า")
    
    # เรียงกระเป๋าตามยอดพร้อมถอน
    sorted_wallets = sorted(grouped.items(), key=lambda x: x[1]['ready'], reverse=True)
    
    for w_name, data in sorted_wallets:
        w_ready = data['ready']
        price_val = w_ready * p_thb
        icon = "🟢" if w_ready > 0 else "⚪"
        
        # Countdown logic
        addr_count = len(data['addr_map']) if len(data['addr_map']) > 0 else 1
        curr_thaw = int(data['redeemed_thaws_count'] / addr_count) + 1
        total_thaws = int(data['total_thaws_count'] / addr_count)
        if curr_thaw > total_thaws: curr_thaw = total_thaws

        countdown = "Completed"
        if w_ready > 0: countdown = "Available Now!"
        elif data['next_unlock']:
            diff = data['next_unlock'] - (datetime.utcnow()+timedelta(hours=7))
            countdown = f"Thaws in: {diff.days}d {diff.seconds//3600}h"
            
        btn_class = "redeem-btn-active" if w_ready > 0 else "redeem-btn-full"
        btn_text = "Redeem" if w_ready > 0 else "No tokens available"
        purple_sub = f"≈ ฿{price_val:,.2f}" if w_ready > 0 else "NIGHT tokens become available after current thaw"
        
        # HTML Card
        html_card = f"""
        <div class="official-card-container">
            <div class="official-header">
                <div>Current thaw: {curr_thaw}/{total_thaws}</div>
                <div style="font-size:0.9em; color:#6b7280;">{countdown}</div>
            </div>
            <div class="official-body">
                <div class="purple-redeem-box">
                    <div class="purple-label" style="justify-content:center;">Redeemable now</div>
                    <div class="purple-amount">{w_ready:,.2f} NIGHT</div>
                    <div class="purple-sub">{purple_sub}</div>
                    <a href="{REDEEM_URL}" target="_blank" class="{btn_class}">{btn_text}</a>
                </div>
                <div class="details-section">
                    <div class="detail-row"><span class="detail-label">Redeemed so far:</span> <span class="detail-value">{data['redeemed']:,.2f} NIGHT</span></div>
                    <div class="detail-row"><span class="detail-label">Total left to redeem:</span> <span class="detail-value">{data['left']:,.2f} NIGHT</span></div>
                    <div class="detail-row"><span class="detail-label">Total allocation size:</span> <span class="detail-value">{data['alloc']:,.2f} NIGHT</span></div>
                </div>
            </div>
        </div>
        """

        # EXPANDER
        with st.expander(f"{icon} {w_name} | พร้อมถอน: {w_ready:,.2f} NIGHT (฿{price_val:,.0f})", expanded=False):
            
            # --- Address Sorting Logic (จัดเรียง Address) ---
            # เรียง Address ตามยอด ready (มากไปน้อย) เพื่อให้ตัวที่เคลมได้อยู่บนสุด
            sorted_addrs = sorted(data['addr_map'].items(), key=lambda x: x[1]['ready'], reverse=True)
            
            st.markdown(f"**Addresses ({len(sorted_addrs)}):**")
            for addr, stats in sorted_addrs:
                ready_amt = stats['ready']
                # ใส่ icon หน้า address ถ้ามีเงินพร้อมเคลม
                addr_icon = "🟣" if ready_amt > 0 else "⚪"
                ready_text = f" (Ready: {ready_amt:,.2f})" if ready_amt > 0 else ""
                st.code(f"{addr_icon} {addr}{ready_text}")

            st.markdown(html_card, unsafe_allow_html=True)
            
            st.caption("Transactions History:")
            df_hist = pd.DataFrame(data['history']).sort_values("_sort")
            def color_status(val):
                if "✅" in str(val): return 'color: green'
                if "🟣" in str(val): return 'color: purple; font-weight: bold'
                return 'color: gray'
            st.dataframe(df_hist[['Date', 'Amount', 'Status', 'Address']].style.applymap(color_status, subset=['Status']), use_container_width=True, hide_index=True)
