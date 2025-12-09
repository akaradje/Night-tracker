import streamlit as st
import asyncio
import aiohttp
import pandas as pd
from datetime import datetime, timedelta
import os
import requests

# --- 1. ตั้งค่าและ Config ---
st.set_page_config(page_title="NIGHT Tracker Pro", page_icon="🌙", layout="wide")

# ========================================================
# 🔑 วาง KEY ยาวๆ ของคุณลงในช่องว่างข้างล่างนี้ (ในเครื่องหมายคำพูด)
# ========================================================
UNIVERSAL_KEY = ""  # <--- วาง Key ตรงนี้ครับ (เช่น "eyJhbGci...")

# Config อื่นๆ
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f" # Contract NIGHT
VESTING_API_URL = "https://aysqjcborxgdnivlisxl.supabase.co/functions/v1/thaw-schedule"

# CSS แต่งสวย
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
</style>
""", unsafe_allow_html=True)

# --- Function 1: ดึงราคา (Moralis) ---
def get_token_price(api_key):
    if not api_key: return 0
    
    # ลองใช้ Key ที่ให้มาดึงราคา
    url = f"https://deep-index.moralis.io/api/v2/erc20/{TOKEN_ADDRESS}/price?chain=bsc"
    headers = {"X-API-Key": api_key} # ปกติ Moralis ใช้ header นี้
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data.get("usdPrice", 0)
        else:
            # ถ้า Key นี้ใช้กับ Moralis ไม่ได้ (อาจเป็น Key ของ Supabase อย่างเดียว)
            # จะไม่ Error ให้ตกใจ แต่จะคืนค่า 0 เงียบๆ (หรือ Print เตือนใน Log)
            print(f"Note: Price fetch failed ({response.status_code}). Key might be for Vesting only.")
            return 0
    except Exception as e:
        print(f"Error fetching price: {e}")
        return 0

# --- Helper: คำนวณเวลา ---
def process_claim_time(iso_str, now_thai):
    try:
        clean_str = iso_str.replace('Z', '').split('.')[0] 
        dt_utc = datetime.fromisoformat(clean_str)
        dt_thai = dt_utc + timedelta(hours=7)
        delta = dt_thai - now_thai
        total_seconds = int(delta.total_seconds())
        
        if total_seconds <= 0:
            return {"text": "✅ เคลมได้เลย", "sort": -1, "urgent": True, "date": dt_thai}
        
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        
        parts = []
        if days > 0: parts.append(f"{days}วัน")
        if hours > 0: parts.append(f"{hours}ชม.")
        if days == 0 and minutes > 0: parts.append(f"{minutes}น.")
        
        return {
            "text": " ".join(parts) if parts else "เร็วๆ นี้",
            "sort": total_seconds,
            "urgent": days <= 7,
            "date": dt_thai
        }
    except:
        return {"text": "-", "sort": 999999999, "urgent": False, "date": iso_str}

# --- Function 2: ดึงข้อมูล Vesting (Supabase) ---
async def fetch_vesting_data(session, wallet_name, address, api_key):
    # ใส่ Key ลงใน Header เผื่อ API ต้องการ Auth (Bearer Token)
    headers = {}
    if api_key and len(api_key) > 50: # ถ้า Key ยาวๆ น่าจะเป็น JWT
        headers["Authorization"] = f"Bearer {api_key}"
        
    try:
        async with session.get(VESTING_API_URL, params={"address": address}, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return {"wallet": wallet_name, "address": address, "data": data, "status": "ok"}
            return {"wallet": wallet_name, "address": address, "status": "error", "code": response.status}
    except Exception as e:
        return {"wallet": wallet_name, "address": address, "status": "fail", "error": str(e)}

async def run_scan(df, api_key):
    results = []
    sem = asyncio.Semaphore(50)
    
    async def task(session, row):
        async with sem:
            return await fetch_vesting_data(session, row['Wallet_Name'], row['Address'], api_key)

    async with aiohttp.ClientSession() as session:
        tasks = [task(session, row) for index, row in df.iterrows()]
        
        # Progress Bar
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        completed = 0
        total = len(tasks)
        
        for f in asyncio.as_completed(tasks):
            res = await f
            results.append(res)
            completed += 1
            if completed % 5 == 0 or completed == total:
                progress_bar.progress(completed / total)
                status_text.text(f"⏳ กำลังสแกน... {completed}/{total}")
        
        progress_bar.empty()
        status_text.empty()
            
    return results

# --- MAIN UI ---
st.title("🌙 NIGHT Vesting & Price Tracker")

# Input Key (เผื่ออยากกรอกหน้าเว็บแทนแก้โค้ด)
with st.sidebar:
    st.header("⚙️ Config")
    user_api_key = st.text_input("API Key (Paste here if empty in code)", 
                                value=UNIVERSAL_KEY, 
                                type="password",
                                help="วาง Key ยาวๆ ที่นี่ ใช้สำหรับดึงข้อมูลและราคา")

# โหลดไฟล์
df_input = None
if os.path.exists('active_wallets.csv'):
    st.success(f"📂 โหลดข้อมูลเดิม: active_wallets.csv")
    df_input = pd.read_csv('active_wallets.csv')
elif os.path.exists('wallets.xlsx'):
    st.info(f"📂 พบไฟล์ต้นฉบับ: wallets.xlsx")
    df_input = pd.read_excel('wallets.xlsx')
else:
    uploaded = st.file_uploader("อัปโหลดไฟล์ (xlsx/csv)", type=['xlsx', 'csv'])
    if uploaded:
        df_input = pd.read_csv(uploaded) if uploaded.name.endswith('.csv') else pd.read_excel(uploaded)

# ปุ่มเริ่มทำงาน
if df_input is not None:
    col_btn, col_info = st.columns([1, 4])
    with col_btn:
        start = st.button("🚀 เริ่มสแกน (Start)", type="primary", use_container_width=True)
    
    if start:
        # 1. ดึงข้อมูล Vesting
        raw_data = asyncio.run(run_scan(df_input, user_api_key))
        
        # 2. ดึงราคา (ใช้ Key เดียวกันลองดู)
        price_usd = 0
        if user_api_key:
            with st.spinner("💸 กำลังเช็คราคาตลาด..."):
                price_usd = get_token_price(user_api_key)
        
        # 3. ประมวลผล
        now_thai = datetime.utcnow() + timedelta(hours=7)
        total_night = 0
        wallets_data = {}
        urgent_items = []
        active_list = []

        for item in raw_data:
            if item['status'] == 'ok':
                thaws = item['data'].get('thaws', [])
                w_name = item['wallet']
                addr = item['address']
                
                # รวมยอด
                sum_amt = sum(t['amount'] for t in thaws) / 1_000_000
                if sum_amt > 0:
                    total_night += sum_amt
                    if w_name not in wallets_data: wallets_data[w_name] = {"total": 0, "addrs": {}}
                    wallets_data[w_name]["total"] += sum_amt
                    
                    # เก็บรายละเอียดแต่ละ Address
                    addr_info = {"amt": sum_amt, "claims": []}
                    
                    for t in thaws:
                        time_data = process_claim_time(t['thawing_period_start'], now_thai)
                        amt = t['amount'] / 1_000_000
                        
                        addr_info["claims"].append({
                            "date": time_data['date'].strftime('%d/%m/%Y %H:%M'),
                            "amount": amt,
                            "countdown": time_data['text'],
                            "sort": time_data['sort']
                        })
                        
                        if time_data['urgent']:
                            urgent_items.append({
                                "Wallet": w_name,
                                "Address": addr,
                                "Amount": amt,
                                "Value ($)": amt * price_usd,
                                "Date": time_data['date'].strftime('%d/%m %H:%M'),
                                "Countdown": time_data['text'],
                                "_sort": time_data['sort']
                            })
                            
                    wallets_data[w_name]["addrs"][addr] = addr_info
                    active_list.append({"Wallet_Name": w_name, "Address": addr})

        # --- แสดงผล ---
        st.divider()
        st.write(f"🕒 อัปเดต: {now_thai.strftime('%d/%m/%Y %H:%M:%S')}")

        # Metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(f'<div class="metric-card"><h5>🌙 NIGHT ทั้งหมด</h5><h2>{total_night:,.2f}</h2></div>', unsafe_allow_html=True)
        
        price_color = "#28a745" if price_usd > 0 else "#6c757d"
        price_text = f"${price_usd:,.4f}" if price_usd > 0 else "N/A"
        m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคา (BSC)</h5><h2 style="color:{price_color}">{price_text}</h2></div>', unsafe_allow_html=True)
        
        val_usd = total_night * price_usd
        m3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าพอร์ต</h5><h2>${val_usd:,.2f}</h2></div>', unsafe_allow_html=True)
        
        m4.markdown(f'<div class="metric-card"><h5>📝 Active Wallets</h5><h2>{len(active_list)}</h2></div>', unsafe_allow_html=True)

        # รายการด่วน
        if urgent_items:
            st.error(f"🚨 พบ {len(urgent_items)} รายการต้องเคลมใน 7 วัน!")
            df_urg = pd.DataFrame(urgent_items).sort_values("_sort").drop(columns=["_sort"])
            st.dataframe(df_urg.style.format({"Amount": "{:,.2f}", "Value ($)": "${:,.2f}"}), use_container_width=True, hide_index=True)
        else:
            st.success("✅ สบายใจได้! ไม่มีรายการด่วนใน 7 วันนี้")

        # รายละเอียด
        st.subheader("📂 รายละเอียดรายกระเป๋า")
        for w_name, data in sorted(wallets_data.items(), key=lambda x: x[1]['total'], reverse=True):
            val = data['total'] * price_usd
            with st.expander(f"💼 {w_name} | {data['total']:,.2f} NIGHT (${val:,.2f})"):
                for addr, info in data['addrs'].items():
                    # หาอันที่ใกล้สุด
                    claims = sorted(info['claims'], key=lambda x: x['sort'])
                    nearest = claims[0] if claims else {}
                    
                    c1, c2, c3 = st.columns([3, 2, 2])
                    c1.markdown(f"**Address:** `{addr}`")
                    c2.markdown(f"**ยอดรวม:** {info['amt']:,.2f}")
                    c3.markdown(f"**เคลมถัดไป:** {nearest.get('countdown', '-')}")
                    
                    # ตารางย่อย
                    st.dataframe(pd.DataFrame(claims).drop(columns=['sort']), use_container_width=True, hide_index=True)
                    st.markdown("---")

        # Save CSV
        if active_list and not os.path.exists('active_wallets.csv'):
            pd.DataFrame(active_list).to_csv('active_wallets.csv', index=False)
            st.toast("บันทึก active_wallets.csv แล้ว!")
