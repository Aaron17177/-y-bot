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

# V181-2026 戰力池 (完美覆蓋版)
STRATEGIC_POOL = {
    'CRYPTO': [
        'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 
        'DOGE-USD', 'SHIB-USD', 
        'PEPE24478-USD', 'APT-USD', 'NEAR-USD', 'SUI-USD', # 公鏈新星
        'FET-USD', 'RENDER-USD', 'WLD-USD', 'TAO-USD',     # AI Crypto 龍頭
        'LINK-USD', 'AVAX-USD'
    ],
    'LEVERAGE': [
        'NVDL', 'SOXL', 'TQQQ', 'FNGU', 'TSLL', 
        'CONL', 'BITU', 'USD', 'TECL',
        'MSTU', # 2倍 MSTR (比特幣核彈)
        'LABU'  # 3倍生技 (降息循環黑馬)
    ],
    'US_STOCKS': [
        'NVDA', 'AMD', 'TSLA', 'PLTR', 'MSTR', 'COIN',
        'SMCI', 'ARM', 'AVGO', 'META', 'AMZN', 'NFLX', 
        'LLY', 'VRTX', 'CRWD', 'PANW', 'ORCL', 'SHOP',
        'APP',  # AI 廣告
        'IONQ', 'RGTI', # 量子計算
        'RKLB', # 太空經濟
        'VRT', 'ANET', 'SNOW', 'COST',
        'VST'   # AI 電力/核能
    ],
    'TW_STOCKS': [
        '2330.TW', '2454.TW', '2317.TW', '2382.TW',
        '3231.TW', '6669.TW', '3017.TW',
        '1519.TW', '1503.TW', # 重電
        '2603.TW', '2609.TW'  # 航運
    ]
}

def get_asset_type(symbol):
    if "-USD" in symbol: return 'CRYPTO'
    if ".TW" in symbol: return 'TW'
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
    
    # 取最新一筆有效數據
    return df.iloc[-1]

