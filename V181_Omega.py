import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import json
from datetime import datetime, timedelta

# ==========================================
# 1. 參數與戰力池 (2026 展望版)
# ==========================================
# 讀取 LINE Messaging API 設定
LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')

# V181-2026 戰力池：包含 AI, Crypto, 量子計算, 重電, 散熱
STRATEGIC_POOL = {
    'CRYPTO': [
        'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 
        'DOGE-USD', 'SHIB-USD', 'PEPE-USD', # Memes
        'SUI-USD', 'APT-USD', 'NEAR-USD',   # High Performance L1
        'FET-USD', 'RNDR-USD', 'WLD-USD',   # AI Crypto
        'LINK-USD', 'AVAX-USD'
    ],
    'LEVERAGE': [
        'NVDL', 'SOXL', 'TQQQ', 'FNGU', 'TSLL', 
        'CONL', 'BITU', 'USD', 'TECL'
    ],
    'US_STOCKS': [
        'NVDA', 'AMD', 'TSLA', 'PLTR', 'MSTR', 'COIN',
        'SMCI', 'ARM', 'AVGO', 'META', 'AMZN', 'NFLX', 
        'LLY', 'VRTX', 'CRWD', 'PANW', 'ORCL', 'SHOP',
        'APP',  # AppLovin (AI AdTech)
        'IONQ', 'RGTI', # Quantum Computing
        'VRT', 'ANET', 'SNOW', 'COST'
    ],
    'TW_STOCKS': [
        '2330.TW', # 台積電
        '2454.TW', # 聯發科
        '2317.TW', # 鴻海
        '2382.TW', # 廣達
        '3231.TW', # 緯創
        '6669.TW', # 緯穎
        '3017.TW', # 奇鋐 (散熱)
        '1519.TW', # 華城 (重電)
        '1503.TW', # 士電 (重電)
        '2603.TW', '2609.TW' # 航運 (週期備選)
    ]
}

# 輔助：判斷資產類別
def get_asset_type(symbol):
    if "-USD" in symbol: return 'CRYPTO'
    if ".TW" in symbol: return 'TW'
    if symbol in STRATEGIC_POOL['LEVERAGE']: return 'LEVERAGE'
    return 'STOCK'

# ==========================================
# 2. 技術指標計算函式
# ==========================================
def calculate_indicators(df):
    if len(df) < 200: return None # 數據不足
    
    # 均線
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    
    # RSI (14)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 動能 (20日漲跌幅)
    df['Momentum'] = df['Close'].pct_change(periods=20)
    
    return df.iloc[-1] # 只傳回最新一天的數據

# ==========================================
# 3. 市場環境判讀 (V180 核心)
# ==========================================
def analyze_market_regime():
    tickers = ['^GSPC', 'BTC-USD', '^TWII']
    data = yf.download(tickers, period="300d", progress=False)['Close']
    
    regime = {}
    
    # 美股環境 (SPY > MA200 ?)
    spy_price = data['^GSPC'].iloc[-1]
    spy_ma200 = data['^GSPC'].rolling(200).mean().iloc[-1]
    regime['US_BULL'] = spy_price > spy_ma200
    
    # 幣圈環境 (BTC > MA200 ?)
    btc_price = data['BTC-USD'].iloc[-1]
    btc_ma200 = data['BTC-USD'].rolling(200).mean().iloc[-1]
    regime['CRYPTO_BULL'] = btc_price > btc_ma200
    
    # 台股環境 (TWII > MA60 ?)
    tw_price = data['^TWII'].iloc[-1]
    tw_ma60 = data['^TWII'].rolling(60).mean().iloc[-1]
    regime['TW_BULL'] = tw_price > tw_ma60
    
    return regime, spy_price, btc_price, tw_price

