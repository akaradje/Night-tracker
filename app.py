import streamlit as st
import pandas as pd
import os
import requests
from datetime import datetime, timedelta

# --- 1. ตั้งค่าหน้าเว็บ ---
st.set_page_config(page_title="NIGHT Tracker (Dynamic 2025)", page_icon="🌙", layout="wide")

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
    .status-ready { color: #28a745; font-weight: bold; }
    .status-wait { color: #6c757d; }
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

def calculate_time_status(row):
    """คำนวณสถานะใหม่ตามเวลาปัจจุบัน"""
    # ถ้าสถานะเดิมบอกว่าเคลมแล้ว ให้คงไว้
    if "Claimed" in str(row['Status']):
        return "Claimed (เคลมแล้ว)", -999999999

    try:
        # แปลง Unlock Date เป็นรูปแบบที่คำนวณได้
        unlock_dt = pd.to_datetime(row['Unlock Date'], dayfirst=True)
        now = datetime.now()
        diff = unlock_dt - now
        total_sec = diff.total_seconds()

        if total_sec <= 0:
            return "✅ เคลมได้เลย", total_sec
        else:
            days = int(total_sec // 86400)
            hours = int((total_sec % 86400) // 3600)
            mins = int((total_sec % 3600) // 60)
            return f"⏳ {days}วัน {hours}ชม. {mins}นาที", total_sec
    except:
        return row['Status'], 999999999

# ==============================================================================
# MAIN UI
# ==============================================================================
st.title("🌙 NIGHT Tracker (Dynamic 2025 Status)")

if not os.path.exists(DATA_FILE):
    st.error(f"❌ ไม่พบไฟล์ {DATA_FILE}")
else:
    # 1. โหลดข้อมูลและราคาสด
    df = pd.read_csv(DATA_FILE)
    p_usd, p_thb = get_market_price()

    # 2. ปรับปรุงสถานะตามเวลาปัจจุบัน
    # คำนวณ Status และเพิ่มคอลัมน์ sort_order เพื่อเรียงลำดับเวลา
    df[['New_Status', 'sort_order']] = df.apply(lambda r: pd.Series(calculate_time_status(r)), axis=1)

    # 3. สรุปยอด Dashboard
    total_alloc = df['Amount'].sum()
    df_claimed = df[df['New_Status'] == "Claimed (เคลมแล้ว)"]
    total_redeemed = df_claimed['Amount'].sum()
    total_remaining = total_alloc - total_redeemed

    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(f'<div class="metric-card"><h5>📦 ทั้งหมด (Alloc)</h5><h2>{total_alloc:,.2f}</h2></div>', unsafe_allow_html=True)
    c2.markdown(f'<div class="metric-card price-card"><h5>📈 ราคาสด (THB)</h5><h2>฿{p_thb:,.4f}</h2></div>', unsafe_allow_html=True)
    c3.markdown(f'<div class="metric-card value-card"><h5>💰 มูลค่าที่เหลือ</h5><h2>฿{total_remaining * p_thb:,.2f}</h2></div>', unsafe_allow_html=True)
    c4.markdown(f'<div class="metric-card redeemed-card"><h5>✅ เคลมไปแล้ว</h5><h2>{total_redeemed:,.2f}</h2></div>', unsafe_allow_html=True)

    # 4. รายการที่ต้องเคลมด่วน (Ready to Claim)
    df_ready = df[df['New_Status'] == "✅ เคลมได้เลย"].copy()
    if not df_ready.empty:
        st.subheader("🚨 รายการที่ปลดล็อกแล้ว (พร้อมโอนออก)")
        df_ready['Value (THB)'] = df_ready['Amount'] * p_thb
        st.dataframe(
            df_ready[["Wallet Name", "Address", "Amount", "Value (THB)", "Unlock Date"]].style.format({"Amount": "{:,.2f}", "Value (THB)": "{:,.2f}"}),
            use_container_width=True, hide_index=True
        )

    # 5. ตารางภาพรวมรายกระเป๋า (เรียงตามเวลาปลดล็อก)
    st.subheader("📂 ตารางภาพรวม (เรียงตามเวลาปลดล็อก)")
    # กรองเอาเฉพาะที่ยังไม่เคลม
    df_pending = df[df['New_Status'] != "Claimed (เคลมแล้ว)"].sort_values('sort_order')
    
    if not df_pending.empty:
        # ปรับแต่งการแสดงผลสีใน Status
        def color_status(val):
            color = '#28a745' if '✅' in val else '#6c757d'
            return f'color: {color}; font-weight: bold;'

        st.dataframe(
            df_pending[["Wallet Name", "Address", "Amount", "New_Status", "Unlock Date"]].style.applymap(color_status, subset=['New_Status']).format({"Amount": "{:,.2f}"}),
            use_container_width=True, hide_index=True
        )

    # 6. ประวัติการเคลมสำเร็จ
    if not df_claimed.empty:
        with st.expander("✅ ดูประวัติรายการที่เคลมสำเร็จแล้ว"):
            st.dataframe(df_claimed[["Wallet Name", "Address", "Amount", "Unlock Date"]], use_container_width=True, hide_index=True)

    st.caption(f"🕒 อัปเดตล่าสุด: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')} | วันนี้คือวันที่ 28 ธันวาคม 2025")
