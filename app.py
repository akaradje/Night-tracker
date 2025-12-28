import streamlit as st
import pandas as pd
import os
import requests
from datetime import datetime

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Offline Mode)", page_icon="🌙", layout="wide")

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
    """ดึงราคาตลาดปัจจุบัน"""
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

def is_urgent(status_str):
    """เช็คว่าต้องเคลมด่วนไหม (ภายใน 7 วัน หรือพร้อมเคลม)"""
    if "✅ เคลมได้เลย" in status_str:
        return True
    if "⏳" in status_str:
        try:
            days = int(status_str.split(" ")[1].replace("วัน", ""))
            return days <= 7
        except: return False
    return False

# ==============================================================================
# MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker (Local File Mode)")

if not os.path.exists(DATA_FILE):
    st.error(f"❌ ไม่พบไฟล์ {DATA_FILE} ในเครื่องครับ กรุณานำไฟล์มาวางในโฟลเดอร์เดียวกัน")
else:
    # 1. โหลดข้อมูล
    df = pd.read_csv(DATA_FILE)
    p_usd, p_thb = get_market_price()

    # 2. ประมวลผลข้อมูล
    # ยอดรวมทั้งหมด (Alloc)
    grand_total_alloc = df['Amount'].sum()
    
    # รายการที่เคลมแล้ว
    df_redeemed = df[df['Status'].str.contains("Claimed|Redeemed", na=False)]
    grand_total_redeemed = df_redeemed['Amount'].sum()
    
    # รายการที่เหลือ
    grand_total_remaining = grand_total_alloc - grand_total_redeemed
    
    # รายการด่วน
    df_urgent = df[df['Status'].apply(is_urgent)]

    # 3. แสดง Dashboard
    m1, m2, m3, m4 = st.columns(4)
    m1.markdown(f'<div class="metric-card"><h5>📦 ทั้งหมด (Alloc)</h5><h2>{grand_total_alloc:,.2f}</h2></div>', unsafe_allow_html=True)
    m2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคาปัจจุบัน (THB)</h5><h2>฿{p_thb:,.4f}</h2></div>', unsafe_allow_html=True)
    m3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าที่เหลือ</h5><h2>฿{grand_total_remaining * p_thb:,.2f}</h2></div>', unsafe_allow_html=True)
    m4.markdown(f'<div class="metric-card redeemed-card"><h5>✅ เคลมไปแล้ว</h5><h2>{grand_total_redeemed:,.2f}</h2></div>', unsafe_allow_html=True)

    # 4. แสดงรายการด่วน
    if not df_urgent.empty:
        st.error(f"🚨 แจ้งเตือน: พบ {len(df_urgent)} รายการต้องเคลม (ภายใน 7 วัน)")
        st.dataframe(df_urgent[["Wallet Name", "Address", "Amount", "Status", "Unlock Date"]], use_container_width=True, hide_index=True)

    # 5. แสดงประวัติการเคลม (Redeemed History)
    if not df_redeemed.empty:
        st.subheader("✅ รายการที่เคลมสำเร็จแล้ว (Redeemed History)")
        df_red_display = df_redeemed.copy()
        df_red_display['Value (THB)'] = df_red_display['Amount'] * p_thb
        st.dataframe(
            df_red_display[["Wallet Name", "Address", "Amount", "Unlock Date", "Value (THB)"]].style.format({"Amount": "{:,.2f}", "Value (THB)": "{:,.2f}"}),
            use_container_width=True, hide_index=True
        )

    # 6. รายละเอียดรายกระเป๋า (Group by Wallet Name)
    st.subheader("📂 รายละเอียดรายกระเป๋า")
    wallets = df['Wallet Name'].unique()
    for w in sorted(wallets):
        w_df = df[df['Wallet Name'] == w]
        w_remain = w_df[~w_df['Status'].str.contains("Claimed|Redeemed", na=False)]['Amount'].sum()
        
        with st.expander(f"💼 Wallet {w} | เหลือ: {w_remain:,.2f} NIGHT"):
            st.dataframe(
                w_df[["Address", "Amount", "Status", "Unlock Date"]].style.format({"Amount": "{:,.2f}"}),
                use_container_width=True, hide_index=True
            )

    st.caption(f"📊 ข้อมูลอ้างอิงจากไฟล์: {DATA_FILE} | อัปเดตราคาสดเมื่อ: {datetime.now().strftime('%H:%M:%S')}")
