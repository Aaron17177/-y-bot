import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import csv
import time
from datetime import datetime, timedelta

# ==========================================
# 1. 參數設定 (V212 Apex Predator - Mythic Correction 實戰版)
# ==========================================
# 核心哲學：妖股給耐心 (Stock Rules)，幣與耗損品給紀律 (Crypto Rules)

LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
PORTFOLIO_FILE = 'portfolio.csv'

# --- 資金管理 ---
MAX_TOTAL_POSITIONS = 4  # 4 席位 (25% 倉位)
USD_TWD_RATE = 32.5      # 僅用於顯示估值

# --- 差異化止損設定 (硬止損) ---
STOCK_HARD_STOP = 0.30   # [股票/趨勢ETF] 30% 止損
CRYPTO_HARD_STOP = 0.40  # [幣/耗損ETF] 40% 止損

# --- 差異化移動停利設定 (從高點回落幅度) ---
# [股票] 初始 -25%, 翻倍後 -15%
STOCK_TRAIL_INIT = 0.25
STOCK_TRAIL_TIGHT = 0.15 

# [幣圈] 初始 -40%, 翻倍後 -25%
CRYPTO_TRAIL_INIT = 0.40 
CRYPTO_TRAIL_TIGHT = 0.25

# --- 差異化殭屍清除設定 ---
CRYPTO_ZOMBIE_DAYS = 5   # 僅對「幣圈/耗損資產」啟用：5天不漲就賣

# ==========================================
# 2. 全明星戰力池 (V212 精簡優化版)
# ==========================================
STRATEGIC_POOL = {
    'CRYPTO': [ 
        'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 
        'AVAX-USD', 'NEAR-USD', 'RENDER-USD',        
        'DOGE-USD', 'SHIB-USD', 'PEPE24478-USD',    
        'BONK-USD', 'WIF-USD'                        
    ],
    'LEVERAGE': [ 
        'NVDL', 'SOXL', 'TQQQ', 'FNGU', 'TSLL', 
        'CONL', 'BITU', 'USD', 'TECL', 'MSTU', 'LABU',
        'BITX', 'ETHU', 'WGMI'
    ],
    'US_STOCKS': [ 
        'NVDA', 'AMD', 'TSLA', 'MRNA', 'ZM', 'PTON', 'UBER',
        'PLTR', 'MSTR', 'COIN', 'SMCI', 'ARM', 'AVGO', 'META', 'AMZN', 'NFLX', 
        'LLY', 'VRTX', 'CRWD', 'PANW', 'ORCL', 'SHOP',
        'APP', 'IONQ', 'RGTI', 'RKLB', 'VRT', 'ANET', 'SNOW', 'COST',
        'VST', 'MU', 'AMAT', 'LRCX', 'ASML', 'KLAC', 'GLW',
        'ASTS', 'OKLO', 'VKTX'
    ],
    'TW_STOCKS': [ 
        '2330.TW', '2454.TW', '2317.TW', '2382.TW',
        '3231.TW', '6669.TW', '3017.TW',
        '1519.TW', '1503.TW', '2603.TW', '2609.TW',
        '8996.TW', '6515.TW', '6442.TW', '6139.TW',
        '8299.TWO', '3529.TWO', '3081.TWO', '6739.TWO', '6683.TWO',
        '2359.TW', '3131.TWO', '3583.TW', '8054.TWO',
        '3661.TW', '3443.TW', '3035.TW', '5269.TW', '6531.TW', '2388.TW'
    ],
    'TW_LEVERAGE': [
        '00631L.TW', '00670L.TW'
    ]
}

TIER_1_ASSETS = [
    'BTC-USD', 'ETH-USD', 'SOL-USD',
    'SOXL', 'NVDL', 'TQQQ', 'MSTU', 'CONL', 'FNGU', 'ETHU', 'WGMI',
    'NVDA', 'TSLA', 'MSTR', 'COIN', 'APP', 'PLTR', 'ASTS', 'SMCI',
    '2330.TW', '00631L.TW'
]

