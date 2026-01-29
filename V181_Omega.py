import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import csv
from datetime import datetime

# ==========================================
# 1. 參數與設定 (V196 Apex Predator 實戰版)
# ==========================================
LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
PORTFOLIO_FILE = 'portfolio.csv'

# V196 全明星戰力池 (含權重設定)
# 更新註記: MATIC->POL, 移除 HYPE (YF無數據)
STRATEGIC_POOL = {
    'CRYPTO': [ # 權重 1.4x
        'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'AVAX-USD',
        'DOGE-USD', 'SHIB-USD', 'POL-USD', 'LINK-USD', 'LTC-USD',
        'SAND-USD', 'AXS-USD', 'LUNC-USD', 'FTT-USD', 
        'PEPE24478-USD', 'APT-USD', 'NEAR-USD', 'SUI20947-USD',
        'FET-USD', 'RENDER-USD', 'WLD-USD', 'TAO22974-USD',
        'BONK-USD'
    ],
    'LEVERAGE': [ # 權重 1.5x
        'NVDL', 'SOXL', 'TQQQ', 'FNGU', 'TSLL', 
        'CONL', 'BITU', 'USD', 'TECL', 'MSTU', 'LABU'
    ],
    'US_STOCKS': [ # 權重 1.0x (Tier1 1.2x)
        'NVDA', 'AMD', 'TSLA', 'MRNA', 'ZM', 'PTON', 'UBER',
        'PLTR', 'MSTR', 'COIN', 'SMCI', 'ARM', 'AVGO', 'META', 'AMZN', 'NFLX', 
        'LLY', 'VRTX', 'CRWD', 'PANW', 'ORCL', 'SHOP',
        'APP', 'IONQ', 'RGTI', 'RKLB', 'VRT', 'ANET', 'SNOW', 'COST',
        'VST', 'MU', 'AMAT', 'LRCX', 'ASML', 'KLAC', 'GLW'
    ],
    'TW_STOCKS': [ # 權重 1.0x (Tier1 1.2x)
        '2330.TW', '2454.TW', '2317.TW', '2382.TW',
        '3231.TW', '6669.TW', '3017.TW',
        '1519.TW', '1503.TW', '2603.TW', '2609.TW',
        '8996.TW', '6515.TW', '6442.TW', '6139.TW',
        '8299.TWO', '3529.TWO', '3081.TWO', '6739.TWO', '6683.TWO'
    ]
}

TIER_1_ASSETS = [
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD',
    'NVDA', 'TSLA', 'MSTR', 'COIN', 'APP', 'PLTR',
    'SOXL', 'NVDL', 'TQQQ', 'MSTU', 'CONL', 'FNGU',
    '2330.TW', '2454.TW', '2317.TW'
]

# 基準指標
BENCHMARKS = ['^GSPC', 'BTC-USD', '^TWII']

# ==========================================
# 2. 輔助函式
# ==========================================
def get_asset_type(symbol):
    if "-USD" in symbol: return 'CRYPTO'
    if ".TW" in symbol or ".TWO" in symbol: return 'TW'
    if any(s == symbol for s in STRATEGIC_POOL['LEVERAGE']): return 'LEVERAGE'
    return 'US_STOCK'

def calculate_indicators(df):
    if len(df) < 100: return None
    df = df.copy()
    
    # V196 關鍵均線
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['MA100'] = df['Close'].rolling(window=100).mean() # 幣圈專用
    df['MA200'] = df['Close'].rolling(window=200).mean() # 美股專用
    
    # 動能
    df['Momentum'] = df['Close'].pct_change(periods=20)
    
    return df.iloc[-1]

def normalize_symbol(raw_symbol):
    """自動校正股票代碼"""
    raw_symbol = raw_symbol.strip().upper()
    
    # 1. 別名對映 (Yahoo Finance 特殊代碼)
    alias_map = {
        'PEPE': 'PEPE24478-USD', 'SHIB': 'SHIB-USD', 'DOGE': 'DOGE-USD',
        'BONK': 'BONK-USD', 'FLOKI': 'FLOKI-USD', 'WIF': 'WIF-USD',
        'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD',
        'TAO': 'TAO22974-USD', 'SUI': 'SUI20947-USD',
        'HYPE': 'HYPE-USD', 'WLD': 'WLD-USD', 'FET': 'FET-USD',
        'MATIC': 'POL-USD', 'POL': 'POL-USD' # Polygon 換幣修正
    }
    if raw_symbol in alias_map: return alias_map[raw_symbol]
    
    # 2. 台灣股票 (.TW / .TWO)
    # 簡單判斷：如果是4位數字，先假設是 .TW，除非在特定的上櫃名單中
    otc_list = ['8299', '3529', '3081', '6739', '6683', '8069', '3293', '3661'] 
    if raw_symbol.isdigit() and len(raw_symbol) == 4:
        if raw_symbol in otc_list: return f"{raw_symbol}.TWO"
        return f"{raw_symbol}.TW"
        
    # 3. 加密貨幣 (沒有 -USD 的自動補上)
    known_crypto = set([c.split('-')[0] for c in STRATEGIC_POOL['CRYPTO']])
    if raw_symbol in known_crypto:
        # 檢查是否在特殊對映中，否則直接加 -USD
        for k, v in alias_map.items():
            if raw_symbol == k: return v
        return f"{raw_symbol}-USD"

    return raw_symbol

