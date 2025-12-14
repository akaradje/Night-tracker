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
CACHE_FILE = "vesting_data.json"
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f"
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
REDEEM_URL = "https://redeem.midnight.gd/"
# ==============================================================================

# CSS
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
    
    .redeem-btn {
        display: inline-block;
        background-color: #6f42c1; color: white !important;
        padding: 8px 20px; border-radius: 6px;
        text-decoration: none; font-weight: bold;
        margin-bottom: 15px; text-align: center;
        width: 100%;
        transition: background-color 0.3s;
    }
    .redeem-btn:hover { background-color: #5a32a3; }
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
        
        if total_seconds <= 0:
            return {"text": "✅ เคลมได้เลย", "sort": -999999, "urgent": True, "status": "ready", "date": dt_thai}
        
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        
        countdown = " ".join([f"{days}วัน" if days>0 else "", f"{hours}ชม." if hours>0 else ""])
        if not countdown: countdown = "เร็วๆ นี้"
        
        status = "urgent" if days <= 7 else "wait"
        urgent = True if days <= 7 else False
        icon = "🔥" if days <= 7 else "🔒"
        
        return {"text": f"{icon} {countdown}", "sort": total_seconds, "urgent": urgent, "status": status, "date": dt_thai}
    except:
        return {"text": "-", "sort": 999999, "urgent": False, "status": "unknown", "date": None}

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
                    st.success("✅ อัปเดตสำเร็จ!")
                    st.rerun()

if not os.path.exists(CACHE_FILE):
    st.info("👋 กดปุ่ม **'🔄 ดึงข้อมูลใหม่'** ด้านบนขวาเพื่อเริ่มใช้งาน")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    
    last_update = datetime.fromisoformat(cached.get("updated_at", "")).strftime("%d/%m/%Y %H:%M")
    with col_top1:
        st.caption(f"💾 อัปเดตล่าสุด: {last_update}")

    with st.spinner("..เช็คราคา.."):
        p_usd, p_thb = get_market_price()

    # --- Calculation ---
    grand_total_alloc = 0
    grand_total_remaining = 0
    
    wallets_data = {}
    urgent_items = []
    redeemed_list = [] # เก็บรายการที่เคลมไปแล้ว
    
    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            
            # 1. ยอดทั้งหมด (Alloc)
            w_total_alloc = sum(t['amount'] for t in thaws) / 1_000_000
            grand_total_alloc += w_total_alloc
            
            # 2. ยอดคงเหลือ (Active - No Tx ID)
            active_thaws = [t for t in thaws if not t.get('transaction_id')]
            w_total_remaining = sum(t['amount'] for t in active_thaws) / 1_000_000
            grand_total_remaining += w_total_remaining
            
            # 3. เก็บรายการที่เคลมแล้ว (Has Tx ID)
            done_thaws = [t for t in thaws if t.get('transaction_id')]
            for t in done_thaws:
                r_amt = t['amount'] / 1_000_000
                redeemed_list.append({
                    "Wallet": w_name,
                    "Address": addr,
                    "Amount": r_amt,
                    "Value (THB)": r_amt * p_thb,
                    "Date": t.get('thawing_period_start', '').split('T')[0]
                })

            # Data for Wallet Details (Only Active)
            if w_total_alloc > 0:
                if w_name not in wallets_data: 
                    wallets_data[w_name] = {"total_alloc": 0, "remaining": 0, "addrs": {}}
                
                wallets_data[w_name]["total_alloc"] += w_total_alloc
                wallets_data[w_name]["remaining"] += w_total_remaining
                
                addr_info = {"total_alloc": w_total_alloc, "remaining": w_total_remaining, "claims": []}
                
                for t in active_thaws:
                    time_data = process_claim_time(t['thawing_period_start'])
                    amt = t['amount'] / 1_000_000
                    
                    addr_info["claims"].append({
                        "date_str": time_data['date'].strftime('%d/%m/%Y') if time_data['date'] else "-",
                        "amount": amt,
                        "status_text": time_data['text'],
                        "status_code": time_data['status'],
                        "sort": time_data['sort']
                    })
                    
                    if time_data['urgent']:
                        urgent_items.append({
                            "Wallet": w_name,
                            "Address": addr,
                            "Amount": amt,
                            "Value (THB)": amt * p_thb,
                            "Status": time_data['text'],
                            "Date": time_data['date'].strftime('%d/%m'),
                            "_sort": time_data['sort'],
                            "Link": REDEEM_URL
                        })
                
                wallets_data[w_name]["addrs"][addr] = addr_info

    grand_total_redeemed = grand_total_alloc - grand_total_remaining
    val_alloc_thb = grand_total_alloc * p_thb
    val_redeemed_thb = grand_total_redeemed * p_thb

    # --- Cards ---
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f'<div class="metric-card"><h5>📦 NIGHT ทั้งหมด (Alloc)</h5><h2>{grand_total_alloc:,.2f}</h2></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าพอร์ต (Alloc)</h5><h2>฿{val_alloc_thb:,.2f}</h2></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card"><h5>⏳ NIGHT ที่เหลือ</h5><h2>{grand_total_remaining:,.2f}</h2></div>', unsafe_allow_html=True)
    m4.markdown(f'<div class="metric-card redeemed-card"><h5>✅ เคลมไปแล้ว</h5><h2>{grand_total_redeemed:,.2f}</h2><small>฿{val_redeemed_thb:,.2f}</small></div>', unsafe_allow_html=True)

    # --- Alerts ---
    if urgent_items:
        st.error(f"🚨 แจ้งเตือน: พบ {len(urgent_items)} รายการต้องเคลม (ภายใน 7 วัน)")
        df_urg = pd.DataFrame(urgent_items).sort_values("_sort").drop(columns=["_sort"])
        st.dataframe(
            df_urg,
            column_config={
                "Amount": st.column_config.NumberColumn("Amount", format="%.2f"),
                "Value (THB)": st.column_config.NumberColumn("Value (THB)", format="฿%.2f"),
                "Link": st.column_config.LinkColumn("Action", display_text="🚀 กดเคลม")
            },
            hide_index=True,
            use_container_width=True
        )

    # --- Wallet Details (Active) ---
    st.subheader("📂 รายละเอียดกระเป๋า (ยอดที่ยังไม่เคลม)")
    for w_name, data in sorted(wallets_data.items(), key=lambda x: x[1]['total_alloc'], reverse=True):
        w_redeemed = data['total_alloc'] - data['remaining']
        val_w_redeemed = w_redeemed * p_thb
        header_text = f"💼 {w_name} | ทั้งหมด: {data['total_alloc']:,.2f} | เคลมแล้ว: {w_redeemed:,.2f} (฿{val_w_redeemed:,.0f})"
        
        with st.expander(header_text):
            st.markdown(f"""<a href="{REDEEM_URL}" target="_blank" class="redeem-btn">👉 ไปที่หน้ากดเคลม (Redeem Site)</a>""", unsafe_allow_html=True)
            for addr, info in data['addrs'].items():
                claims = sorted(info['claims'], key=lambda x: x['sort'])
                if claims:
                    nearest = claims[0]
                    c1, c2, c3 = st.columns([3, 2, 2])
                    c1.text(f"{addr}")
                    c2.markdown(f"**เหลือ: {info['remaining']:,.2f}** / ทั้งหมด: {info['total_alloc']:,.2f}")
                    s_color = "green" if nearest.get('status_code') == 'ready' else "red" if nearest.get('status_code') == 'urgent' else "gray"
                    c3.markdown(f"<span style='color:{s_color}'><b>{nearest.get('status_text', '-')}</b></span>", unsafe_allow_html=True)
                    
                    df_sub = pd.DataFrame(claims)[["date_str", "amount", "status_text"]]
                    df_sub.columns = ["วันที่ปลดล็อค", "จำนวน", "สถานะ"]
                    st.dataframe(df_sub.style.format({"จำนวน": "{:,.2f}"}), use_container_width=True, hide_index=True)
                    st.markdown("---")

    # --- Redeemed History Table ---
    st.subheader("📜 รายการที่เคลมไปแล้ว (Redeemed History)")
    if redeemed_list:
        df_red = pd.DataFrame(redeemed_list)
        st.dataframe(
            df_red.style.format({"Amount": "{:,.2f}", "Value (THB)": "฿{:,.2f}"}),
            use_container_width=True, hide_index=True
        )
    else:
        st.info("ยังไม่มีรายการที่เคลม")