# 🔥 V212 關鍵分類：適用幣圈規則 (寬止損+殭屍清除) 的資產
CRYPTO_PROXIES = [
    'ETHU', 'BITX', 'BITU', 'WGMI',  # 純幣 ETF / 礦工
    'MSTU', 'MSTR', 'COIN', 'CONL',  # 幣圈分身
    'NVDL', 'SOXL'                   # 高耗損槓桿 ETF
]

BENCHMARKS = ['^GSPC', 'BTC-USD', '^TWII']

# ==========================================
# 3. 輔助函式
# ==========================================
def get_asset_type(symbol):
    if "-USD" in symbol: return 'CRYPTO'
    if ".TW" in symbol or ".TWO" in symbol:
        if symbol in STRATEGIC_POOL['TW_LEVERAGE']: return 'LEVERAGE'
        return 'TW'
    if any(s == symbol for s in STRATEGIC_POOL['LEVERAGE']): return 'LEVERAGE'
    return 'US_STOCK'

def is_crypto_rules_apply(symbol):
    """判斷是否適用幣圈規則 (寬止損 + 殭屍清除)"""
    atype = get_asset_type(symbol)
    if atype == 'CRYPTO': return True
    if symbol in CRYPTO_PROXIES: return True
    return False

def calculate_indicators(df):
    if len(df) < 100: return None
    df = df.copy()
    
    # 計算均線
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['MA100'] = df['Close'].rolling(window=100).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    
    # 動能：20日漲跌幅
    df['Momentum'] = df['Close'].pct_change(periods=20)
    
    return df.iloc[-1]

def normalize_symbol(raw_symbol):
    raw_symbol = raw_symbol.strip().upper()
    alias_map = {
        'PEPE': 'PEPE24478-USD', 'SHIB': 'SHIB-USD', 'DOGE': 'DOGE-USD',
        'BONK': 'BONK-USD', 'FLOKI': 'FLOKI-USD', 'WIF': 'WIF-USD',
        'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD',
        'TAO': 'TAO22974-USD', 'SUI': 'SUI20947-USD',
        'HYPE': 'HYPE-USD', 'WLD': 'WLD-USD', 'FET': 'FET-USD',
        'MATIC': 'POL-USD', 'POL': 'POL-USD',
        'TIA': 'TIA-USD', 'STX': 'STX4847-USD'    
    }
    if raw_symbol in alias_map: return alias_map[raw_symbol]
    
    otc_list = ['8299', '3529', '3081', '6739', '6683', '8069', '3293', '3661', '3131', '8054', '5269', '6531'] 
    if raw_symbol.isdigit() and len(raw_symbol) == 4:
        if raw_symbol in otc_list: return f"{raw_symbol}.TWO"
        return f"{raw_symbol}.TW"
    
    if (len(raw_symbol) == 5 or len(raw_symbol) == 6) and (raw_symbol.endswith('L') or raw_symbol.endswith('Q')):
         return f"{raw_symbol}.TW"
        
    known_crypto = set([c.split('-')[0] for c in STRATEGIC_POOL['CRYPTO']])
    if raw_symbol in known_crypto:
        for k, v in alias_map.items():
            if raw_symbol == k: return v
        return f"{raw_symbol}-USD"

    return raw_symbol