def load_portfolio():
    """
    讀取 portfolio.csv
    格式: Symbol, EntryPrice, HighPrice(可選)
    """
    holdings = {}
    if not os.path.exists(PORTFOLIO_FILE):
        print("⚠️ 找不到 portfolio.csv，假設目前空手。")
        return holdings

    try:
        with open(PORTFOLIO_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            # 嘗試讀取第一行，如果是標題就跳過，如果不是標題(是數據)就回退
            try:
                header = next(reader)
                # 簡單檢查第一欄是否為 'Symbol' 或類似標題
                if not header or 'Symbol' not in header[0]:
                    # 如果不是標題，這裡假設使用者沒加標題，直接報錯或跳過可能會有問題
                    # 但為了相容性，建議使用者務必加標題
                    pass 
                
                # 繼續讀取剩下的行
                for row in reader:
                    if not row or len(row) < 2: continue
                    symbol = normalize_symbol(row[0])
                    try:
                        entry_price = float(row[1])
                        # 如果有紀錄最高價就讀取，沒有就設為進場價
                        high_price = float(row[2]) if len(row) > 2 and row[2] else entry_price
                        
                        holdings[symbol] = {
                            'entry_price': entry_price,
                            'high_price': high_price
                        }
                    except ValueError:
                        continue # 跳過無法解析的行
                        
            except StopIteration:
                pass # 空文件

        print(f"📋 已讀取持倉監控名單: {list(holdings.keys())}")
        return holdings
    except Exception as e:
        print(f"❌ 讀取 CSV 失敗: {e}")
        return {}

def update_portfolio_csv(holdings, current_prices):
    """更新 CSV 中的最高價 (HighPrice) 欄位，用於移動停利"""
    try:
        data_to_write = []
        for symbol, data in holdings.items():
            curr_p = current_prices.get(symbol, 0)
            if curr_p > 0:
                # 更新歷史最高價
                new_high = max(data['high_price'], curr_p)
                data_to_write.append([symbol, data['entry_price'], new_high])
            else:
                data_to_write.append([symbol, data['entry_price'], data['high_price']])
        
        with open(PORTFOLIO_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Symbol', 'EntryPrice', 'HighPrice']) # Header
            writer.writerows(data_to_write)
        print("✅ Portfolio 最高價已更新")
    except Exception as e:
        print(f"❌ 更新 CSV 失敗: {e}")

# ==========================================
# 3. 分析引擎
# ==========================================
def analyze_market():
    # 1. 準備清單
    portfolio = load_portfolio()
    all_tickers = list(set(BENCHMARKS + list(portfolio.keys()) + 
                           [t for cat in STRATEGIC_POOL for t in STRATEGIC_POOL[cat]]))
    
    # 移除 HYPE 避免下載錯誤
    if 'HYPE-USD' in all_tickers: all_tickers.remove('HYPE-USD')

    print(f"📥 下載 {len(all_tickers)} 檔標的數據...")
    try:
        data = yf.download(all_tickers, period="250d", progress=False, auto_adjust=True)
        if data.empty: return None
        closes = data['Close'].ffill()
    except Exception as e:
        print(f"❌ 數據下載失敗: {e}")
        return None

    # 2. 判斷冬眠狀態 (V196 規則)
    regime = {}
    
    # 美股/台股看 SPY 200日線
    spy_series = closes.get('^GSPC', closes.get('SPY'))
    if spy_series is not None:
        spy_last = spy_series.iloc[-1]
        spy_ma200 = spy_series.rolling(200).mean().iloc[-1]
        regime['US_BULL'] = spy_last > spy_ma200
        regime['TW_BULL'] = regime['US_BULL'] # 台股連動美股
    else:
        regime['US_BULL'] = True # 數據不足預設多頭

    # 幣圈看 BTC 100日線 (V196 特色)
    btc_series = closes.get('BTC-USD')
    if btc_series is not None:
        btc_last = btc_series.iloc[-1]
        btc_ma100 = btc_series.rolling(100).mean().iloc[-1]
        regime['CRYPTO_BULL'] = btc_last > btc_ma100
    else:
        regime['CRYPTO_BULL'] = True

    current_prices = {t: closes[t].iloc[-1] for t in all_tickers if t in closes.columns}
    
    # 更新 CSV 中的 HighPrice
    update_portfolio_csv(portfolio, current_prices)

    # 3. 掃描持倉 (Sell Check)
    sells = []
    keeps = []
    
    for symbol, data in portfolio.items():
        if symbol not in closes.columns: continue
        
        series = closes[symbol].dropna()
        if len(series) < 60: continue
        
        row = calculate_indicators(pd.DataFrame({'Close': series}))
        curr_price = row['Close']
        entry_price = data['entry_price']
        high_price = max(data['high_price'], curr_price) # 取用 CSV 紀錄或當前價
        
        atype = get_asset_type(symbol)
        
        # A. 冬眠檢查
        is_winter = False
        if atype == 'CRYPTO' and not regime['CRYPTO_BULL']: is_winter = True
        elif atype in ['US_STOCK', 'LEVERAGE'] and not regime['US_BULL']: is_winter = True
        elif atype == 'TW' and not regime['TW_BULL']: is_winter = True
        
        # B. 停損停利檢查 (V196 參數)
        reason = ""
        profit_pct = (curr_price - entry_price) / entry_price
        
        # 移動停利: 預設 25% 回撤，翻倍後收緊至 20%
        trail_limit = 0.75
        if profit_pct > 1.0: trail_limit = 0.80
        
        # 計算防守價位以便顯示
        hard_stop_price = entry_price * 0.70
        trail_stop_price = high_price * trail_limit
        
        # 決定當前生效的防守價 (取最高者)
        active_stop_price = max(hard_stop_price, trail_stop_price)
        
        # 決定防守說明文字
        stop_info = ""
        if active_stop_price == hard_stop_price:
            stop_info = "硬損-30%"
        else:
            stop_info = f"高點-{int((1-trail_limit)*100)}%"

        if is_winter:
            reason = "❄️ 分區冬眠 (清倉)"
        elif curr_price < hard_stop_price:
            reason = "🔴 深淵止損 (-30%)"
        elif curr_price < trail_stop_price:
            reason = f"🛡️ 移動停利 ({stop_info})"
        elif curr_price < row['MA50']:
             reason = "❌ 跌破季線"
        
        if reason:
            sells.append({'Symbol': symbol, 'Price': curr_price, 'Reason': reason, 'PnL': f"{profit_pct*100:.1f}%"})
        else:
            # 弒君分數計算
            score = row['Momentum']
            multiplier = 1.0
            if symbol in TIER_1_ASSETS: multiplier = 1.2
            if atype == 'CRYPTO': multiplier = 1.4
            if atype == 'LEVERAGE': multiplier = 1.5
            final_score = score * multiplier
            
            keeps.append({
                'Symbol': symbol, 'Price': curr_price, 'Score': final_score, 
                'Profit': profit_pct, 'Stop': active_stop_price, 
                'StopInfo': stop_info # 新增欄位給顯示用
            })

    # 4. 掃描機會 (Buy Check)
    candidates = []
    
    # 只掃描符合多頭條件的板塊
    valid_pool = []
    if regime['CRYPTO_BULL']: valid_pool += STRATEGIC_POOL['CRYPTO']
    if regime['US_BULL']: 
        valid_pool += STRATEGIC_POOL['US_STOCKS']
        valid_pool += STRATEGIC_POOL['LEVERAGE']
    if regime['TW_BULL']: valid_pool += STRATEGIC_POOL['TW_STOCKS']
    
    # 移除暫時無法獲取的
    if 'HYPE-USD' in valid_pool: valid_pool.remove('HYPE-USD')

    for t in valid_pool:
        if t in portfolio or t not in closes.columns: continue
        
        series = closes[t].dropna()
        if len(series) < 60: continue
        
        row = calculate_indicators(pd.DataFrame({'Close': series}))
        
        # 趨勢過濾: 價格 > 20 > 50 > 60
        if not (row['Close'] > row['MA20'] and row['MA20'] > row['MA50'] and row['Close'] > row['MA60']):
            continue
            
        raw_score = row['Momentum']
        if pd.isna(raw_score) or raw_score <= 0: continue
        
        # 暴力加權
        multiplier = 1.0
        atype = get_asset_type(t)
        if t in TIER_1_ASSETS: multiplier = 1.2
        if atype == 'CRYPTO': multiplier = 1.4
        if atype == 'LEVERAGE': multiplier = 1.5
        
        final_score = raw_score * multiplier
        
        candidates.append({'Symbol': t, 'Price': row['Close'], 'Score': final_score, 'RawMom': raw_score})
        
    candidates.sort(key=lambda x: x['Score'], reverse=True)
    
    # 5. 弒君檢查 (King Slayer)
    swaps = []
    if keeps and candidates:
        worst_holding = min(keeps, key=lambda x: x['Score'])
        best_candidate = candidates[0]
        
        # 如果場外最強 > 場內最弱 * 1.5倍
        if best_candidate['Score'] > worst_holding['Score'] * 1.5:
            swaps.append({
                'Sell': worst_holding,
                'Buy': best_candidate,
                'Reason': f"💀 弒君換馬 (評分 {best_candidate['Score']:.2f} vs {worst_holding['Score']:.2f})"
            })
            # 移除被換掉的，避免重複推薦
            keeps = [k for k in keeps if k != worst_holding]
            sells.append({'Symbol': worst_holding['Symbol'], 'Price': worst_holding['Price'], 'Reason': "💀 弒君被換", 'PnL': f"{worst_holding['Profit']*100:.1f}%"})
            
    # 6. 空位買入
    buys = []
    open_slots = 4 - len(keeps) # V196 固定 4 席
    
    # 扣除掉已經在 Swap 名單中的候選人
    swap_buy_symbols = [s['Buy']['Symbol'] for s in swaps]
    available_candidates = [c for c in candidates if c['Symbol'] not in swap_buy_symbols]
    
    if open_slots > 0 and available_candidates:
        for i in range(min(open_slots, len(available_candidates))):
            cand = available_candidates[i]
            buys.append({
                'Symbol': cand['Symbol'],
                'Price': cand['Price'],
                'Score': cand['Score'],
                'Reason': f"🦁 新晉獵物 (評分 {cand['Score']:.2f})"
            })

    return regime, sells, keeps, buys, swaps

# ==========================================
# 4. 訊息發送
# ==========================================
def send_line_notify(msg):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 未設定 LINE Token，跳過發送。")
        print(msg)
        return

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": msg}]
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            print("✅ LINE 通知已發送")
        else:
            print(f"❌ LINE 發送失敗: {response.text}")
    except Exception as e:
        print(f"❌ 連線錯誤: {e}")

def format_message(regime, sells, keeps, buys, swaps):
    msg = f"🦁 **V196 Apex Predator 實戰日報**\n{datetime.now().strftime('%Y-%m-%d')}\n"
    msg += "━━━━━━━━━━━━━━\n"
    
    # 環境
    us_icon = "🟢" if regime['US_BULL'] else "❄️"
    crypto_icon = "🟢" if regime['CRYPTO_BULL'] else "❄️"
    msg += f"環境: 美股{us_icon} | 幣圈{crypto_icon}\n"
    msg += "━━━━━━━━━━━━━━\n"

    # 賣出指令
    if sells:
        msg += "🔴 **【賣出指令】**\n"
        for s in sells:
            msg += f"❌ {s['Symbol']} ({s['Reason']})\n"
            msg += f"   現價: {s['Price']:.2f} | 損益: {s['PnL']}\n"
        msg += "--------------------\n"

    # 弒君換馬
    if swaps:
        msg += "💀 **【弒君換馬】**\n"
        for s in swaps:
            msg += f"OUT: {s['Sell']['Symbol']} ({s['Sell']['Score']:.1f})\n"
            msg += f"IN : {s['Buy']['Symbol']} ({s['Buy']['Score']:.1f})\n"
        msg += "--------------------\n"

    # 買入指令
    if buys:
        msg += "🟢 **【買入指令】**\n"
        for b in buys:
            msg += f"💰 {b['Symbol']} @ {b['Price']:.2f}\n"
            msg += f"   評分: {b['Score']:.2f}\n"
        msg += "--------------------\n"

    # 持倉監控
    if keeps:
        msg += "🛡️ **【持倉監控】**\n"
        for k in keeps:
            pnl = k['Profit'] * 100
            emoji = "😍" if pnl > 20 else "🤢" if pnl < 0 else "😐"
            msg += f"{emoji} {k['Symbol']}: {pnl:+.1f}%\n"
            # 顯示防守價與停利百分比
            msg += f"   防守: {k['Stop']:.2f} ({k['StopInfo']})\n"
    else:
        msg += "☕ 目前空手\n"

    msg += "━━━━━━━━━━━━━━\n"
    msg += "⚠️ 投資有風險，V196波動極大，請嚴格控倉 (總資產20% max)。"
    
    return msg

# ==========================================
# 主程式
# ==========================================
if __name__ == "__main__":
    result = analyze_market()
    if result:
        regime, sells, keeps, buys, swaps = result
        message = format_message(regime, sells, keeps, buys, swaps)
        send_line_notify(message)
    else:
        print("無法執行分析")
