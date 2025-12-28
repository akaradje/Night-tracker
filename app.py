import streamlit as st
import pandas as pd
import os
import requests
from datetime import datetime

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (File Mode)", page_icon="🌙", layout="wide")

# ==============================================================================
# ⚙️ CONFIG
# ==============================================================================
DATA_FILE = "night_export.csv"
TOKEN_ADDRESS = "0xfe930c2d63aed9b82fc4dbc801920dd2c1a3224f"
MY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6ImZlMWU5MjhhLWE1YjMtNDc3OC04ZjE4LTFlODZhYjcyZTQ2NiIsIm9yZ0lkIjoiMjU3NjgzIiwidXNlcklkIjoiMjYxNjQyIiwidHlwZUlkIjoiMmNiZDhhNzUtNDk3Yi00ZTRhLWI2YmQtYmQzNTc4ODY4MjAyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjUyNzU1MzUsImV4cCI6NDkyMTAzNTUzNX0.sLbHogFDbXQ0TGm5VXPD7DWg1f22ztUnqR8LzfGAUoM"
REDEEM_URL = "https://redeem.midnight.gd/"

# CSS สำหรับตกแต่ง UI ให้เหมือนเดิม
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
</style>
""", unsafe_allow_html=True)

# --- Functions ---
def get_market_price():
    """ดึงราคาตลาดปัจจุบันมาคำนวณมูลค่าพอร์ต"""
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

def check_urgent(status_str):
    """ตรวจสอบว่ารายการนี้ต้องเคลมภายใน 7 วันหรือไม่"""
    if "✅" in status_str: return True
    if "⏳" in status_str:
        try:
            # ดึงตัวเลขจำนวนวันออกมาจากสตริง "⏳ Xวัน Yชม."
            days = int(status_str.split(" ")[1].replace("วัน", ""))
            return days <= 7
        except: return False
    return False

# ==============================================================================
# MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker (Local File Mode)")

if not os.path.exists(DATA_FILE):
    st.error(f"❌ ไม่พบไฟล์ {DATA_FILE} ในโฟลเดอร์เดียวกันกับ app.py")
    st.info("กรุณานำไฟล์ csv ที่ export มาวางในโฟลเดอร์ก่อนรันโปรแกรมครับ")
else:
    # 1. โหลดข้อมูลจากไฟล์ CSV
    df = pd.read_csv(DATA_FILE)
    
    # 2. ดึงราคาตลาดล่าสุด
    with st.spinner("..กำลังอัปเดตราคาสด.."):
        p_usd, p_thb = get_market_price()

    # 3. ประมวลผลข้อมูลสำหรับ Metrics
    total_alloc = df['Amount'].sum() #
    
    # กรองรายการที่เคลมแล้ว
    df_redeemed = df[df['Status'].str.contains("Claimed|Redeemed", na=False)]
    total_redeemed = df_redeemed['Amount'].sum()
    
    # รายการที่เหลือและรายการด่วน
    total_remaining = total_alloc - total_redeemed
    df_urgent = df[df['Status'].apply(check_urgent)]
    
    # 4. แสดงผล Metrics Dashboard
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f'<div class="metric-card"><h5>📦 ทั้งหมด (Alloc)</h5><h2>{total_alloc:,.2f}</h2></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคา (THB)</h5><h2>฿{p_thb:,.4f}</h2></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าที่เหลือ</h5><h2>฿{total_remaining * p_thb:,.2f}</h2></div>', unsafe_allow_html=True)
    m4.markdown(f'<div class="metric-card redeemed-card"><h5>✅ เคลมไปแล้ว</h5><h2>{total_redeemed:,.2f}</h2></div>', unsafe_allow_html=True)

    # 5. แสดงรายการด่วน (Urgent)
    if not df_urgent.empty:
        st.error(f"🚨 แจ้งเตือน: พบ {len(df_urgent)} รายการต้องเคลม (ภายใน 7 วัน)")
        st.dataframe(df_urgent[["Wallet Name", "Address", "Amount", "Status", "Unlock Date"]], use_container_width=True, hide_index=True)

    # 6. แสดงรายการที่เคลมสำเร็จ (History)
    if not df_redeemed.empty:
        st.subheader("✅ ประวัติการเคลมสำเร็จ (Redeemed History)")
        df_hist = df_redeemed.copy()
        df_hist['Current Value (THB)'] = df_hist['Amount'] * p_thb
        st.dataframe(
            df_hist[["Wallet Name", "Address", "Amount", "Unlock Date", "Current Value (THB)"]].style.format({"Amount": "{:,.2f}", "Current Value (THB)": "{:,.2f}"}),
            use_container_width=True, hide_index=True
        )

    # 7. รายละเอียดรายกระเป๋า (แยกตาม Wallet Name)
    st.subheader("📂 รายละเอียดรายกระเป๋า")
    wallets = sorted(df['Wallet Name'].unique())
    for w in wallets:
        w_df = df[df['Wallet Name'] == w]
        w_remain = w_df[~w_df['Status'].str.contains("Claimed|Redeemed", na=False)]['Amount'].sum()
        
        with st.expander(f"💼 Wallet {w} | เหลือที่ต้องเคลม: {w_remain:,.2f} NIGHT"):
            st.markdown(f"""<a href="{REDEEM_URL}" target="_blank" style="text-decoration:none;">
                <button style="width:100%; padding:10px; background-color:#6f42c1; color:white; border:none; border-radius:5px; cursor:pointer; font-weight:bold;">
                👉 ไปที่หน้ากดเคลม (Midnight)
                </button></a>""", unsafe_allow_html=True)
            st.dataframe(
                w_df[["Address", "Amount", "Status", "Unlock Date"]].style.format({"Amount": "{:,.2f}"}),
                use_container_width=True, hide_index=True
            )

    st.caption(f"📊 แสดงข้อมูลจากไฟล์: {DATA_FILE} | ข้อมูล ณ วันที่: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
