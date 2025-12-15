# ==========================================
# Gemini V41 Hybrid Commander (GitHub Auto) - Debug Mode
# ------------------------------------------
# 策略核心：雙核並行 (BTC/ETH Dual-Core)
# 新增功能：
# 1. 啟動時立即發送測試訊息 (確認連線)
# 2. 印出 Token 前五碼 (確認變數讀取)
# 3. 強制詳細輸出錯誤代碼
# 4. 【新增】AI 健檢日期提醒 (半年後)
# ==========================================

import os
import sys
import requests
import json
import warnings
import yfinance as yf
import pandas as pd
import numpy as np
from stable_baselines3 import PPO
import gymnasium as gym
from gymnasium import spaces
from datetime import datetime, timedelta # 引入時間計算

warnings.filterwarnings("ignore")

# ==========================================
# 0. 環境檢查與連線測試 (Debug Section)
# ==========================================
print("="*50)
print("🔍 系統自我診斷開始...")

# 從環境變數讀取 LINE 設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

# 除錯：檢查 Token 是否讀取成功
if LINE_CHANNEL_ACCESS_TOKEN:
    print(f"✅ Token 讀取成功！前五碼: {LINE_CHANNEL_ACCESS_TOKEN[:5]}...")
else:
    print("❌ 嚴重錯誤：Token 是空的！(None)")
    print("   -> 請檢查 GitHub Settings > Secrets 是否名稱打錯？(必須是 LINE_CHANNEL_ACCESS_TOKEN)")

if LINE_USER_ID:
    print(f"✅ UserID 讀取成功！User ID: {LINE_USER_ID}")
else:
    print("❌ 嚴重錯誤：User ID 是空的！(None)")
    print("   -> 請檢查 GitHub Settings > Secrets 是否名稱打錯？(必須是 LINE_USER_ID)")

# 定義發送函數 (含除錯資訊)
def send_line_push(msg, is_test=False):
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("❌ 無法發送：缺少 Token 或 User ID")
        return False
    
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": msg}]
    }
    
    try:
        print(f"📡 正在發送{'測試' if is_test else '正式'}訊息...")
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            print("✅ 發送成功！(HTTP 200)")
            return True
        else:
            print(f"❌ 發送失敗！狀態碼: {response.status_code}")
            print(f"❌ 錯誤回應: {response.text}")
            # 如果是測試階段失敗，強制報錯讓 GitHub 亮紅燈
            if is_test: sys.exit(1)
            return False
            
    except Exception as e:
        print(f"❌ 連線錯誤: {e}")
        if is_test: sys.exit(1)
        return False

# --- 立即執行連線測試 ---
print("\n🧪 正在執行 LINE 連線測試...")
test_msg = "🔔 【系統測試】Gemini V41 雙核指揮官正在啟動...\n如果您看到這則訊息，代表連線設定完全正確！\nAI 正在下載數據並訓練模型，請稍候約 3-5 分鐘..."
success = send_line_push(test_msg, is_test=True)

if not success:
    print("⛔ 測試失敗，程式終止。請檢查 Secrets 設定。")
    # 如果沒讀到 Token，這裡會讓程式停下，避免浪費資源跑後面的 AI
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        sys.exit(1)
else:
    print("🎉 測試通過！開始執行量化分析...")
print("="*50)


# ==========================================
# 1. 數據獲取
# ==========================================
print("📥 正在獲取全球金融數據 (BTC, ETH, VIX)...")
START_DATE = '2020-01-01'
tickers = ['BTC-USD', 'ETH-USD', '^VIX']

try:
    raw_data = yf.download(tickers, start=START_DATE, group_by='ticker', progress=False)
except Exception as e:
    print(f"❌ 數據下載失敗: {e}")
    import sys; sys.exit(1)

# 整理數據函數
def process_data(ticker):
    df = pd.DataFrame()
    try:
        if ticker in raw_data.columns.levels[0]:
            df['Close'] = raw_data[ticker]['Close']
        else:
            # Fallback for single ticker structure
            if ticker == 'BTC-USD': df['Close'] = raw_data['Close']
    except:
        return None
    
    # 填補 VIX
    try:
        if '^VIX' in raw_data.columns.levels[0]:
            df['VIX'] = raw_data['^VIX']['Close']
        else:
            df['VIX'] = 20.0
    except:
        df['VIX'] = 20.0

    df.ffill(inplace=True)
    df.dropna(inplace=True)
    return df

df_btc = process_data('BTC-USD')
df_eth = process_data('ETH-USD')

