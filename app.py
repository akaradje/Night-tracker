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
REDEEM_URL = "https://redeem.midnight.gd/"

# ==============================================================================

# CSS สำหรับตกแต่ง UI
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
    .redeem-btn {
        display: inline-block; width: 100%; text-align: center;
        background-color: #6f42c1; color: white !important; padding: 10px; 
        border-radius: 6px; text-decoration: none; font-weight: bold; margin-bottom: 10px;
    }
    .redeem-btn:hover { background-color: #5a32a3; }
</style>
""", unsafe_allow_html=True)

# --- Functions ---

def get_market_price():
    """ดึงราคา NIGHT จาก Moralis API"""
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
    """คำนวณเวลานับถอยหลัง"""
    try:
        now_thai = datetime.utcnow() + timedelta(hours=7)
        clean_str = iso_str.replace('Z', '').split('.')[0]
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        if total_seconds <= 0:
            return {"text": "✅ เคลมได้เลย", "sort": -999999, "status": "ready", "date": dt_thai, "urgent": True}
        
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        return {"text": f"⏳ {days}วัน {hours}ชม.", "sort": total_seconds, "status": "wait", "date": dt_thai, "urgent": days <= 7}
    except:
        return {"text": "-", "sort": 999999, "status": "unknown", "date": None, "urgent": False}

async def fetch_vesting_data(session, wallet_name, address):
    """ดึงข้อมูลจาก Midnight API (ปรับปรุง Headers)"""
    address = address.strip() # ลบช่องว่างที่อาจติดมาในไฟล์ Excel
    url = f"https://mainnet.prod.gd.midnighttge.io/thaws/{address}/schedule"
    
    # Headers แบบเลียนแบบ Browser เพื่อป้องกันการโดน Block
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://redeem.midnight.gd",
        "Referer": "https://redeem.midnight.gd/",
        "Accept-Language": "en-US,en;q=0.9,th;q=0.8"
    }
    
    try:
        async with session.get(url, headers=headers, timeout=15) as response:
            if response.status == 200:
                data = await response.json()
                # ตรวจสอบว่ามีคีย์ thaws หรือไม่
                if "thaws" in data:
                    return {"wallet": wallet_name, "address": address, "data": data, "status": "ok"}
                else:
                    return {"wallet": wallet_name, "address": address, "status": "empty_data", "msg": "No thaws found"}
            elif response.status == 404:
                return {"wallet": wallet_name, "address": address, "data": {"thaws": []}, "status": "ok"}
            return {"wallet": wallet_name, "address": address, "status": f"error_{response.status}"}
    except Exception as e:
        return {"wallet": wallet_name, "address": address, "status": "fail", "msg": str(e)}

async def update_database(df):
    """รัน Task แบบ Async"""
    results = []
    sem = asyncio.Semaphore(5) # จำกัดการยิงพร้อมกัน 5 กระเป๋าเพื่อความเสถียร
    async def task(session, row):
        async with sem:
            return await fetch_vesting_data(session, row['Wallet_Name'], row['Address'])
    
    async with aiohttp.ClientSession() as session:
        tasks = [task(session, row) for index, row in df.iterrows()]
        for f in asyncio.as_completed(tasks):
            res = await f
            results.append(res)
    return results

# ==============================================================================
# MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker (Full Export)")

# 1. ตรวจสอบไฟล์ Input
df_input = None
if os.path.exists('wallets.xlsx'): 
    df_input = pd.read_excel('wallets.xlsx')
elif os.path.exists('active_wallets.csv'): 
    df_input = pd.read_csv('active_wallets.csv')

col_top1, col_top2 = st.columns([3, 1])

with col_top2:
    if df_input is not None:
        st.write(f"📁 พบ {len(df_input)} กระเป๋า")
        if st.button("🔄 อัปเดตข้อมูล (Update)", type="primary", use_container_width=True):
            with st.spinner("⏳ กำลังคุยกับ Midnight API..."):
                raw_data = asyncio.run(update_database(df_input))
                save_data = {"updated_at": datetime.now().isoformat(), "wallets": raw_data}
                with open(CACHE_FILE, 'w', encoding='utf-8') as f: 
                    json.dump(save_data, f, ensure_ascii=False, indent=4)
                
                # เช็คผลลัพธ์เบื้องต้น
                errors = [r for r in raw_data if r['status'] != 'ok']
                if errors:
                    st.warning(f"⚠️ พบข้อผิดพลาด {len(errors)} รายการ (ดูใน Console หรือลองกดใหม่)")
                else:
                    st.success("✅ อัปเดตข้อมูลสำเร็จ!")
                st.rerun()
    else:
        st.error("❌ ไม่พบไฟล์ wallets.xlsx")

# 2. แสดงผลข้อมูลจาก Cache
if not os.path.exists(CACHE_FILE):
    st.info("👋 ยินดีต้อนรับ! กรุณากดปุ่ม Update ด้านบนเพื่อเริ่มดึงข้อมูลครั้งแรก")
else:
    with open(CACHE_FILE, 'r', encoding='utf-8') as f: 
        cached = json.load(f)
    
    last_update = datetime.fromisoformat(cached.get("updated_at", "")).strftime("%d/%m/%Y %H:%M")
    with col_top1: st.caption(f"💾 ข้อมูลล่าสุดเมื่อ: {last_update}")
    
    p_usd, p_thb = get_market_price()

    # --- การประมวลผลข้อมูลเพื่อแสดงผล ---
    grand_total_alloc = 0
    grand_total_remaining = 0
    wallets_data = {}
    urgent_items = []
    redeemed_history = []
    all_export_data = []

    for item in cached.get("wallets", []):
        if item.get('status') == 'ok':
            thaws = item['data'].get('thaws', [])
            w_name = item['wallet']
            addr = item['address']
            
            w_alloc = sum(t['amount'] for t in thaws) / 1_000_000
            grand_total_alloc += w_alloc
            
            active_thaws = [t for t in thaws if not t.get('transaction_id')]
            w_remain = sum(t['amount'] for t in active_thaws) / 1_000_000
            grand_total_remaining += w_remain
            
            # เก็บข้อมูล Export
            for t in thaws:
                amt = t['amount'] / 1_000_000
                is_redeemed = t.get('transaction_id') is not None
                if is_redeemed:
                    status_text = "Claimed (เคลมแล้ว)"
                    date_display = t.get('thawing_period_start', '').split('T')[0]
                    redeemed_history.append({"Wallet": w_name, "Address": addr, "Amount": amt, "Date": date_display})
                else:
                    time_info = process_claim_time(t['thawing_period_start'])
                    status_text = time_info['text']
                    date_display = time_info['date'].strftime('%d/%m/%Y %H:%M') if time_info['date'] else "-"
                    if time_info['urgent']:
                        urgent_items.append({"Wallet": w_name, "Address": addr, "Amount": amt, "Status": status_text, "Date": date_display})

                all_export_data.append({
                    "Wallet Name": w_name, "Address": addr, "Amount": amt,
                    "Status": status_text, "Unlock Date": date_display, "Value (THB)": amt * p_thb
                })

            # จัดกลุ่มสำหรับ UI
            if w_name not in wallets_data: 
                wallets_data[w_name] = {"remaining": 0, "total": 0, "addrs": {}, "min_sort": 9999999999}
            
            wallets_data[w_name]["remaining"] += w_remain
            wallets_data[w_name]["total"] += w_alloc
            
            addr_info = {"amt": w_remain, "claims": []}
            for t in active_thaws:
                time_data = process_claim_time(t['thawing_period_start'])
                if time_data['sort'] < wallets_data[w_name]['min_sort']:
                    wallets_data[w_name]['min_sort'] = time_data['sort']
                addr_info["claims"].append({
                    "date": time_data['date'].strftime('%d/%m/%Y'),
                    "amount": t['amount']/1_000_000, "status": time_data['text'], "code": time_data['status'], "sort": time_data['sort']
                })
            wallets_data[w_name]["addrs"][addr] = addr_info

    # --- ส่วน Dashboard สรุปยอด ---
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f'<div class="metric-card"><h5>📦 ทั้งหมด (Alloc)</h5><h2>{grand_total_alloc:,.2f}</h2></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคา (THB)</h5><h2>฿{p_thb:,.4f}</h2></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าพอร์ต</h5><h2>฿{grand_total_remaining * p_thb:,.2f}</h2></div>', unsafe_allow_html=True)
    m4.markdown(f'<div class="metric-card redeemed-card"><h5>✅ เคลมไปแล้ว</h5><h2>{grand_total_alloc - grand_total_remaining:,.2f}</h2></div>', unsafe_allow_html=True)

    # แสดงรายการด่วน
    if urgent_items:
        st.error(f"🚨 รายการที่ต้องเคลมด่วน ({len(urgent_items)} รายการ)")
        st.dataframe(pd.DataFrame(urgent_items), use_container_width=True, hide_index=True)

    # --- รายละเอียดแต่ละกระเป๋า ---
    st.subheader("📂 รายละเอียดกระเป๋า")
    # เรียงตามกระเป๋าที่ใกล้ถึงเวลาเคลมที่สุด
    for w_name, data in sorted(wallets_data.items(), key=lambda x: x[1]['min_sort']):
        with st.expander(f"💼 {w_name} | เหลือ: {data['remaining']:,.2f} | ทั้งหมด: {data['total']:,.2f}"):
            st.markdown(f'<a href="{REDEEM_URL}" target="_blank" class="redeem-btn">🔗 ไปที่หน้าเคลม (Midnight)</a>', unsafe_allow_html=True)
            for addr, info in data['addrs'].items():
                st.caption(f"Address: {addr}")
                if info['claims']:
                    df_c = pd.DataFrame(info['claims']).sort_values('sort')
                    st.dataframe(df_c[['date', 'amount', 'status']], use_container_width=True, hide_index=True)
                else:
                    st.write("✅ เคลมครบทุกรอบแล้ว")

    # --- Export ---
    st.divider()
    st.subheader("💾 ดาวน์โหลดข้อมูล (CSV)")
    if all_export_data:
        csv_all = pd.DataFrame(all_export_data).to_csv(index=False).encode('utf-8-sig')
        st.download_button("⬇️ โหลดข้อมูลทั้งหมด (ALL DATA)", csv_all, "night_export.csv", "text/csv", type="primary")