def load_portfolio():
    """
    讀取 GitHub 上的 portfolio.csv 並自動修正代碼
    支援:
    1. 特殊別名: PEPE -> PEPE24478-USD, RNDR -> RENDER-USD
    2. 通用Crypto: BTC -> BTC-USD (自動比對戰力池)
    3. 台股: 1503 -> 1503.TW
    """
    holdings = {}
    if not os.path.exists(PORTFOLIO_FILE):
        print("⚠️ 找不到 portfolio.csv，假設為空手。")
        return holdings

    # 建立動態 Crypto 對照表
    # 邏輯: 產生 { 'BTC': 'BTC-USD', 'ETH': 'ETH-USD', ... }
    crypto_map = {}
    for c in STRATEGIC_POOL['CRYPTO']:
        if c.endswith('-USD'):
            short_name = c.split('-')[0] # 取前面代號
            crypto_map[short_name] = c

    # 建立特殊別名 (手動指定)
    alias_map = {
        'PEPE': 'PEPE24478-USD',
        'RNDR': 'RENDER-USD'
    }

    try:
        with open(PORTFOLIO_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 2: continue
                
                # 1. 讀取與基礎清理
                raw_symbol = row[0].strip().upper()
                symbol = raw_symbol
                
                # 2. 智能修正代碼邏輯
                
                # A. 優先檢查特殊別名 (PEPE, RNDR)
                if raw_symbol in alias_map:
                    symbol = alias_map[raw_symbol]
                
                # B. 台股修正 (4位純數字)
                elif raw_symbol.isdigit() and len(raw_symbol) == 4:
                    symbol = f"{raw_symbol}.TW"
                
                # C. 通用 Crypto 修正 (BTC -> BTC-USD)
                # 檢查是否在我們的簡寫表中
                elif raw_symbol in crypto_map:
                    symbol = crypto_map[raw_symbol]
                
                try:
                    cost = float(row[1].strip())
                except ValueError:
                    cost = 0.0
                
                # 簡單過濾掉標題行
                if 'SYMBOL' in symbol: continue
                
                holdings[symbol] = {"entry_price": cost}
        return holdings
    except Exception as e:
        print(f"❌ 讀取 CSV 失敗: {e}")
        return {}

def analyze_market_regime():
    """判斷大環境"""
    tickers = ['SPY', 'BTC-USD', '^TWII']
    try:
        data = yf.download(tickers, period="300d", progress=False, auto_adjust=True)
        if isinstance(data.columns, pd.MultiIndex):
            try: df_close = data['Close']
            except: df_close = data
        else: df_close = data
        
        regime = {}
        # 輔助函式避免報錯
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
    # A. 載入資料
    portfolio = load_portfolio()
    regime, spy, btc, tw = analyze_market_regime()
    
    sells = []
    keeps = []
    
    # B. 檢查現有持倉 (賣出/續抱邏輯)
    if portfolio:
        print(f"🔍 檢查持倉: {list(portfolio.keys())}")
        try:
            tickers = list(portfolio.keys())
            # 多下載一些數據以防萬一
            data = yf.download(tickers, period="200d", progress=False, auto_adjust=True)
            
            if isinstance(data.columns, pd.MultiIndex): closes = data['Close']
            else: closes = data
            # 單一股票修正
            if len(tickers) == 1: closes = pd.DataFrame({tickers[0]: data['Close']})

            for symbol in tickers:
                try:
                    series = closes[symbol].dropna()
                    if len(series) < 60: 
                        print(f"⚠️ {symbol} 數據不足，可能是代碼錯誤")
                        continue
                    
                    # 計算指標
                    curr_row = calculate_indicators(pd.DataFrame({'Close': series}))
                    price = curr_row['Close']
                    ma50 = curr_row['MA50']
                    
                    entry = portfolio[symbol]['entry_price']
                    
                    # 賣出條件 (V181 核心)
                    reason = ""
                    if price < ma50:
                        reason = "❌ 跌破季線 (MA50)"
                    elif entry > 0 and price < entry * 0.8:
                        reason = "🔴 硬止損 (-20%)"
                    
                    if reason:
                        sells.append({'Symbol': symbol, 'Price': price, 'Reason': reason})
                    else:
                        # 計算建議
                        profit = (price - entry) / entry if entry > 0 else 0
                        stop_suggest = max(price * 0.8, ma50) # 建議止損位
                        
                        # 檢查是否過熱
                        rsi = curr_row['RSI']
                        note = "續抱"
                        if rsi > 80: note = "🔥 過熱 (請收緊停利至10%)"
                        elif profit > 0.5: note = "🔒 獲利>50% (請鎖定利潤)"
                        
                        keeps.append({
                            'Symbol': symbol, 'Price': price, 'Profit': profit, 
                            'Stop': stop_suggest, 'Note': note, 'RSI': rsi
                        })
                except Exception as e:
                    print(f"處理 {symbol} 出錯: {e}")
                    keeps.append({'Symbol': symbol, 'Price': 0, 'Profit': 0, 'Stop': 0, 'Note': "數據錯誤", 'RSI': 0})
        except Exception as e:
            print(f"下載持倉數據失敗: {e}")

    # C. 掃描新機會 (買入邏輯)
    current_slots = len(keeps) # 賣出後的剩餘空位
    buys = []
    candidates = []
    
    # 只有當有空位時才掃描，節省資源
    all_tickers = []
    for cat in STRATEGIC_POOL: all_tickers.extend(STRATEGIC_POOL[cat])
    
    print("📥 掃描全市場機會...")
    try:
        data = yf.download(all_tickers, period="250d", progress=False, auto_adjust=True)
        if isinstance(data.columns, pd.MultiIndex): closes = data['Close'].ffill()
        else: closes = data['Close'].ffill()
        
        for symbol in all_tickers:
            if symbol in closes.columns:
                try:
                    series = closes[symbol].dropna()
                    if len(series) < 100: continue
                    
                    df_t = pd.DataFrame({'Close': series})
                    row = calculate_indicators(df_t)
                    
                    # 買入篩選 V181
                    # 多頭排列 + RSI不過熱
                    if row['Close'] > row['MA20'] and row['MA20'] > row['MA50'] and row['RSI'] < 80:
                        candidates.append({
                            'Symbol': symbol,
                            'Score': row['Momentum'],
                            'Price': row['Close'],
                            'RSI': row['RSI'],
                            'Type': get_asset_type(symbol)
                        })
                except: continue
        
        # 排名
        candidates.sort(key=lambda x: x['Score'], reverse=True)
        
        # 填補空缺
        slots_needed = 3 - current_slots
        if slots_needed > 0:
            for cand in candidates:
                if len(buys) >= slots_needed: break
                
                # 不買已經持有的
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
    
    # 1. 關鍵指令
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
            # 判斷倉位大小
            size_hint = "滿倉"
            if x['Type'] == 'LEVERAGE' and not regime['US_BULL']: size_hint = "⚠️半倉"
            if x['Type'] == 'CRYPTO' and not regime['CRYPTO_BULL']: size_hint = "⚠️半倉"
            
            msg += f"💰 {x['Symbol']} @ {x['Price']:.2f}\n"
            msg += f"   建議: {size_hint} | RSI: {x['RSI']:.1f}\n"
        has_action = True
        
    if not has_action:
        msg += "☕ **今日無買賣，請續抱。**\n"
        
    msg += "━━━━━━━━━━━━━━\n"
    
    # 2. 持倉監控
    if keeps:
        msg += "🛡️ **【持倉監控】**\n"
        for x in keeps:
            profit = x['Profit'] * 100
            emoji = "😍" if profit > 20 else "🙂" if profit > 0 else "🤢"
            
            # 防守價顯示邏輯優化
            # 如果是過熱狀態，顯示 10% 停利價 (現價*0.9)，否則顯示標準防守價 (20% 或 MA50)
            display_stop = x['Stop']
            if "過熱" in x['Note']:
                display_stop = max(display_stop, x['Price'] * 0.9)
            
            msg += f"{emoji} {x['Symbol']} ({profit:+.1f}%)\n"
            msg += f"   狀態: {x['Note']}\n"
            msg += f"   防守價: {display_stop:.2f}\n"
    else:
        msg += "🛡️ 目前空手 (等待機會)\n"

    msg += "━━━━━━━━━━━━━━\n"
    
    # 3. 市場概況
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
        msg += f"{rank}. {x['Symbol']} (RSI:{x['RSI']:.0f})\n"
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
