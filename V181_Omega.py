import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import csv
from datetime import datetime

# ==========================================
# 1. 參數與設定
# ==========================================
LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
PORTFOLIO_FILE = 'portfolio.csv'
MIN_DAILY_VOLUME_USD = 500000  # 最低日成交額限制 (50萬美金 / 約1600萬台幣)

# V181-2026 戰力池
STRATEGIC_POOL = {
    'CRYPTO': [
        'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 
        'DOGE-USD', 'SHIB-USD', 
        'PEPE24478-USD', 'APT-USD', 'NEAR-USD', 'SUI20947-USD',
        'FET-USD', 'RENDER-USD', 'WLD-USD', 'TAO22974-USD',
        'LINK-USD', 'AVAX-USD',
        'BCH-USD', 'ZEC-USD', 'DASH-USD',
        'BONK-USD', 'HYPE-USD'
    ],
    'LEVERAGE': [
        'NVDL', 'SOXL', 'TQQQ', 'FNGU', 'TSLL', 
        'CONL', 'BITU', 'USD', 'TECL',
        'MSTU', 'LABU'
    ],
    'US_STOCKS': [
        'NVDA', 'AMD', 'TSLA', 'PLTR', 'MSTR', 'COIN',
        'SMCI', 'ARM', 'AVGO', 'META', 'AMZN', 'NFLX', 
        'LLY', 'VRTX', 'CRWD', 'PANW', 'ORCL', 'SHOP',
        'APP', 'IONQ', 'RGTI', 'RKLB', 'VRT', 'ANET', 'SNOW', 'COST',
        'VST', 'MU', 'AMAT', 'LRCX', 'ASML', 'KLAC', 'GLW'
    ],
    'TW_STOCKS': [
        '2330.TW', '2454.TW', '2317.TW', '2382.TW',
        '3231.TW', '6669.TW', '3017.TW',
        '1519.TW', '1503.TW', '2603.TW', '2609.TW',
        '8996.TW', '6515.TW', '6442.TW', '6139.TW',
        # 上櫃 (.TWO)
        '8299.TWO', '3529.TWO', '3081.TWO', '6739.TWO', '6683.TWO'
    ]
}

def get_asset_type(symbol):
    if "-USD" in symbol: return 'CRYPTO'
    if ".TW" in symbol or ".TWO" in symbol: return 'TW'
    if symbol in STRATEGIC_POOL['LEVERAGE']: return 'LEVERAGE'
    return 'STOCK'

# ==========================================
# 2. 核心功能函式
# ==========================================
def calculate_indicators(df):
    if len(df) < 100: return None
    df = df.copy().sort_index()
    
    # 均線
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 動能
    df['Momentum'] = df['Close'].pct_change(periods=20)
    
    return df.iloc[-1]

def calculate_liquidity(df, symbol):
    """計算過去5日的平均成交金額(USD)"""
    try:
        # 取最近5天
        recent = df.tail(5).copy()
        
        # 轉換為 USD (簡單匯率估算)
        exchange_rate = 1.0
        if ".TW" in symbol or ".TWO" in symbol:
            exchange_rate = 1 / 32.5 # 台幣轉美金
            
        # 成交金額 = 收盤價 * 成交量 * 匯率
        recent['DollarVolume'] = recent['Close'] * recent['Volume'] * exchange_rate
        avg_volume = recent['DollarVolume'].mean()
        
        return avg_volume
    except:
        return 0

