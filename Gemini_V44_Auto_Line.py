# ==========================================
# Gemini V44 Auto Commander (三核激進版)
# ------------------------------------------
# 策略核心：40% BTC + 40% ETH + 20% SOL
# ------------------------------------------
# 策略邏輯 (The Trinity + Satellite V44):
# 1. 趨勢鐵律: 各自價格 < SMA 140 -> 空倉避險
# 2. 衛星風控: SOL 買入的前提是 BTC 必須處於牛市 (大哥濾網)
# 3. 估值濾網: Mayer > 2.4 或 VIX > 30 -> 嚴格減碼/空倉
# ==========================================

import sys
import subprocess
import warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import requests
import time

warnings.filterwarnings("ignore")

# 0. 環境檢查與 LINE 設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

def send_line_push(msg):
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("❌ 未設定 LINE Token，僅顯示於螢幕。")
        print(msg)
        return
    
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
        requests.post(url, headers=headers, json=payload)
        print("✅ LINE 通知已發送")
    except Exception as e:
        print(f"❌ 發送失敗: {e}")

# 自動安裝必要套件 (yfinance)
def install(package):
    try:
        __import__(package)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    import yfinance as yf
except ImportError:
    install("yfinance")
    import yfinance as yf

# ==========================================
# 1. 數據中心
# ==========================================
print("\n[1/3] 正在連線全球數據庫 (BTC, ETH, SOL)...")

START_DATE = '2020-01-01' 
tickers = ['BTC-USD', 'ETH-USD', 'SOL-USD', '^VIX']

try:
    raw_data = yf.download(tickers, start=START_DATE, group_by='ticker', progress=False)
except Exception as e:
    # 這裡的錯誤處理不應包含 send_line_push，因為是測試環境
    print(f"❌ 數據下載失敗！請檢查網路。錯誤: {e}")
    sys.exit()

def get_data(ticker, vix_data):
    df = pd.DataFrame()
    try:
        if ticker in raw_data.columns.levels[0]:
            df['Close'] = raw_data[ticker]['Close']
        else:
            if ticker == 'BTC-USD': df['Close'] = raw_data['Close']
    except:
        return None
    
    df['VIX'] = vix_data
    df.ffill(inplace=True)
    df.dropna(inplace=True)
    return df

# 處理 VIX
try:
    if '^VIX' in raw_data.columns.levels[0]:
        vix_series = raw_data['^VIX']['Close']
    else:
        vix_series = pd.Series(20, index=raw_data.index)
except:
    vix_series = pd.Series(20, index=raw_data.index)

df_btc = get_data('BTC-USD', vix_series)
df_eth = get_data('ETH-USD', vix_series)
df_sol = get_data('SOL-USD', vix_series)

# ==========================================
# 2. 策略引擎 (V44 Logic)
# ==========================================
def analyze_asset(df, asset_name, btc_trend=True):
    # A. 計算指標
    df['SMA_140'] = df['Close'].rolling(window=140).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['Mayer'] = df['Close'] / df['SMA_200']
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    latest = df.iloc[-1]
    
    # --- 判斷邏輯 ---
    price = latest['Close']
    sma140 = latest['SMA_140']
    mayer = latest['Mayer']
    vix = latest['VIX']
    rsi = latest['RSI']
    
    target_pct = 0.0
    status = ""
    reason = ""
    
    is_bull = price > sma140
    is_panic = vix > 30
    is_overheated = mayer > 2.4
    is_oversold = rsi < 30
    
    # [SOL 專屬風控] 大哥濾網
    if asset_name == "Solana" and not btc_trend:
        return {
            'name': asset_name, 'price': price, 'sma140': sma140,
            'target_pct': 0.0, 'status': "🛑 聯動避險", 
            'reason': "BTC 轉入熊市，強制空倉保護。", 'is_bull': False, 'vix': vix
        }

    # 一般三層判斷 (恐慌 > 過熱 > 趨勢 > 抄底)
    if is_panic:
        target_pct = 0.0
        status = "🌪️ 恐慌避險"
        reason = f"VIX ({vix:.2f}) 過高，系統性風險。"
    elif is_overheated:
        target_pct = 0.5
        status = "⚠️ 過熱減碼"
        reason = f"Mayer ({mayer:.2f}) 過熱。"
    elif is_bull:
        target_pct = 1.0
        status = "🚀 趨勢持有"
        reason = "Price > SMA140"
    else: # 熊市
        if is_oversold:
            target_pct = 0.3
            status = "⚡ 極限抄底"
            reason = f"RSI < 30"
        else:
            target_pct = 0.0
            status = "🛑 空倉觀望"
            reason = "Price < SMA140"
            
    return {
        'name': asset_name,
        'price': price,
        'sma140': sma140,
        'target_pct': target_pct,
        'status': status,
        'reason': reason,
        'is_bull': is_bull,
        'vix': vix
    }

# ==========================================
# 3. 生成投資組合建議
# ==========================================
print("[2/3] AI 正在分析三核配置 (40/40/20)...")

# 1. 先分析 BTC (大哥狀態)
btc_signal = analyze_asset(df_btc, "Bitcoin")
btc_is_bull = btc_signal['is_bull']

# 2. 分析 ETH (核心) 和 SOL (衛星)
eth_signal = analyze_asset(df_eth, "Ethereum")
sol_signal = analyze_asset(df_sol, "Solana", btc_trend=btc_is_bull)

# 3. 計算權重 (V44 激進配置: 40 / 40 / 20)
w_btc = btc_signal['target_pct'] * 0.40
w_eth = eth_signal['target_pct'] * 0.40
w_sol = sol_signal['target_pct'] * 0.20
w_cash = 1.0 - (w_btc + w_eth + w_sol)

latest_date = df_btc.index[-1].strftime('%Y-%m-%d')
vix_level = btc_signal['vix']

# 4. 組合訊息
message = f"""
=========================
🏆 Gemini V44 激進三核戰報
📅 日期: {latest_date} | VIX: {vix_level:.2f}
=========================

🟠 [Bitcoin] (核心 40%)
   ${btc_signal['price']:,.0f} (均線 ${btc_signal['sma140']:,.0f})
   指令: {btc_signal['status']} ({btc_signal['target_pct']*100:.0f}%)
   理由: {btc_signal['reason']}

🔵 [Ethereum] (核心 40%)
   ${eth_signal['price']:,.0f} (均線 ${eth_signal['sma140']:,.0f})
   指令: {eth_signal['status']} ({eth_signal['target_pct']*100:.0f}%)
   理由: {eth_signal['reason']}

🟣 [Solana] (衛星 20%)
   ${sol_signal['price']:,.2f} (均線 ${sol_signal['sma140']:,.2f})
   指令: {sol_signal['status']} ({sol_signal['target_pct']*100:.0f}%)
   理由: {sol_signal['reason']}

-------------------------
💼 [總資產建議配置] (Target Allocation)
   🟠 BTC : {w_btc*100:>4.1f}%
   🔵 ETH : {w_eth*100:>4.1f}%
   🟣 SOL : {w_sol*100:>4.1f}%
   🟢 Cash: {w_cash*100:>4.1f}%
-------------------------

💡 紀律提醒:
1. SOL 波動大，嚴格遵守 20% 上限。
2. 若 SOL 佔總資產 > 25%，請強制賣出多餘部分 (收割)。
3. 熊市紀律：BTC 轉空 (🛑) 時，SOL 必須清倉，不可戀戰。

📅 [AI 健檢] 請於 {datetime.now() + timedelta(days=180)} 檢查參數。
=========================
"""

# 4. 發送報告
print("[3/3] 發送戰報...")
send_line_push(message)
