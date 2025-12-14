import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Unified Mode)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG & KEY
# ==============================================================================
CACHE_FILE = "vesting_data.json"  # ไฟล์สำหรับบันทึกข้อมูล
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f" # Contract NIGHT
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
REDEEM_URL = "https://redeem.midnight.gd/"
# ==============================================================================

# CSS แต่งสวย (เพิ่มส่วน Official UI เข้าไป)
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

    /* --- ส่วนที่เพิ่ม: Official UI Styles --- */
    .card-container {
        border: 1px solid #e0e0e0; border-radius: 12px; margin-top: 10px; margin-bottom: 10px;
        background-color: white; overflow: hidden;
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
    .redeem-btn {
        display: inline-block; width: 100%; text-align: center;
        background-color: #6f42c1; color: white !important; padding: 10px; 
        border-radius: 6px; text-decoration: none; font-weight: bold; margin-top: 10px;
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
        if r.status_code == 200: 
            usd_price = r.json().get("usdPrice", 0)
    except Exception as e: 
        print(f"Price Error: {e}")
    
    return usd_price, usd_price * thb_rate

# --- Function: คำนวณเวลา (ปรับปรุงให้เช็ค Tx ID ได้) ---
def process_claim_status(iso_str, tx_id):
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        # 1. เช็คว่าเคลมไปแล้วหรือยัง (มี Tx ID ไหม)
        if tx_id is not None and len(str(tx_id)) > 5:
             return {"text": "✅ เคลมแล้ว", "status": "redeemed", "date": dt_thai, "sort": 999999, "urgent": False}

        # 2. เช็คว่าถึงเวลาหรือยัง
        if total_seconds <= 0:
            return {"text": "🟣 พร้อมถอน (Ready)", "status": "ready", "date": dt_thai, "sort": -999999, "urgent": True}
        
        # 3. ยังไม่ถึงเวลา
        days = total_seconds // 86400
        urgent = True if days <= 7 else False
        icon = "🔥" if urgent else "🔒"
        return {"text": f"{icon} Locked ({days}d)", "status": "locked", "date": dt_thai, "sort": total_seconds, "urgent": urgent}
            
    except:
        return {"text": "-", "status": "unknown", "date": None, "sort": 999999, "urgent": False}

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

    # 3. ประมวลผลและจัดกลุ่ม (Grouping Logic)
    grouped_wallets = {}
    urgent_items = []
    
    grand_redeemable = 0
    grand_left = 0
    grand_total = 0
    
    # วนลูปเพื่อรวบรวมข้อมูลและจัดกลุ่ม
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            
            # สร้างกลุ่มถ้ายังไม่มี
            if w_name not in grouped_wallets:
                grouped_wallets[w_name] = {
                    'alloc': 0, 'redeemed': 0, 'left': 0, 'ready': 0,
                    'addresses': [], 'history': [], 
                    'thaws_total': 0, 'thaws_redeemed': 0, 'next_unlock': None
                }

            # คำนวณราย Address
            for t in thaws:
                amt = t['amount'] / 1_000_000
                info = process_claim_status(t['thawing_period_start'], t.get('transaction_id'))
                
                # บวกยอดเข้ากลุ่ม
                grouped_wallets[w_name]['alloc'] += amt
                grouped_wallets[w_name]['thaws_total'] += 1
                
                if info['status'] == 'redeemed':
                    grouped_wallets[w_name]['redeemed'] += amt
                    grouped_wallets[w_name]['thaws_redeemed'] += 1
                else:
                    grouped_wallets[w_name]['left'] += amt
                    if info['status'] == 'ready':
                        grouped_wallets[w_name]['ready'] += amt
                    elif info['status'] == 'locked':
                        curr = grouped_wallets[w_name]['next_unlock']
                        if curr is None or (info['date'] and info['date'] < curr):
                            grouped_wallets[w_name]['next_unlock'] = info['date']

                # เก็บประวัติรายการ
                grouped_wallets[w_name]['history'].append({
                    "Date": info['date'].strftime('%d/%m/%Y') if info['date'] else "-",
                    "Amount": amt, "Status": info['text'], "_sort": info['sort'], "Address": addr
                })
                
                # แจ้งเตือนด่วน
                if info['urgent']:
                    urgent_items.append({
                        "Wallet": w_name, "Amount": amt, "Value (THB)": amt * p_thb,
                        "Status": info['text'], "_sort": info['sort']
                    })

            grouped_wallets[w_name]['addresses'].append(addr)

    # คำนวณยอดรวมทั้งพอร์ต
    for data in grouped_wallets.values():
        grand_total += data['alloc']
        grand_redeemable += data['ready']
        grand_left += data['left']

    # --- แสดงผล Cards (Metrics) ---
    st.divider()
    m1, m2, m3 = st.columns(3)
    m1.markdown(f'<div class="metric-card"><h5>🟣 พร้อมถอน (Now)</h5><h2>{grand_redeemable:,.2f}</h2><small>฿{grand_redeemable*p_thb:,.2f}</small></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคา (Real-time)</h5><h2 style="color:#856404">฿{p_thb:,.4f}</h2><small>${p_usd:,.4f}</small></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card value-card"><h5>📦 มูลค่ารวม (บาท)</h5><h2>฿{grand_total * p_thb:,.2f}</h2></div>', unsafe_allow_html=True)

    # --- แจ้งเตือนด่วน ---
    if urgent_items:
        st.error(f"🚨 แจ้งเตือน: พบ {len(urgent_items)} รายการต้องเคลม (ภายใน 7 วัน)")
        df_urg = pd.DataFrame(urgent_items).sort_values("_sort").drop(columns=["_sort"])
        st.dataframe(
            df_urg.style.format({"Amount": "{:,.2f}", "Value (THB)": "฿{:,.2f}"})
            .map(lambda x: "background-color: #d4edda; color:green" if "🟣" in str(x) else "color:red", subset=["Status"]),
            use_container_width=True, hide_index=True
        )

    # --- รายละเอียด (Official Grouped View) ---
    st.subheader("📂 รายละเอียดกระเป๋า (รวมยอด)")
    
    # วนลูปแสดงผล (เรียงตามยอดพร้อมถอนมากสุดก่อน)
    sorted_wallets = sorted(grouped_wallets.items(), key=lambda x: x[1]['ready'], reverse=True)
    
    for w_name, data in sorted_wallets:
        
        w_ready = data['ready']
        price_val = w_ready * p_thb
        icon = "🟢" if w_ready > 0 else "⚪"
        
        # คำนวณงวด
        addr_count = len(data['addresses']) if len(data['addresses']) > 0 else 1
        curr_thaw = int((data['thaws_redeemed'] / addr_count)) + 1
        total_thaws_per_addr = int(data['thaws_total'] / addr_count)
        if curr_thaw > total_thaws_per_addr: curr_thaw = total_thaws_per_addr

        # Countdown
        countdown = "Completed"
        if w_ready > 0: countdown = "Available Now!"
        elif data['next_unlock']:
            diff = data['next_unlock'] - (datetime.utcnow()+timedelta(hours=7))
            countdown = f"Thaws in: {diff.days} days"

        # EXPANDER: ชื่อกระเป๋า + ยอดรวม
        with st.expander(f"{icon} {w_name} | พร้อมถอน: {w_ready:,.2f} NIGHT (฿{price_val:,.0f})", expanded=False):
            
            # แสดง Address
            st.markdown(f"**Addresses ({addr_count}):**")
            for ad in data['addresses']: st.code(ad)

            # OFFICIAL UI CARD
            st.markdown(f"""
            <div class="card-container">
                <div class="thaw-header">
                    <span>Current thaw: ~{curr_thaw}/{total_thaws_per_addr}</span>
                    <span style="font-size:0.9em; color:#555;">{countdown}</span>
                </div>
                <div class="card-body">
                    <div class="purple-box">
                        <small>Redeemable now:</small>
                        <h2>{w_ready:,.2f} NIGHT</h2>
                        <small>≈ ฿{price_val:,.2f}</small>
                        <br>
                        <a href="{REDEEM_URL}" target="_blank" class="redeem-btn">👉 ไปที่หน้ากดเคลม (Redeem Site)</a>
                    </div>
                    <div class="detail-row"><span class="detail-label">Redeemed so far:</span> <span class="detail-val">{data['redeemed']:,.2f}</span></div>
                    <div class="detail-row"><span class="detail-label">Total left to redeem:</span> <span class="detail-val">{data['left']:,.2f}</span></div>
                    <div class="detail-row"><span class="detail-label">Total allocation size:</span> <span class="detail-val">{data['alloc']:,.2f}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # TABLE
            st.caption("Transactions List:")
            df_show = pd.DataFrame(data['history']).sort_values("_sort")
            
            def color_row(val):
                if "✅" in str(val): return 'color: green'
                if "🟣" in str(val): return 'color: purple; font-weight: bold'
                return 'color: gray'

            st.dataframe(
                df_show[['Date', 'Amount', 'Status', 'Address']].style.applymap(color_row, subset=['Status']),
                use_container_width=True, hide_index=True
            )
