import streamlit as st
import pandas as pd
import os
import requests
from datetime import datetime

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Real-time Status)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG
# ==============================================================================
DATA_FILE = "night_export.csv"
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f"
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"

# CSS
st.markdown("""
<style>
    .metric-card {
        background-color: #f8f9fa; border: 1px solid #dee2e6;
        padding: 20px; border-radius: 10px; margin-bottom: 20px; text-align: center;
    }
    .price-card { background-color: #fff3cd; color: #856404; }
    .value-card { background-color: #d1e7dd; color: #0f5132; }
    .redeemed-card { background-color: #e2e3e5; color: #383d41; }
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

def calculate_current_status(row):
    """คำนวณสถานะใหม่ตามเวลาปัจจุบัน (28 ธ.ค. 2025)"""
    # ถ้าเคลมไปแล้ว ให้คงไว้เหมือนเดิม
    if "Claimed" in str(row['Status']):
        return "Claimed (เคลมแล้ว)"
    
    try:
        # แปลง Unlock Date เป็น datetime object
        unlock_dt = pd.to_datetime(row['Unlock Date'], dayfirst=True)
        now = datetime.now()
        delta = unlock_dt - now
        
        if delta.total_seconds() <= 0:
            return "✅ เคลมได้เลย"
        else:
            days = delta.days
            hours = delta.seconds // 3600
            return f"⏳ {days}วัน {hours}ชม."
    except:
        return row['Status']

# ==============================================================================
# MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker (Dynamic Status)")

if not os.path.exists(DATA_FILE):
    st.error(f"❌ ไม่พบไฟล์ {DATA_FILE}")
else:
    # 1. โหลดข้อมูล
    df = pd.read_csv(DATA_FILE)
    p_usd, p_thb = get_market_price()

    # 2. ปรับปรุง Status ตามเวลาปัจจุบัน
    df['Status'] = df.apply(calculate_current_status, axis=1)

    # 3. ประมวลผล Metrics
    total_alloc = df['Amount'].sum()
    df_redeemed = df[df['Status'] == "Claimed (เคลมแล้ว)"]
    total_redeemed = df_redeemed['Amount'].sum()
    total_remaining = total_alloc - total_redeemed
    
    # รายการด่วน (เคลมได้เลย หรือ เหลือไม่เกิน 7 วัน)
    df_urgent = df[df['Status'].str.contains("✅|⏳ 0วัน|⏳ 1วัน|⏳ 2วัน|⏳ 3วัน|⏳ 4วัน|⏳ 5วัน|⏳ 6วัน|⏳ 7วัน", na=False)]

    # 4. แสดง Dashboard
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f'<div class="metric-card"><h5>📦 ทั้งหมด (Alloc)</h5><h2>{total_alloc:,.2f}</h2></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคา (THB)</h5><h2>฿{p_thb:,.4f}</h2></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าที่เหลือ</h5><h2>฿{total_remaining * p_thb:,.2f}</h2></div>', unsafe_allow_html=True)
    m4.markdown(f'<div class="metric-card redeemed-card"><h5>✅ เคลมไปแล้ว</h5><h2>{total_redeemed:,.2f}</h2></div>', unsafe_allow_html=True)

    # 5. ตารางรายการด่วน
    if not df_urgent.empty:
        st.error(f"🚨 แจ้งเตือน: พบ {len(df_urgent)} รายการที่ต้องเคลม/กำลังจะถึงกำหนด")
        st.dataframe(df_urgent[["Wallet Name", "Address", "Amount", "Status", "Unlock Date"]], use_container_width=True, hide_index=True)

    # 6. ประวัติการเคลม
    if not df_redeemed.empty:
        st.subheader("✅ รายการที่เคลมสำเร็จแล้ว")
        df_red_view = df_redeemed.copy()
        df_red_view['Value (THB)'] = df_red_view['Amount'] * p_thb
        st.dataframe(df_red_view[["Wallet Name", "Address", "Amount", "Unlock Date", "Value (THB)"]].style.format({"Amount": "{:,.2f}", "Value (THB)": "{:,.2f}"}), use_container_width=True, hide_index=True)

    # 7. รายละเอียดรายกระเป๋า
    st.subheader("📂 รายละเอียดรายกระเป๋า (อัปเดตเวลาล่าสุด)")
    for w in sorted(df['Wallet Name'].unique()):
        w_df = df[df['Wallet Name'] == w]
        w_remain = w_df[w_df['Status'] != "Claimed (เคลมแล้ว)"]['Amount'].sum()
        with st.expander(f"💼 Wallet {w} | เหลือ: {w_remain:,.2f} NIGHT"):
            st.dataframe(w_df[["Address", "Amount", "Status", "Unlock Date"]].style.format({"Amount": "{:,.2f}"}), use_container_width=True, hide_index=True)

    st.caption(f"🕒 วันนี้: {datetime.now().strftime('%d/%m/%Y %H:%M')} | ข้อมูลอ้างอิงจาก Unlock Date ในไฟล์ {DATA_FILE}")
