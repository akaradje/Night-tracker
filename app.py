import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Full History)", page_icon="🌙", layout="wide")

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
    /* Metric Cards */
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
    
    /* Official Card Container */
    .official-card-container {
        border: 1px solid #e0e0e0; 
        border-radius: 12px; 
        background-color: white; 
        overflow: hidden;
        margin-top: 15px; margin-bottom: 15px;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    .official-header {
        background-color: #f9fafb; padding: 15px 20px; border-bottom: 1px solid #e0e0e0;
        display: flex; justify-content: space-between; align-items: center;
        font-weight: 600; color: #111827;
    }
    .official-body { padding: 24px; }
    
    /* Purple Redeem Box */
    .purple-redeem-box {
        background-color: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 8px;
        padding: 20px; margin-bottom: 24px; text-align: center;
    }
    .purple-label { color: #4b5563; font-size: 0.9em; display: flex; justify-content: center; }
    .purple-amount { font-size: 2em; font-weight: 700; color: #111827; margin: 10px 0; }
    .purple-sub { font-size: 0.9em; color: #6b7280; margin-bottom: 15px; }
    
    /* Details Section */
    .details-section { border-top: 1px solid #e5e7eb; padding-top: 20px; }
    .detail-row { display: flex; justify-content: space-between; padding: 8px 0; font-size: 0.95em; border-bottom: 1px solid #f3f4f6; }
    .detail-label { color: #4b5563; }
    .detail-value { font-weight: 600; color: #111827; }
    
    /* Custom Button */
    .redeem-btn-active {
        display: block; width: 100%; text-align: center; background-color: #7c3aed; color: white !important;
        padding: 10px 0; border-radius: 6px; text-decoration: none; font-weight: 600; transition: background 0.2s;
    }
    .redeem-btn-active:hover { background-color: #6d28d9; }
    
    .redeem-btn-full {
        display: block; width: 100%; text-align: center; background-color: #d1d5db; color: #374151;
        padding: 10px 0; border-radius: 6px; text-decoration: none; font-weight: 600; cursor: not-allowed;
    }
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

# --- Function: คำนวณเวลาและสถานะ (สำคัญ: แยก Redeemed) ---
def process_claim_time(iso_str, tx_id):
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        # 1. มี Transaction ID = เคลมแล้ว
        if tx_id is not None and len(str(tx_id)) > 5:
             return {"text": "✅ เคลมแล้ว", "status": "redeemed", "date": dt_thai, "sort": 999999, "urgent": False}
        
        # 2. เวลาผ่านไปแล้ว = พร้อมเคลม
        if total_seconds <= 0:
            return {"text": "🟣 พร้อมเคลม (Ready)", "status": "ready", "date": dt_thai, "sort": -999999, "urgent": True}
        
        # 3. ยังไม่ถึงเวลา = Locked
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        countdown = f"{days}วัน {hours}ชม."
        
        status = "urgent" if days <= 7 else "wait"
        urgent = True if days <= 7 else False
        icon = "🔥" if days <= 7 else "🔒"
        
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
st.title("🌙 NIGHT Tracker (Full History)")

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
                    st.success("✅ อัปเดตเสร็จสิ้น!")
                    st.rerun()

if not os.path.exists(CACHE_FILE):
    st.info("👋 กดปุ่ม **'🔄 ดึงข้อมูลใหม่'** ด้านบนขวาเพื่อเริ่มใช้งาน")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    
    last_update = datetime.fromisoformat(cached.get("updated_at", "")).strftime("%d/%m/%Y %H:%M")
    with col_top1:
        st.caption(f"💾 อัปเดตล่าสุด: {last_update}")

    # ดึงราคา
    with st.spinner("..เช็คราคา.."):
        p_usd, p_thb = get_market_price()

    # --- Processing & Grouping ---
    grouped_wallets = {}
    urgent_items = []
    redeemed_history = [] # รายการที่เคลมไปแล้วทั้งหมด
    
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
                    
                    # เก็บลงประวัติการเคลม (History Table)
                    redeemed_history.append({
                        "Wallet": w_name,
                        "Address": addr,
                        "Amount": amt,
                        "Value (THB)": amt * p_thb,
                        "Date": info['date'].strftime('%d/%m/%Y')
                    })
                    
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
                
                # Table inside expander (เฉพาะที่ยังไม่เคลม - เพื่อความสะอาด)
                if info['status'] != 'redeemed':
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
    
    # 2. มูลค่ารวม (คิดจาก Alloc)
    val_total = grand_alloc * p_thb
    m2.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าพอร์ต (Alloc)</h5><h2>฿{val_total:,.2f}</h2></div>', unsafe_allow_html=True)
    
    # 3. ยอดที่เหลือ
    m3.markdown(f'<div class="metric-card"><h5>⏳ NIGHT ที่เหลือ</h5><h2>{grand_left:,.2f}</h2></div>', unsafe_allow_html=True)
    
    # 4. ยอดที่เคลมไปแล้ว (พร้อมมูลค่า)
    val_redeemed_total = grand_redeemed * p_thb
    m4.markdown(f'<div class="metric-card redeemed-card"><h5>✅ เคลมไปแล้ว</h5><h2>{grand_redeemed:,.2f}</h2><small>฿{val_redeemed_total:,.2f}</small></div>', unsafe_allow_html=True)

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

    # --- Wallet Details (Official Card) ---
    st.subheader("📂 รายละเอียดกระเป๋า")
    
    for w_name, data in sorted(grouped_wallets.items(), key=lambda x: x[1]['ready'], reverse=True):
        val_ready = data['ready'] * p_thb
        icon = "🟢" if data['ready'] > 0 else "⚪"
        
        # Countdown logic
        countdown = "Completed"
        if data['ready'] > 0: countdown = "Available Now!"
        elif data['next_unlock']:
            diff = data['next_unlock'] - (datetime.utcnow()+timedelta(hours=7))
            countdown = f"Thaws in: {diff.days}d {diff.seconds//3600}h"
            
        # Avg Thaw Calculation
        addr_count = len(data['addresses']) if len(data['addresses']) > 0 else 1
        curr_thaw = int(data['redeemed_thaws'] / addr_count) + 1
        total_thaws_avg = int(data['total_thaws'] / addr_count)
        if curr_thaw > total_thaws_avg: curr_thaw = total_thaws_avg

        # Button Style
        btn_class = "redeem-btn-active" if data['ready'] > 0 else "redeem-btn-full"
        btn_text = "Redeem" if data['ready'] > 0 else "No tokens available"
        purple_sub = f"≈ ฿{val_ready:,.2f}" if data['ready'] > 0 else "Tokens become available after current thaw"

        # HTML Card
        html_card = f"""
        <div class="official-card-container">
            <div class="official-header">
                <div>Current thaw: {curr_thaw}/{total_thaws_avg}</div>
                <div style="font-size:0.9em; color:#6b7280;">{countdown}</div>
            </div>
            <div class="official-body">
                <div class="purple-redeem-box">
                    <div class="purple-label">Redeemable now</div>
                    <div class="purple-amount">{data['ready']:,.2f} NIGHT</div>
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

        with st.expander(f"{icon} {w_name} | พร้อมถอน: {data['ready']:,.2f} NIGHT (฿{val_ready:,.0f})"):
            st.markdown(f"**Addresses ({addr_count}):**")
            for ad in data['addresses']: st.code(ad)
            
            st.markdown(html_card, unsafe_allow_html=True)
            
            if data['history']:
                st.caption("Pending Transactions:")
                df_hist = pd.DataFrame(data['history']).sort_values("_sort")
                def color_row(val):
                    if "✅" in str(val): return 'color: green'
                    if "🟣" in str(val): return 'color: purple; font-weight: bold'
                    return 'color: gray'
                st.dataframe(df_hist[['Date', 'Amount', 'Status', 'Address']].style.applymap(color_row, subset=['Status']), use_container_width=True, hide_index=True)
            else:
                st.success("🎉 ครบกำหนดทุกรายการแล้ว (All Redeemed)")

    # --- Redeemed History Table (New) ---
    st.divider()
    st.subheader("📜 รายการที่เคลมไปแล้ว (Redeemed History)")
    
    if redeemed_history:
        df_red = pd.DataFrame(redeemed_history)
        # โชว์ข้อมูลให้ครบ: Wallet, Address, Amount, Value, Date
        st.dataframe(
            df_red.style.format({"Amount": "{:,.2f}", "Value (THB)": "฿{:,.2f}"}),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("ยังไม่มีประวัติการเคลม")
