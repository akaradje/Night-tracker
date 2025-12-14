import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests
import json

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Full Export)", page_icon="🌙", layout="wide")

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
        display: inline-block; width: 100%; text-align: center;
        background-color: #6f42c1; color: white !important; padding: 10px; 
        border-radius: 6px; text-decoration: none; font-weight: bold; margin-bottom: 10px;
        transition: background 0.3s;
    }
    .redeem-btn:hover { background-color: #5a32a3; }
</style>
""", unsafe_allow_html=True)

# --- Functions ---
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
        countdown = f"{days}วัน {hours}ชม."
        return {"text": f"⏳ {countdown}", "sort": total_seconds, "urgent": days <= 7, "status": "wait", "date": dt_thai}
    except:
        return {"text": "-", "sort": 999999, "urgent": False, "status": "unknown", "date": None}

async def fetch_vesting_data(session, wallet_name, address):
    url = f"https://mainnet.prod.gd.midnighttge.io/thaws/{address}/schedule"
    headers = {"User-Agent": "Mozilla/5.0", "Origin": "https://redeem.midnight.gd", "Referer": "https://redeem.midnight.gd/"}
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

async def update_database(df):
    results = []
    sem = asyncio.Semaphore(10)
    async def task(session, row):
        async with sem:
            return await fetch_vesting_data(session, row['Wallet_Name'], row['Address'])
    async with aiohttp.ClientSession() as session:
        tasks = [task(session, row) for index, row in df.iterrows()]
        for i, f in enumerate(asyncio.as_completed(tasks)):
            res = await f
            results.append(res)
    return results

# ==============================================================================
# MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker (Full Export)")

col_top1, col_top2 = st.columns([3, 1])
df_input = None
if os.path.exists('wallets.xlsx'): df_input = pd.read_excel('wallets.xlsx')
elif os.path.exists('active_wallets.csv'): df_input = pd.read_csv('active_wallets.csv')

with col_top2:
    if df_input is not None:
        if st.button("🔄 ดึงข้อมูลใหม่ (Update)", type="secondary", use_container_width=True):
            with st.spinner("⏳ กำลังโหลด..."):
                raw_data = asyncio.run(update_database(df_input))
                save_data = {"updated_at": datetime.now().isoformat(), "wallets": raw_data}
                with open(CACHE_FILE, 'w', encoding='utf-8') as f: json.dump(save_data, f, ensure_ascii=False, indent=4)
                st.success("✅ เรียบร้อย!")
                st.rerun()

if not os.path.exists(CACHE_FILE):
    st.info("👋 กดปุ่ม Update ขวาบนก่อนครับ")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: cached = json.load(f)
    last_update = datetime.fromisoformat(cached.get("updated_at", "")).strftime("%d/%m/%Y %H:%M")
    with col_top1: st.caption(f"💾 อัปเดตล่าสุด: {last_update}")
    
    with st.spinner("..เช็คราคา.."): p_usd, p_thb = get_market_price()

    # --- Processing ---
    grand_total_alloc = 0
    grand_total_remaining = 0
    wallets_data = {}
    urgent_items = []
    redeemed_history = []
    all_export_data = [] # เก็บทุกรายการเพื่อ Export

    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            
            # คำนวณยอด
            w_alloc = sum(t['amount'] for t in thaws) / 1_000_000
            grand_total_alloc += w_alloc
            
            active_thaws = [t for t in thaws if not t.get('transaction_id')]
            w_remain = sum(t['amount'] for t in active_thaws) / 1_000_000
            grand_total_remaining += w_remain
            
            # Loop เพื่อเก็บข้อมูลลง List สำหรับ Export (รวมทุกสถานะ)
            for t in thaws:
                amt = t['amount'] / 1_000_000
                is_redeemed = t.get('transaction_id') is not None
                
                # เช็คสถานะละเอียด
                if is_redeemed:
                    status_text = "Redeemed (เคลมแล้ว)"
                    date_display = t.get('thawing_period_start', '').split('T')[0]
                else:
                    time_info = process_claim_time(t['thawing_period_start'])
                    status_text = time_info['text']
                    date_display = time_info['date'].strftime('%d/%m/%Y %H:%M') if time_info['date'] else "-"

                # เพิ่มลงถังรวม (All Data)
                all_export_data.append({
                    "Wallet Name": w_name,
                    "Address": addr,
                    "Amount (NIGHT)": amt,
                    "Status": status_text,
                    "Unlock Date": date_display,
                    "Value (THB)": amt * p_thb
                })

            # แยกเก็บข้อมูลสำหรับแสดงผล UI (เหมือนเดิม)
            redeemed_thaws = [t for t in thaws if t.get('transaction_id')]
            for t in redeemed_thaws:
                r_amt = t['amount'] / 1_000_000
                redeemed_history.append({
                    "Wallet": w_name, "Address": addr, "Amount": r_amt,
                    "Value (THB)": r_amt * p_thb, "Date": t.get('thawing_period_start', '').split('T')[0]
                })

            if w_alloc > 0:
                if w_name not in wallets_data: 
                    wallets_data[w_name] = {"total_alloc": 0, "remaining": 0, "addrs": {}, "min_sort": 99999999999}
                wallets_data[w_name]["total_alloc"] += w_alloc
                wallets_data[w_name]["remaining"] += w_remain
                
                addr_info = {"amt": w_remain, "claims": []}
                for t in active_thaws:
                    time_data = process_claim_time(t['thawing_period_start'])
                    amt = t['amount'] / 1_000_000
                    if time_data['sort'] < wallets_data[w_name]['min_sort']:
                        wallets_data[w_name]['min_sort'] = time_data['sort']
                    addr_info["claims"].append({
                        "date_str": time_data['date'].strftime('%d/%m/%Y'),
                        "amount": amt, "status_text": time_data['text'], "status_code": time_data['status'], "sort": time_data['sort']
                    })
                    if time_data['urgent']:
                        urgent_items.append({
                            "Wallet": w_name, "Address": addr, "Amount": amt, "Value (THB)": amt * p_thb, "Status": time_data['text'], "Date": time_data['date'].strftime('%d/%m')
                        })
                wallets_data[w_name]["addrs"][addr] = addr_info

    grand_total_redeemed = grand_total_alloc - grand_total_remaining
    val_alloc_thb = grand_total_alloc * p_thb

    # --- Display ---
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f'<div class="metric-card"><h5>📦 ทั้งหมด (Alloc)</h5><h2>{grand_total_alloc:,.2f}</h2></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคา (THB)</h5><h2 style="color:#856404">฿{p_thb:,.4f}</h2></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าพอร์ต</h5><h2>฿{val_alloc_thb:,.2f}</h2></div>', unsafe_allow_html=True)
    m4.markdown(f'<div class="metric-card redeemed-card"><h5>✅ เคลมไปแล้ว</h5><h2>{grand_total_redeemed:,.2f}</h2></div>', unsafe_allow_html=True)

    if urgent_items:
        st.error(f"🚨 แจ้งเตือน: พบ {len(urgent_items)} รายการต้องเคลม")
        df_urg = pd.DataFrame(urgent_items)
        st.dataframe(df_urg.style.format({"Amount": "{:,.2f}"}), use_container_width=True, hide_index=True)

    st.subheader("📂 รายละเอียดกระเป๋า")
    for w_name, data in sorted(wallets_data.items(), key=lambda x: x[1]['min_sort']):
        val_remain = data['remaining'] * p_thb
        with st.expander(f"💼 {w_name} | เหลือ: {data['remaining']:,.2f} (฿{val_remain:,.0f}) | รวม: {data['total_alloc']:,.2f}"):
            st.markdown(f"""<a href="{REDEEM_URL}" target="_blank" class="redeem-btn">👉 ไปที่หน้ากดเคลม</a>""", unsafe_allow_html=True)
            for addr, info in data['addrs'].items():
                claims = sorted(info['claims'], key=lambda x: x['sort'])
                if claims:
                    nearest = claims[0]
                    c1, c2, c3 = st.columns([3, 2, 2])
                    c1.text(f"{addr}")
                    c2.markdown(f"**{info['amt']:,.2f}** NIGHT")
                    s_color = "green" if nearest.get('status_code') == 'ready' else "gray"
                    c3.markdown(f"<span style='color:{s_color}'><b>{nearest.get('status_text', '-')}</b></span>", unsafe_allow_html=True)
                    df_sub = pd.DataFrame(claims)[["date_str", "amount", "status_text"]]
                    st.dataframe(df_sub.style.format({"amount": "{:,.2f}"}), use_container_width=True, hide_index=True)
                    st.markdown("---")

    st.divider()
    st.subheader("💾 Export Data (โหลดข้อมูล)")
    
    c_ex1, c_ex2, c_ex3 = st.columns(3)
    
    # ปุ่ม 1: โหลดรายการต้องเคลมด่วน
    if urgent_items:
        csv_urg = pd.DataFrame(urgent_items).to_csv(index=False).encode('utf-8-sig')
        c_ex1.download_button("⬇️ โหลดรายการด่วน (Urgent)", csv_urg, "urgent_claims.csv", "text/csv", use_container_width=True)
    
    # ปุ่ม 2: โหลดประวัติการเคลมแล้ว
    if redeemed_history:
        csv_red = pd.DataFrame(redeemed_history).to_csv(index=False).encode('utf-8-sig')
        c_ex2.download_button("⬇️ โหลดประวัติเคลม (History)", csv_red, "redeemed_history.csv", "text/csv", use_container_width=True)
        
    # ปุ่ม 3: โหลดทั้งหมด (ตามที่ขอ)
    if all_export_data:
        csv_all = pd.DataFrame(all_export_data).to_csv(index=False).encode('utf-8-sig')
        c_ex3.download_button("⬇️ โหลดข้อมูลทั้งหมด (ALL DATA)", csv_all, "night_all_data.csv", "text/csv", type="primary", use_container_width=True)