# ==========================================
# 4. 掃描戰力池
# ==========================================
def scan_pool(regime):
    all_tickers = []
    for cat in STRATEGIC_POOL:
        all_tickers.extend(STRATEGIC_POOL[cat])
    
    # 下載數據
    print("📥 下載數據中...")
    try:
        data = yf.download(all_tickers, period="250d", progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            closes = data['Close'].ffill()
        else:
            closes = data['Close'].ffill()
    except Exception as e:
        return f"數據下載失敗: {str(e)}", []

    candidates = []
    
    for symbol in all_tickers:
        try:
            if symbol not in closes.columns: continue
            
            series = closes[symbol].dropna()
            if len(series) < 200: continue
            
            df_temp = pd.DataFrame({'Close': series})
            last_row = calculate_indicators(df_temp)
            
            if last_row is None: continue
            
            price = last_row['Close']
            ma20 = last_row['MA20']
            ma50 = last_row['MA50']
            rsi = last_row['RSI']
            mom = last_row['Momentum']
            asset_type = get_asset_type(symbol)
            
            # --- V181 篩選機制 ---
            is_uptrend = price > ma20 and ma20 > ma50
            
            is_valid_env = True
            note = "滿倉"
            
            if asset_type == 'LEVERAGE' and not regime['US_BULL']:
                note = "⚠️半倉(SPY<年線)"
            if asset_type == 'CRYPTO' and not regime['CRYPTO_BULL']:
                note = "⚠️半倉(BTC<年線)"
            if asset_type == 'TW' and not regime['TW_BULL']:
                note = "⚠️小心(台股弱)"

            if is_uptrend and rsi < 80:
                candidates.append({
                    'Symbol': symbol,
                    'Score': mom,
                    'Price': price,
                    'RSI': rsi,
                    'Type': asset_type,
                    'Note': note
                })
                
        except Exception as e:
            continue

    candidates.sort(key=lambda x: x['Score'], reverse=True)
    return "Scan Complete", candidates

# ==========================================
# 5. 生成 LINE 訊息
# ==========================================
def generate_message(regime, candidates, spy_p, btc_p, tw_p):
    today = datetime.now().strftime('%Y-%m-%d')
    msg = f"🔥 V181 Omega 每日戰報 🔥\n{today}\n"
    msg += "━━━━━━━━━━━━━━\n"
    
    msg += "🌍 【大環境風向】\n"
    spy_st = "🟢牛市(全倉)" if regime['US_BULL'] else "🔴熊市(半倉避險)"
    btc_st = "🟢牛市(全倉)" if regime['CRYPTO_BULL'] else "🔴熊市(半倉避險)"
    tw_st = "🟢多頭" if regime['TW_BULL'] else "🔴空頭"
    
    msg += f"🇺🇸 美股: {spy_st} (SPY: {spy_p:.0f})\n"
    msg += f"₿ 幣圈: {btc_st} (BTC: {btc_p:.0f})\n"
    msg += f"🇹🇼 台股: {tw_st} (TWII: {tw_p:.0f})\n"
    msg += "━━━━━━━━━━━━━━\n"

    msg += "🏆 【今日動能榜 (買入參考)】\n"
    msg += "*(若手中空手，優先買前3名)*\n"
    
    top_picks = candidates[:3]
    reserves = candidates[3:5]
    
    rank = 1
    for item in top_picks:
        icon = "💎" if item['Type'] == 'CRYPTO' else "⚡" if item['Type'] == 'LEVERAGE' else "🏢"
        msg += f"{rank}. {icon} {item['Symbol']}\n"
        msg += f"   分數: {item['Score']*100:.1f}% | RSI: {item['RSI']:.1f}\n"
        msg += f"   現價: {item['Price']:.2f}\n"
        msg += f"   建議: {item['Note']} | 止損: -20%\n"
        rank += 1
        
    msg += "--------------------\n"
    msg += "💡 【候補名單】\n"
    for item in reserves:
        msg += f"• {item['Symbol']} (動能 {item['Score']*100:.1f}%)\n"
    
    msg += "━━━━━━━━━━━━━━\n"
    
    msg += "⚠️ 【拋物線收割警報】\n"
    msg += "*(若持有以下標的，請收緊停利至 10%)*\n"
    
    danger_found = False
    for item in candidates[:20]:
        if item['RSI'] > 80:
            msg += f"🔥 {item['Symbol']} (RSI: {item['RSI']:.1f})\n"
            danger_found = True
            
    if not danger_found:
        msg += "✅ 目前無過熱標的 (RSI < 80)\n"

    msg += "━━━━━━━━━━━━━━\n"
    msg += "🛡️ 操作口訣：\n"
    msg += "1. 買進後設定 20% 移動止損單。\n"
    msg += "2. 若出現 RSI>80 警報，改為 10%。\n"
    msg += "3. 若 SPY/BTC 轉熊，新單金額減半。\n"
    
    return msg

# ==========================================
# 6. 發送 LINE Message (Push API)
# ==========================================
def send_line_message(message):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("❌ 錯誤: 未設定 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_USER_ID")
        return
        
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            print("✅ LINE 訊息發送成功！")
        else:
            print(f"❌ 發送失敗: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ 連線錯誤: {e}")

# ==========================================
# 主程式
# ==========================================
if __name__ == "__main__":
    print("🚀 V181 策略引擎啟動...")
    
    # 1. 判斷環境
    regime, spy, btc, tw = analyze_market_regime()
    
    # 2. 掃描標的
    status, candidates = scan_pool(regime)
    
    if candidates:
        # 3. 生成訊息
        msg = generate_message(regime, candidates, spy, btc, tw)
        print(msg)
        
        # 4. 發送 LINE
        send_line_message(msg)
    else:
        print("⚠️ 無符合條件標的，或數據下載失敗。")
        send_line_message("⚠️ V181 系統訊息：今日無符合買入條件之標的，或數據源異常。")