def load_portfolio():
    """讀取 GitHub 上的 portfolio.csv 並自動修正代碼"""
    holdings = {}
    if not os.path.exists(PORTFOLIO_FILE):
        return holdings

    # 建立對照表
    crypto_map = {}
    for c in STRATEGIC_POOL['CRYPTO']:
        if c.endswith('-USD'):
            short_name = c.split('-')[0]
            if any(char.isdigit() for char in short_name):
                alpha_only = ''.join(filter(str.isalpha, short_name))
                crypto_map[alpha_only] = c
            crypto_map[short_name] = c

    otc_list = ['8299', '3529', '3081', '6739', '6683']

    alias_map = {
        'RNDR': 'RENDER-USD', 'TAO': 'TAO22974-USD',
        'SUI': 'SUI20947-USD', 'PEPE': 'PEPE24478-USD'
    }

    try:
        with open(PORTFOLIO_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 2: continue
                raw_symbol = row[0].strip().upper()
                symbol = raw_symbol
                
                if raw_symbol in alias_map: symbol = alias_map[raw_symbol]
                elif raw_symbol.isdigit() and len(raw_symbol) == 4:
                    if raw_symbol in otc_list: symbol = f"{raw_symbol}.TWO"
                    else: symbol = f"{raw_symbol}.TW"
                elif raw_symbol in crypto_map: symbol = crypto_map[raw_symbol]
                
                try: cost = float(row[1].strip())
                except: cost = 0.0
                
                if 'SYMBOL' in symbol: continue
                holdings[symbol] = {"entry_price": cost}
        return holdings
    except Exception as e:
        print(f"❌ 讀取 CSV 失敗: {e}")
        return {}

def analyze_market_regime():
    tickers = ['SPY', 'BTC-USD', '^TWII']
    try:
        data = yf.download(tickers, period="300d", progress=False, auto_adjust=True)
        if isinstance(data.columns, pd.MultiIndex):
            try: df_close = data['Close']
            except: df_close = data
        else: df_close = data
        
        regime = {}
        def check_bull(series, ma_window):
            try:
                s = series.dropna()
                if len(s) < ma_window: return False, 0
                price = s.iloc[-1]
                ma = s.rolling(ma_window).mean().iloc[-1]
                return price > ma, price
            except: return False, 0

        regime['US_BULL'], spy_p = check_bull(df_close.get('SPY'), 200)
        regime['CRYPTO_BULL'], btc_p = check_bull(df_close.get('BTC-USD'), 200)
        regime['TW_BULL'], tw_p = check_bull(df_close.get('^TWII'), 60)
        
        return regime, spy_p, btc_p, tw_p
    except:
        return {'US_BULL':False, 'CRYPTO_BULL':False, 'TW_BULL':False}, 0, 0, 0

# ==========================================
# 3. 決策引擎 (實戰版)
# ==========================================
def make_decision():
    portfolio = load_portfolio()
    regime, spy, btc, tw = analyze_market_regime()
    
    sells = []
    keeps = []
    
    if portfolio:
        print(f"🔍 檢查持倉: {list(portfolio.keys())}")
        try:
            tickers = list(portfolio.keys())
            data = yf.download(tickers, period="200d", progress=False, auto_adjust=True)
            if isinstance(data.columns, pd.MultiIndex): closes = data['Close']
            else: closes = data
            if len(tickers) == 1: closes = pd.DataFrame({tickers[0]: data['Close']})

            for symbol in tickers:
                try:
                    series = closes[symbol].dropna()
                    if len(series) < 60: 
                        print(f"⚠️ {symbol} 數據不足")
                        continue
                    
                    curr_row = calculate_indicators(pd.DataFrame({'Close': series}))
                    price = curr_row['Close']
                    ma50 = curr_row['MA50']
                    rsi = curr_row['RSI']
                    entry = portfolio[symbol]['entry_price']
                    
                    reason = ""
                    if price < ma50: reason = "❌ 跌破季線 (MA50)"
                    elif entry > 0 and price < entry * 0.8: reason = "🔴 硬止損 (-20%)"
                    
                    if reason:
                        sells.append({'Symbol': symbol, 'Price': price, 'Reason': reason})
                    else:
                        profit = (price - entry) / entry if entry > 0 else 0
                        stop_suggest = max(price * 0.8, ma50)
                        note = "續抱"
                        if rsi > 80:
                            note = "🔥 過熱 (請收緊停利至10%)"
                            stop_suggest = max(stop_suggest, price * 0.9)
                        elif profit > 0.5:
                            note = "🔒 獲利>50% (請鎖定利潤)"
                            stop_suggest = max(stop_suggest, entry * 1.2)
                        keeps.append({'Symbol': symbol, 'Price': price, 'Profit': profit, 'Stop': stop_suggest, 'Note': note, 'RSI': rsi})
                except Exception as e:
                    print(f"處理 {symbol} 出錯: {e}")
                    keeps.append({'Symbol': symbol, 'Price': 0, 'Profit': 0, 'Stop': 0, 'Note': "數據錯誤", 'RSI': 0})
        except Exception as e:
            print(f"下載持倉數據失敗: {e}")

    current_slots = len(keeps) 
    buys = []
    candidates = []
    all_tickers = []
    for cat in STRATEGIC_POOL: all_tickers.extend(STRATEGIC_POOL[cat])
    
    print("📥 掃描全市場機會...")
    try:
        data = yf.download(all_tickers, period="250d", progress=False, auto_adjust=True)
        
        # 處理資料列名
        closes = None
        volumes = None
        
        if isinstance(data.columns, pd.MultiIndex):
            try: closes = data['Close'].ffill()
            except: closes = data.ffill() # Fallback
            
            try: volumes = data['Volume'].ffill()
            except: pass
        else:
            closes = data.ffill() # 只有一檔時可能沒有 MultiIndex
        
        for symbol in all_tickers:
            if symbol in closes.columns:
                try:
                    series = closes[symbol].dropna()
                    if len(series) < 100: continue
                    
                    # 1. 流動性檢測 (新增)
                    avg_vol_usd = 0
                    if volumes is not None and symbol in volumes.columns:
                        vol_series = volumes[symbol].tail(10) # 取最近數據
                        close_series = series.tail(10)
                        
                        # 簡易計算平均成交額
                        val_series = vol_series * close_series
                        avg_vol_raw = val_series.mean()
                        
                        # 匯率換算
                        rate = 1/32.5 if (".TW" in symbol or ".TWO" in symbol) else 1.0
                        avg_vol_usd = avg_vol_raw * rate
                    
                    # 如果成交額太低 (<50萬美金)，直接跳過
                    # 若無法取得 Volume 數據 (例如某些指數)，則保守起見設為通過，或視為不通過
                    # 這裡假設若有 Volume 數據才檢查，沒有則 Pass (避免誤殺 ETF)
                    if avg_vol_usd > 0 and avg_vol_usd < MIN_DAILY_VOLUME_USD:
                        continue 

                    df_t = pd.DataFrame({'Close': series})
                    row = calculate_indicators(df_t)
                    
                    # 2. 技術篩選
                    if row['Close'] > row['MA20'] and row['MA20'] > row['MA50'] and row['RSI'] < 80:
                        candidates.append({
                            'Symbol': symbol,
                            'Score': row['Momentum'],
                            'Price': row['Close'],
                            'RSI': row['RSI'],
                            'Type': get_asset_type(symbol),
                            'Vol': avg_vol_usd # 紀錄成交額
                        })
                except: continue
        
        candidates.sort(key=lambda x: x['Score'], reverse=True)
        
        slots_needed = 3 - current_slots
        if slots_needed > 0:
            for cand in candidates:
                if len(buys) >= slots_needed: break
                is_held = False
                for k in keeps:
                    if k['Symbol'] == cand['Symbol']: is_held = True
                if not is_held:
                    buys.append(cand)
                    
    except Exception as e:
        print(f"掃描市場失敗: {e}")

    return regime, sells, keeps, buys, candidates[:5], spy, btc, tw

# ==========================================
# 4. 訊息生成與發送
# ==========================================
def generate_message(regime, sells, keeps, buys, top_list, spy, btc, tw):
    msg = f"🤖 **V181 實戰管家**\n{datetime.now().strftime('%Y-%m-%d')}\n"
    msg += "━━━━━━━━━━━━━━\n"
    
    msg += "📢 **【今日操作指令】**\n"
    has_action = False
    
    if sells:
        msg += "🔴 **賣出 (請執行並刪除CSV):**\n"
        for x in sells:
            msg += f"❌ {x['Symbol']} ({x['Reason']})\n"
        has_action = True
        
    if buys:
        msg += "🟢 **買進 (請執行並寫入CSV):**\n"
        for x in buys:
            size_hint = "滿倉"
            if x['Type'] == 'LEVERAGE' and not regime['US_BULL']: size_hint = "⚠️半倉"
            if x['Type'] == 'CRYPTO' and not regime['CRYPTO_BULL']: size_hint = "⚠️半倉"
            
            msg += f"💰 {x['Symbol']} @ {x['Price']:.2f}\n"
            msg += f"   建議: {size_hint} | RSI: {x['RSI']:.1f}\n"
        has_action = True
        
    if not has_action:
        msg += "☕ **今日無買賣，請續抱。**\n"
        
    msg += "━━━━━━━━━━━━━━\n"
    
    if keeps:
        msg += "🛡️ **【持倉監控】**\n"
        for x in keeps:
            profit = x['Profit'] * 100
            emoji = "😍" if profit > 20 else "🙂" if profit > 0 else "🤢"
            
            display_stop = x['Stop']
            if "過熱" in x['Note']:
                display_stop = max(display_stop, x['Price'] * 0.9)
            
            msg += f"{emoji} {x['Symbol']} (Now: {x['Price']:.2f} | {profit:+.1f}%)\n"
            msg += f"   狀態: {x['Note']}\n"
            msg += f"   防守價: {display_stop:.2f}\n"
    else:
        msg += "🛡️ 目前空手 (等待機會)\n"

    msg += "━━━━━━━━━━━━━━\n"
    
    msg += "🌍 **【大盤與動能王】**\n"
    spy_disp = f"{spy:.0f}" if spy > 0 else "N/A"
    btc_disp = f"{btc:.0f}" if btc > 0 else "N/A"
    tw_disp = f"{tw:.0f}" if tw > 0 else "N/A"
    
    spy_icon = "🟢" if regime['US_BULL'] else "🔴"
    btc_icon = "🟢" if regime['CRYPTO_BULL'] else "🔴"
    tw_icon = "🟢" if regime['TW_BULL'] else "🔴"

    msg += f"美{spy_icon} {spy_disp} | 幣{btc_icon} {btc_disp}\n"
    msg += f"台{tw_icon} {tw_disp}\n"
    msg += "--------------------\n"
    rank = 1
    for x in top_list[:3]:
        # 顯示成交量概況 (M = 百萬美金)
        vol_str = ""
        if 'Vol' in x and x['Vol'] > 0:
            vol_str = f"| Vol:${x['Vol']/1000000:.1f}M"
            
        msg += f"{rank}. {x['Symbol']} (RSI:{x['RSI']:.0f} {vol_str})\n"
        rank += 1
        
    return msg

def send_line_message(message):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("未設定 LINE Token")
        return
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'}
    data = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=data)

if __name__ == "__main__":
    regime, sells, keeps, buys, top_list, spy, btc, tw = make_decision()
    msg = generate_message(regime, sells, keeps, buys, top_list, spy, btc, tw)
    print(msg)
    send_line_message(msg)