# ==========================================
# 2. 策略引擎 (V37 黃金鐵律)
# ==========================================
def analyze_asset(df, asset_name):
    # A. 計算指標
    # 1. 趨勢 (SMA 140)
    df['SMA_140'] = df['Close'].rolling(window=140).mean()
    
    # 2. 估值 (Mayer)
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['Mayer'] = df['Close'] / df['SMA_200']
    
    # 3. 動能 (RSI)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # B. 執行判斷
    latest = df.iloc[-1]
    price = latest['Close']
    sma140 = latest['SMA_140']
    mayer = latest['Mayer']
    vix = latest['VIX']
    rsi = latest['RSI']
    
    signal = "HOLD"
    target_pct = 0.0
    icon = ""
    reason = ""
    
    # 邏輯樹
    is_bull = price > sma140
    is_panic = vix > 30
    is_overheated = mayer > 2.4
    is_oversold = rsi < 30
    
    if is_panic:
        signal = "ESCAPE"
        target_pct = 0.0
        icon = "🌪️"
        reason = f"VIX ({vix:.2f}) 過高，系統性風險，強制空倉。"
        
    elif is_overheated:
        signal = "TRIM"
        target_pct = 0.5
        icon = "⚠️"
        reason = f"Mayer ({mayer:.2f}) 過熱，減碼保平安。"
        
    elif is_bull:
        signal = "FULL"
        target_pct = 1.0 
        icon = "🚀"
        reason = f"站穩 140日均線 (${sma140:,.0f})，趨勢向上。"
        
    else: # 熊市
        if is_oversold:
            signal = "SNIPE"
            target_pct = 0.3 # 搶反彈
            icon = "⚡"
            reason = f"熊市超賣 (RSI {rsi:.1f})，小倉位搶反彈。"
        else:
            signal = "EMPTY"
            target_pct = 0.0
            icon = "🛑"
            reason = f"跌破 140日均線 (${sma140:,.0f})，空倉觀望。"
            
    return {
        'asset': asset_name,
        'price': price,
        'sma140': sma140,
        'target': target_pct,
        'icon': icon,
        'reason': reason,
        'vix': vix
    }

# ==========================================
# 3. 生成雙核戰報
# ==========================================
print("🧠 正在分析雙核配置 (BTC + ETH)...")
result_btc = analyze_asset(df_btc, "Bitcoin")
result_eth = analyze_asset(df_eth, "Ethereum")

# 計算最終配置 (50/50 權重)
final_btc_weight = result_btc['target'] * 0.5
final_eth_weight = result_eth['target'] * 0.5
final_cash_weight = 1.0 - (final_btc_weight + final_eth_weight)

latest_date = df_btc.index[-1].strftime('%Y-%m-%d')

# 計算下次健檢日期 (從今天起算 180 天)
next_check_date = (datetime.now() + timedelta(days=180)).strftime('%Y-%m-%d')

message = f"""
=========================
🏆 Gemini V41 雙核指揮官
📅 日期: {latest_date}
=========================

🟠 [BTC 分部]
   現價: ${result_btc['price']:,.0f} (MA140: ${result_btc['sma140']:,.0f})
   指令: {result_btc['icon']} 建議倉位 {result_btc['target']*100:.0f}%
   理由: {result_btc['reason']}

🔵 [ETH 分部]
   現價: ${result_eth['price']:,.0f} (MA140: ${result_eth['sma140']:,.0f})
   指令: {result_eth['icon']} 建議倉位 {result_eth['target']*100:.0f}%
   理由: {result_eth['reason']}

🌪️ 恐慌指數 (VIX): {result_btc['vix']:.2f}

-------------------------
💼 [總資產配置建議] (Target)
   🟠 BTC 持倉: {final_btc_weight*100:>4.1f}%
   🔵 ETH 持倉: {final_eth_weight*100:>4.1f}%
   🟢 現金保留: {final_cash_weight*100:>4.1f}%
-------------------------

💡 操作備忘錄 (紀律):
1. 【買入】若建議大幅加倉 (如 BTC 0% -> 45%)，請分 3-5 天分批買進，平滑成本。
2. 【賣出】若建議某幣種空倉 (🛑)，請勿猶豫，一次果斷賣出該幣種 (避險優先)。
3. 若建議佔比與您帳戶實際佔比差距 > 5%，才進行再平衡 (省手續費)。

📅 [AI 系統健檢提醒]
   為了確保策略參數適應最新市場，請於 {next_check_date} 重新檢視本程式。
=========================
"""

# 印出並發送
print(message)
send_line_push(message)
