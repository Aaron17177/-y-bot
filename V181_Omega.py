import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import json
from datetime import datetime, timedelta

# ==========================================
# 1. 參數與戰力池 (V181-2026 戰略升級版)
# ==========================================
# 讀取 LINE Messaging API 設定
LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')

# V181-2026 戰力池：加入對沖、軍工、原物料、新興市場
STRATEGIC_POOL = {
    'CRYPTO': [
        'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 
        'DOGE-USD', 'SHIB-USD', 
        'PEPE24478-USD', # Pepe (Yahoo代碼)
        'APT-USD', 'NEAR-USD', 'SUI-USD', # 高性能公鏈
        'FET-USD', 'RENDER-USD', 'WLD-USD', # AI Crypto
        'LINK-USD', 'AVAX-USD'
    ],
    'LEVERAGE': [
        # --- 科技進攻 ---
        'NVDL', 'SOXL', 'TQQQ', 'FNGU', 'TSLL', 
        'CONL', 'BITU', 'USD', 'TECL',
        # --- 全天候防禦與對沖 (V183概念導入) ---
        'UVXY', # 1.5x 恐慌指數 (黑天鵝專用)
        'TMF',  # 3x 美債 (經濟衰退/降息專用)
        'ERX',  # 2x 能源 (通膨/油價上漲)
        'NUGT', # 2x 金礦 (貨幣貶值/避險)
        'LABU', # 3x 生技 (降息受惠/獨立行情)
        'YINN', # 3x 中國 (估值修復/資金輪動)
        'INDL'  # 2x 印度 (人口紅利/供應鏈轉移)
    ],
    'US_STOCKS': [
        # --- AI 與 科技巨頭 ---
        'NVDA', 'AMD', 'TSLA', 'PLTR', 'MSTR', 'COIN',
        'SMCI', 'ARM', 'AVGO', 'META', 'AMZN', 'NFLX', 
        'CRWD', 'PANW', 'ORCL', 'SHOP', 'VRT', 'ANET', 'SNOW', 
        'APP',  # AppLovin (AI廣告)
        'IONQ', 'RGTI', # 量子計算
        # --- 實體經濟與防禦 ---
        'LLY', 'VRTX', # 醫藥雙雄
        'COST', # 消費防禦
        'RTX', 'LMT', # 軍工國防 (地緣政治避險)
        'COPX' # 銅礦ETF (AI基建/電力需求)
    ],
    'TW_STOCKS': [
        '2330.TW', # 台積電
        '2454.TW', # 聯發科
        '2317.TW', # 鴻海
        '2382.TW', # 廣達
        '3231.TW', # 緯創
        '6669.TW', # 緯穎
        '3017.TW', # 奇鋐
        '1519.TW', # 華城 (重電)
        '1503.TW', # 士電 (重電)
        '2603.TW', '2609.TW' # 航運
    ]
}

def get_asset_type(symbol):
    if "-USD" in symbol: return 'CRYPTO'
    if ".TW" in symbol: return 'TW'
    if symbol in STRATEGIC_POOL['LEVERAGE']: return 'LEVERAGE'
    return 'STOCK'

# ==========================================
# 2. 技術指標計算
# ==========================================
def calculate_indicators(df):
    if len(df) < 200: return None
    
    df = df.copy()
    df = df.sort_index()
    
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 動能：20日漲跌幅
    df['Momentum'] = df['Close'].pct_change(periods=20)
    
    # 取最後一筆「有效」數據 (Drop NA)
    valid_df = df.dropna(subset=['MA200', 'RSI'])
    
    if valid_df.empty:
        return df.iloc[-1] 
        
    return valid_df.iloc[-1]

# ==========================================
# 3. 市場環境判讀 (獨立序列修正版)
# ==========================================
def analyze_market_regime():
    # 下載數據，使用 auto_adjust=True 確保價格連續性
    tickers = ['SPY', 'BTC-USD', '^TWII']
    try:
        data = yf.download(tickers, period="365d", progress=False, auto_adjust=True)
        
        # 處理 MultiIndex 列名
        if isinstance(data.columns, pd.MultiIndex):
            try:
                df_close = data['Close']
            except KeyError:
                df_close = data
        else:
            df_close = data

        regime = {}
        
        # 1. 美股 SPY
        try:
            spy_series = df_close['SPY'].dropna()
            if len(spy_series) > 200:
                spy_price = spy_series.iloc[-1]
                spy_ma200 = spy_series.rolling(200).mean().iloc[-1]
                regime['US_BULL'] = spy_price > spy_ma200
            else:
                spy_price = 0
                regime['US_BULL'] = False
        except KeyError:
            spy_price = 0
            regime['US_BULL'] = False

        # 2. 幣圈 BTC
        try:
            btc_series = df_close['BTC-USD'].dropna()
            if len(btc_series) > 200:
                btc_price = btc_series.iloc[-1]
                btc_ma200 = btc_series.rolling(200).mean().iloc[-1]
                regime['CRYPTO_BULL'] = btc_price > btc_ma200
            else:
                btc_price = 0
                regime['CRYPTO_BULL'] = False
        except KeyError:
            btc_price = 0
            regime['CRYPTO_BULL'] = False
            
        # 3. 台股 TWII
        try:
            tw_series = df_close['^TWII'].dropna()
            if len(tw_series) > 60:
                tw_price = tw_series.iloc[-1]
                tw_ma60 = tw_series.rolling(60).mean().iloc[-1]
                regime['TW_BULL'] = tw_price > tw_ma60
            else:
                tw_price = 0
                regime['TW_BULL'] = False
        except KeyError:
            tw_price = 0
            regime['TW_BULL'] = False
        
        return regime, spy_price, btc_price, tw_price
        
    except Exception as e:
        print(f"環境數據下載失敗: {e}")
        return {'US_BULL': False, 'CRYPTO_BULL': False, 'TW_BULL': False}, 0, 0, 0

