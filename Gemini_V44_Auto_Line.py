# ==========================================
# Gemini V44 Aggressive Commander (GitHub Auto)
# ------------------------------------------
# 策略核心：三核並行 (BTC/ETH/SOL)
# 資金分配：40% BTC + 40% ETH + 20% SOL
# ------------------------------------------
# 核心邏輯 (The Trinity + Satellite):
# 1. BTC/ETH: 遵循 V37 黃金鐵律 (趨勢+估值+恐慌)
# 2. SOL (衛星): 必須同時滿足 "自身趨勢" AND "BTC 大哥趨勢" (雙重濾網)
# 3. 風控: 若 BTC 轉空，SOL 強制清倉 (避免山寨幣歸零風險)
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
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

# ==========================================
# 0. 環境檢查
# ==========================================
print("="*50)
print("🔍 V44 系統啟動...")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

def send_line_push(msg, is_test=False):
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        if is_test: print("❌ Token 未設定"); sys.exit(1)
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
        requests.post(url, headers=headers, json=payload)
        print("✅ LINE 發送成功")
        return True
    except Exception as e:
        print(f"❌ 發送失敗: {e}")
        if is_test: sys.exit(1)
        return False

# 連線測試
if not send_line_push("🔔 【系統測試】Gemini V44 (BTC/ETH/SOL) 正在啟動...", is_test=True):
    sys.exit(1)

# ==========================================
# 1. 數據獲取
# ==========================================
print("📥 下載 BTC, ETH, SOL, VIX 數據...")
START_DATE = '2020-01-01'
tickers = ['BTC-USD', 'ETH-USD', 'SOL-USD', '^VIX']

try:
    raw_data = yf.download(tickers, start=START_DATE, group_by='ticker', progress=False)
except Exception as e:
    print(f"❌ 數據下載失敗: {e}")
    sys.exit(1)

def process_data(ticker):
    df = pd.DataFrame()
    try:
        if ticker in raw_data.columns.levels[0]:
            df['Close'] = raw_data[ticker]['Close']
        else:
            if ticker == 'BTC-USD': df['Close'] = raw_data['Close']
    except:
        return None
    
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
df_sol = process_data('SOL-USD')

# ==========================================
# 2. 策略引擎 (V44 衛星風控版)
# ==========================================
def analyze_asset(df, asset_name, btc_bull_filter=True):
    # A. 指標計算
    df['SMA_140'] = df['Close'].rolling(window=140).mean()
    df['SMA_200'] = df['Close'].rolling(window=200).mean()
    df['Mayer'] = df['Close'] / df['SMA_200']
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    latest = df.iloc[-1]
    price = latest['Close']
    sma140 = latest['SMA_140']
    
    # --- 判斷邏輯 ---
    target_pct = 0.0
    status = ""
    reason = ""
    
    # 1. 衛星特殊風控 (針對 SOL)
    # 如果是 SOL，且 BTC 是熊市 (btc_bull_filter=False)，強制空倉
    if asset_name == "Solana" and not btc_bull_filter:
        return {
            'name': asset_name, 'price': price, 'sma140': sma140,
            'target': 0.0, 'status': "🛑 聯動避險", 
            'reason': "BTC 處於熊市，強制清倉山寨幣保命。",
            'is_bull': False
        }

    # 2. 一般邏輯
    is_bull = price > sma140
    is_panic = latest['VIX'] > 30
    is_overheated = latest['Mayer'] > 2.4
    is_oversold = latest['RSI'] < 30
    
    if is_panic:
        target_pct = 0.0
        status = "🌪️ 恐慌避險"
        reason = f"VIX ({latest['VIX']:.1f}) 過高，系統性風險。"
    elif is_overheated:
        target_pct = 0.5
        status = "⚠️ 過熱減碼"
        reason = f"Mayer ({latest['Mayer']:.2f}) 過熱。"
    elif is_bull:
        target_pct = 1.0
        status = "🚀 趨勢持有"
        reason = "站穩 140日均線。"
    else: # 熊市
        if is_oversold:
            target_pct = 0.3
            status = "⚡ 極限抄底"
            reason = f"RSI ({latest['RSI']:.1f}) 超賣搶反彈。"
        else:
            target_pct = 0.0
            status = "🛑 空倉觀望"
            reason = "跌破 140日均線。"
            
    return {
        'name': asset_name,
        'price': price,
        'sma140': sma140,
        'target': target_pct,
        'status': status,
        'reason': reason,
        'is_bull': is_bull,
        'vix': latest['VIX']
    }

# ==========================================
# 3. 生成戰報
# ==========================================
print("🧠 分析市場數據...")

# 1. 先分析 BTC (確認大哥狀態)
btc_res = analyze_asset(df_btc, "Bitcoin")
btc_is_bull = btc_res['is_bull']

# 2. 再分析 ETH 和 SOL (SOL 需參考 BTC 狀態)
eth_res = analyze_asset(df_eth, "Ethereum")
sol_res = analyze_asset(df_sol, "Solana", btc_bull_filter=btc_is_bull)

# 3. 計算權重 (40/40/20)
w_btc = btc_res['target'] * 0.40
w_eth = eth_res['target'] * 0.40
w_sol = sol_res['target'] * 0.20
w_cash = 1.0 - (w_btc + w_eth + w_sol)

# 4. 組合訊息
date_str = df_btc.index[-1].strftime('%Y-%m-%d')
next_check = (datetime.now() + timedelta(days=180)).strftime('%Y-%m-%d')

message = f"""
=========================
🏆 Gemini V44 三核戰情室
📅 {date_str} | VIX: {btc_res['vix']:.2f}
=========================

🟠 [BTC] (核心 40%)
   ${btc_res['price']:,.0f} (均線 ${btc_res['sma140']:,.0f})
   指令: {btc_res['status']} ({btc_res['target']*100:.0f}%)
   由: {btc_res['reason']}

🔵 [ETH] (核心 40%)
   ${eth_res['price']:,.0f} (均線 ${eth_res['sma140']:,.0f})
   指令: {eth_res['status']} ({eth_res['target']*100:.0f}%)
   由: {eth_res['reason']}

🟣 [SOL] (衛星 20%)
   ${sol_res['price']:,.2f} (均線 ${sol_res['sma140']:,.2f})
   指令: {sol_res['status']} ({sol_res['target']*100:.0f}%)
   由: {sol_res['reason']}

-------------------------
💼 [總資產建議配置]
   🟠 BTC : {w_btc*100:>4.1f}%
   🔵 ETH : {w_eth*100:>4.1f}%
   🟣 SOL : {w_sol*100:>4.1f}%
   🟢 Cash: {w_cash*100:>4.1f}%
-------------------------

💡 紀律提醒:
1. SOL 波動大，嚴格遵守 20% 上限。
2. 若 BTC 轉空 (🛑)，SOL 必須清倉，不可戀戰。
3. 買入分批，賣出果斷。

📅 [AI 健檢] 請於 {next_check} 檢查參數。
=========================
"""

print(message)
send_line_push(message)