def load_portfolio():
    holdings = {}
    if not os.path.exists(PORTFOLIO_FILE):
        print("⚠️ 找不到 portfolio.csv，假設目前空手。")
        return holdings

    try:
        with open(PORTFOLIO_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
                # 檢查 CSV 版本，如果沒有 Date 欄位，預設為今天
                has_date = 'EntryDate' in header if header else False
                
                for row in reader:
                    if not row or len(row) < 2: continue
                    symbol = normalize_symbol(row[0])
                    try:
                        entry_price = float(row[1])
                        high_price = float(row[2]) if len(row) > 2 and row[2] else entry_price
                        
                        # 處理買入日期
                        if has_date and len(row) > 3 and row[3]:
                            entry_date = row[3]
                        else:
                            entry_date = datetime.now().strftime('%Y-%m-%d')
                            
                        holdings[symbol] = {
                            'entry_price': entry_price, 
                            'high_price': high_price,
                            'entry_date': entry_date
                        }
                    except ValueError: continue 
            except StopIteration: pass 

        print(f"📋 已讀取持倉監控名單: {list(holdings.keys())}")
        return holdings
    except Exception as e:
        print(f"❌ 讀取 CSV 失敗: {e}")
        return {}

def update_portfolio_csv(holdings, current_prices, new_buys=None):
    try:
        # 更新現有持倉的最高價
        data_to_write = []
        
        # 1. 處理舊持倉 (更新 High Price)
        for symbol, data in holdings.items():
            curr_p = current_prices.get(symbol, 0)
            if curr_p > 0:
                new_high = max(data['high_price'], curr_p)
                data_to_write.append([symbol, data['entry_price'], new_high, data['entry_date']])
            else:
                data_to_write.append([symbol, data['entry_price'], data['high_price'], data['entry_date']])
        
        # 2. 加入新買入 (如果有的話)
        if new_buys:
            for buy in new_buys:
                symbol = buy['Symbol']
                price = buy['Price']
                date = datetime.now().strftime('%Y-%m-%d')
                # 避免重複寫入
                if not any(row[0] == symbol for row in data_to_write):
                     data_to_write.append([symbol, price, price, date])

        with open(PORTFOLIO_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Symbol', 'EntryPrice', 'HighPrice', 'EntryDate'])
            writer.writerows(data_to_write)
        print("✅ Portfolio CSV 已更新 (含日期)")
    except Exception as e:
        print(f"❌ 更新 CSV 失敗: {e}")

def get_live_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        # 嘗試獲取即時價格
        price = ticker.fast_info.get('last_price')
        if price is None or np.isnan(price):
             # 備用方案
             hist = ticker.history(period="1d")
             if not hist.empty:
                 price = hist['Close'].iloc[-1]
        
        if price is not None and not np.isnan(price) and price > 0:
            return price
    except Exception:
        pass
    return None

# ==========================================
# 4. 分析引擎 (V212 Logic)
# ==========================================
def analyze_market():
    # 1. 準備清單
    portfolio = load_portfolio()
    all_pool_tickers = [t for cat in STRATEGIC_POOL for t in STRATEGIC_POOL[cat]]
    all_tickers = list(set(BENCHMARKS + list(portfolio.keys()) + all_pool_tickers))
    
    if 'HYPE-USD' in all_tickers: all_tickers.remove('HYPE-USD')

    print(f"📥 下載 {len(all_tickers)} 檔標的數據...")
    try:
        data = yf.download(all_tickers, period="250d", progress=False, auto_adjust=False)
        if data.empty: return None
        closes = data['Close'].ffill()
    except Exception as e:
        print(f"❌ 數據下載失敗: {e}")
        return None

    # 2. 判斷環境狀態 (Regime Check)
    regime = {}
    
    # 美股 & 槓桿ETF 冬眠線: SPY < 200MA
    spy_series = closes.get('^GSPC', closes.get('SPY'))
    if spy_series is not None:
        spy_last = spy_series.iloc[-1]
        spy_ma200 = spy_series.rolling(200).mean().iloc[-1]
        regime['US_BULL'] = spy_last > spy_ma200
    else:
        regime['US_BULL'] = True 

    # 加密貨幣 冬眠線: BTC < 100MA
    btc_series = closes.get('BTC-USD')
    if btc_series is not None:
        btc_last = btc_series.iloc[-1]
        btc_ma100 = btc_series.rolling(100).mean().iloc[-1]
        regime['CRYPTO_BULL'] = btc_last > btc_ma100
    else:
        regime['CRYPTO_BULL'] = True

    # 台股 冬眠線: TWII < 60MA
    tw_series = closes.get('^TWII')
    if tw_series is not None:
        tw_last = tw_series.iloc[-1]
        tw_ma60 = tw_series.rolling(60).mean().iloc[-1]
        regime['TW_BULL'] = tw_last > tw_ma60
    else:
        regime['TW_BULL'] = regime['US_BULL'] 

    # 3. 建立當前價格表
    current_prices = {}
    for t in all_tickers:
        if t in closes.columns:
            current_prices[t] = closes[t].iloc[-1]

    print("\n🔍 持倉報價校正:")
    for sym in portfolio.keys():
        live_price = get_live_price(sym)
        old_price = current_prices.get(sym, 0)
        if live_price:
            current_prices[sym] = live_price
            print(f"✅ {sym:<15} : {old_price:.2f} -> {live_price:.2f} (即時)")
        else:
            print(f"⚠️ {sym:<15} : {old_price:.2f} (歷史收盤)")
    print("-" * 50)

    # 先不寫入 CSV，等最後確定買賣後再寫入，但這裡需要傳入 current_prices 給後續邏輯

    # 4. 掃描持倉 (Sell Logic: V212)
    sells = []
    keeps = []
    
    for symbol, data in portfolio.items():
        if symbol not in current_prices: continue
        
        curr_price = current_prices[symbol]
        
        # 計算個別標的季線 (MA50)
        ma50 = 0
        if symbol in closes.columns:
            series = closes[symbol].dropna()
            if len(series) >= 60:
                row = calculate_indicators(pd.DataFrame({'Close': series}))
                ma50 = row['MA50']
        
        entry_price = data['entry_price']
        high_price = max(data['high_price'], curr_price)
        entry_date_str = data.get('entry_date', datetime.now().strftime('%Y-%m-%d'))
        entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d')
        
        atype = get_asset_type(symbol)
        use_crypto_rules = is_crypto_rules_apply(symbol)
        
        # A. 冬眠檢查
        is_winter = False
        if atype == 'CRYPTO' and not regime['CRYPTO_BULL']: is_winter = True
        elif atype in ['US_STOCK', 'LEVERAGE'] and not regime['US_BULL']: is_winter = True
        elif atype == 'TW' and not regime['TW_BULL']: is_winter = True
        
        # B. 停損停利參數 (V212 差異化)
        profit_pct = (curr_price - entry_price) / entry_price
        
        if use_crypto_rules:
            # 幣圈規則：寬止損、寬停利
            stop_pct = CRYPTO_HARD_STOP
            if profit_pct > 1.0: 
                trail_limit = 1 - CRYPTO_TRAIL_TIGHT # 0.75
            else:
                trail_limit = 1 - CRYPTO_TRAIL_INIT  # 0.60
            rule_name = "瘋狗規則"
        else:
            # 股票規則：標準止損、標準停利
            stop_pct = STOCK_HARD_STOP
            if profit_pct > 1.0:
                trail_limit = 1 - STOCK_TRAIL_TIGHT  # 0.85
            else:
                trail_limit = 1 - STOCK_TRAIL_INIT   # 0.75
            rule_name = "股票規則"

        hard_stop_price = entry_price * (1 - stop_pct)
        trail_stop_price = high_price * trail_limit
        active_stop_price = max(hard_stop_price, trail_stop_price)
        
        stop_info = ""
        if active_stop_price == hard_stop_price:
            stop_info = f"硬損-{int(stop_pct*100)}%"
        else:
            stop_info = f"高點-{int((1-trail_limit)*100)}%"

        # C. 檢查出場條件
        reason = ""
        days_held = (datetime.now() - entry_date).days

        # 1. 殭屍清除 (僅適用 Crypto Rules)
        if not reason and use_crypto_rules and days_held > CRYPTO_ZOMBIE_DAYS and curr_price <= entry_price:
             reason = f"💤 殭屍清除 (> {CRYPTO_ZOMBIE_DAYS}天滯漲)"

        # 2. 常規檢查
        if not reason:
            if is_winter:
                reason = "❄️ 分區冬眠 (清倉)"
            elif curr_price < hard_stop_price:
                reason = f"🔴 深淵止損 (-{int(stop_pct*100)}%)"
            elif curr_price < trail_stop_price:
                reason = f"🛡️ 移動停利 ({stop_info})"
            elif ma50 > 0 and curr_price < ma50:
                 reason = "❌ 跌破季線 (MA50)"
        
        if reason:
            sells.append({'Symbol': symbol, 'Price': curr_price, 'Reason': reason, 'PnL': f"{profit_pct*100:.1f}%"})
        else:
            # 計算分數 (用於弒君)
            final_score = 0
            if symbol in closes.columns and len(closes[symbol].dropna()) >= 20:
                series = closes[symbol].dropna()
                row = calculate_indicators(pd.DataFrame({'Close': series}))
                score = row['Momentum']
                
                # 加權乘數
                multiplier = 1.0
                if symbol in TIER_1_ASSETS: multiplier = 1.2
                if atype == 'CRYPTO': multiplier = 1.4
                if atype == 'LEVERAGE': multiplier = 1.5
                
                final_score = score * multiplier
            
            keeps.append({
                'Symbol': symbol, 'Price': curr_price, 'Entry': entry_price, 
                'Score': final_score, 'Profit': profit_pct, 
                'Stop': active_stop_price, 'StopInfo': stop_info,
                'Rule': rule_name, 'Days': days_held
            })

    # 5. 掃描機會 (Buy Logic)
    candidates = []
    
    valid_pool = []
    if regime['CRYPTO_BULL']: valid_pool += STRATEGIC_POOL['CRYPTO']
    if regime['US_BULL']: 
        valid_pool += STRATEGIC_POOL['US_STOCKS']
        valid_pool += STRATEGIC_POOL['LEVERAGE']
    if regime['TW_BULL']: 
        valid_pool += STRATEGIC_POOL['TW_STOCKS']
        valid_pool += STRATEGIC_POOL['TW_LEVERAGE']
    
    if 'HYPE-USD' in valid_pool: valid_pool.remove('HYPE-USD')

    for t in valid_pool:
        if t in portfolio or t not in closes.columns: continue
        
        series = closes[t].dropna()
        if len(series) < 60: continue
        
        row = calculate_indicators(pd.DataFrame({'Close': series}))
        
        # 多頭排列濾網
        if not (row['Close'] > row['MA20'] and row['MA20'] > row['MA50'] and row['Close'] > row['MA60']):
            continue
            
        raw_score = row['Momentum']
        if pd.isna(raw_score) or raw_score <= 0: continue
        
        multiplier = 1.0
        atype = get_asset_type(t)
        
        if t in TIER_1_ASSETS: multiplier = 1.2
        if atype == 'CRYPTO': multiplier = 1.4
        if atype == 'LEVERAGE': multiplier = 1.5
        
        final_score = raw_score * multiplier
        
        candidates.append({'Symbol': t, 'Price': row['Close'], 'Score': final_score})
        
    candidates.sort(key=lambda x: x['Score'], reverse=True)
    
    # 6. 弒君檢查 (Killer Swap - Threshold 1.5x)
    swaps = []
    if keeps and candidates:
        worst_holding = min(keeps, key=lambda x: x['Score'])
        best_candidate = candidates[0]
        
        if best_candidate['Score'] > worst_holding['Score'] * 1.5:
            swap_info = {
                'Sell': worst_holding,
                'Buy': best_candidate,
                'Reason': f"💀 弒君換馬 ({best_candidate['Score']:.2f} vs {worst_holding['Score']:.2f})"
            }
            if len(candidates) > 1 and candidates[1]['Symbol'] != best_candidate['Symbol']:
                swap_info['Backup'] = candidates[1]
                
            swaps.append(swap_info)
            # 模擬賣出
            keeps = [k for k in keeps if k != worst_holding]
            sells.append({'Symbol': worst_holding['Symbol'], 'Price': worst_holding['Price'], 'Reason': "💀 弒君被換", 'PnL': f"{worst_holding['Profit']*100:.1f}%"})
            
    # 7. 空位買入
    buys = []
    final_buys_for_csv = [] # 用於寫入 CSV
    
    open_slots = MAX_TOTAL_POSITIONS - len(keeps) - len(swaps)
    
    swap_buy_symbols = [s['Buy']['Symbol'] for s in swaps]
    available_candidates = [c for c in candidates if c['Symbol'] not in swap_buy_symbols]
    
    # 將 Swap 的買入也加入待寫入列表
    for s in swaps:
        final_buys_for_csv.append({'Symbol': s['Buy']['Symbol'], 'Price': s['Buy']['Price']})

    num_recommendations = 0
    if open_slots > 0:
        num_recommendations = open_slots + 1
    
    if num_recommendations > 0 and available_candidates:
        for i in range(min(num_recommendations, len(available_candidates))):
            cand = available_candidates[i]
            is_backup = (i >= open_slots)
            
            buys.append({
                'Symbol': cand['Symbol'],
                'Price': cand['Price'],
                'Score': cand['Score'],
                'IsBackup': is_backup
            })
            
            if not is_backup:
                final_buys_for_csv.append({'Symbol': cand['Symbol'], 'Price': cand['Price']})

    # 最後執行 CSV 更新 (剔除賣出，加入買入，更新留倉)
    # 這裡只做一次性更新，注意：真實下單需要人工確認，所以這裡只是模擬「如果執行了」的狀態
    # 為了 GitHub Action 的連續性，我們假設用戶會跟單，所以更新 CSV
    # 但需注意 Sells 實際需要被移除。
    
    final_holdings = {}
    
    # 保留 Keeps
    for k in keeps:
        sym = k['Symbol']
        final_holdings[sym] = portfolio[sym] # 保持原樣
    
    # 執行更新
    update_portfolio_csv(final_holdings, current_prices, final_buys_for_csv)

    return regime, sells, keeps, buys, swaps

# ==========================================
# 5. 訊息發送
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
    msg = f"🦁 **V212 神話修正版**\n{datetime.now().strftime('%Y-%m-%d')}\n"
    msg += "━━━━━━━━━━━━━━\n"
    
    us_icon = "🟢" if regime.get('US_BULL', False) else "❄️"
    crypto_icon = "🟢" if regime.get('CRYPTO_BULL', False) else "❄️"
    tw_icon = "🟢" if regime.get('TW_BULL', False) else "❄️"
    msg += f"環境: 美{us_icon} | 幣{crypto_icon} | 台{tw_icon}\n"
    msg += "━━━━━━━━━━━━━━\n"

    if sells:
        msg += "🔴 **【賣出指令】**\n"
        for s in sells:
            msg += f"❌ {s['Symbol']} ({s['Reason']})\n"
            msg += f"   現價: {s['Price']:.2f} | 損益: {s['PnL']}\n"
        msg += "--------------------\n"

    if swaps:
        msg += "💀 **【弒君換馬】**\n"
        for s in swaps:
            msg += f"OUT: {s['Sell']['Symbol']} ({s['Sell']['Score']:.1f})\n"
            msg += f"IN : {s['Buy']['Symbol']} ({s['Buy']['Score']:.1f})\n"
            if 'Backup' in s:
                msg += f"   ✨ 備選: {s['Backup']['Symbol']} ({s['Backup']['Score']:.1f})\n"
        msg += "--------------------\n"

    if buys:
        msg += "🟢 **【買入指令】**\n"
        for b in buys:
            if b.get('IsBackup', False):
                msg += f"✨ {b['Symbol']} @ {b['Price']:.2f} (備選)\n"
                msg += f"   評分: {b['Score']:.2f}\n"
            else:
                msg += f"💰 {b['Symbol']} @ {b['Price']:.2f} (首選)\n"
                msg += f"   評分: {b['Score']:.2f}\n"
        msg += "--------------------\n"

    if keeps:
        msg += "🛡️ **【持倉監控】**\n"
        for k in keeps:
            pnl = k['Profit'] * 100
            emoji = "😍" if pnl > 20 else "🤢" if pnl < 0 else "😐"
            rule_tag = "⚡" if "瘋狗" in k['Rule'] else "🐢"
            days = k['Days']
            day_str = f"{days}天"
            
            msg += f"{emoji} {k['Symbol']} {rule_tag}: {pnl:+.1f}% ({day_str})\n"
            msg += f"   現價: {k['Price']:.2f} | 防守: {k['Stop']:.2f}\n"
            msg += f"   {k['StopInfo']}\n"
    else:
        msg += "☕ 目前空手\n"

    msg += "━━━━━━━━━━━━━━\n"
    msg += "⚡:瘋狗規則 (5天殭屍清除/40%止損)\n"
    msg += "🐢:股票規則 (耐心持有/30%止損)\n"
    
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