# ==========================================
# 4. 掃描戰力池
# ==========================================
def scan_pool(regime):
    all_tickers = []
    for cat in STRATEGIC_POOL:
        all_tickers.extend(STRATEGIC_POOL[cat])
    
    print("📥 下載戰力池數據中...")
    try:
        data = yf.download(all_tickers, period="300d", progress=False, auto_adjust=True)
        
        if isinstance(data.columns, pd.MultiIndex):
            try:
                closes = data['Close']
            except KeyError:
                closes = data.ffill() # Fallback
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
            
            note = "滿倉"
            
            # 環境濾網 (決定倉位建議)
            # 修正：對沖資產 (UVXY, TMF, NUGT, ERX) 不受熊市限制，反而可能是熊市主力
            is_hedge_asset = symbol in ['UVXY', 'TMF', 'NUGT', 'ERX']
            
            if asset_type == 'LEVERAGE' and not is_hedge_asset:
                if not regime.get('US_BULL', False): note = "⚠️半倉(SPY<年線)"
            
            if asset_type == 'CRYPTO':
                if not regime.get('CRYPTO_BULL', False): note = "⚠️半倉(BTC<年線)"
            
            if asset_type == 'TW':
                if not regime.get('TW_BULL', False): note = "⚠️小心(台股弱)"

            # 買入資格確認
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
# 5. 生成與發送 LINE 訊息
# ==========================================
def send_line_message(message):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("❌ 錯誤: 未設定 LINE Secrets")
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

def generate_report(regime, candidates, spy_p, btc_p, tw_p):
    today = datetime.now().strftime('%Y-%m-%d')
    msg = f"🔥 V181 Omega 每日戰報 🔥\n{today}\n"
    msg += "━━━━━━━━━━━━━━\n"
    
    spy_disp = f"{spy_p:.0f}" if spy_p > 0 else "N/A"
    btc_disp = f"{btc_p:.0f}" if btc_p > 0 else "N/A"
    tw_disp = f"{tw_p:.0f}" if tw_p > 0 else "N/A"
    
    spy_st = "🟢牛市(全倉)" if regime.get('US_BULL', False) else "🔴熊市(半倉避險)"
    btc_st = "🟢牛市(全倉)" if regime.get('CRYPTO_BULL', False) else "🔴熊市(半倉避險)"
    tw_st = "🟢多頭" if regime.get('TW_BULL', False) else "🔴空頭"
    
    msg += f"🇺🇸 美股: {spy_st} (SPY: {spy_disp})\n"
    msg += f"₿ 幣圈: {btc_st} (BTC: {btc_disp})\n"
    msg += f"🇹🇼 台股: {tw_st} (TWII: {tw_disp})\n"
    msg += "━━━━━━━━━━━━━━\n"

    msg += "🏆 【今日動能榜 (買入參考)】\n"
    msg += "*(若手中空手，優先買前3名)*\n"
    
    top_picks = candidates[:3]
    reserves = candidates[3:5]
    
    rank = 1
    for item in top_picks:
        icon = "💎" if item['Type'] == 'CRYPTO' else "⚡" if item['Type'] == 'LEVERAGE' else "🏢"
        price_fmt = f"{item['Price']:.0f}" if item['Type'] == 'TW' else f"{item['Price']:.2f}"
        
        msg += f"{rank}. {icon} {item['Symbol']}\n"
        msg += f"   分數: {item['Score']*100:.1f}% | RSI: {item['RSI']:.1f}\n"
        msg += f"   現價: {price_fmt}\n"
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
    for item in candidates[:25]:
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
# 主程式
# ==========================================
if __name__ == "__main__":
    print("🚀 V181 策略引擎啟動...")
    
    regime, spy, btc, tw = analyze_market_regime()
    status, candidates = scan_pool(regime)
    
    if candidates:
        msg = generate_report(regime, candidates, spy, btc, tw)
        print(msg)
        send_line_message(msg)
    else:
        print("⚠️ 無符合條件標的，或數據下載失敗。")
        send_line_message("⚠️ V181 系統訊息：今日無符合買入條件之標的，或數據源異常。")
