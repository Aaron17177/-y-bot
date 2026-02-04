import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import csv
import time
from datetime import datetime, timedelta

# ==========================================
# 1. 參數設定 (V212 Apex Predator - Mythic Correction)
# ==========================================
# 功能更新：買入訊號明確顯示止損趴數 (30% 或 40%)

LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
PORTFOLIO_FILE = 'portfolio.csv'

# --- 資金管理 ---
MAX_TOTAL_POSITIONS = 4
USD_TWD_RATE = 32.5

# --- 差異化止損設定 ---
STOCK_HARD_STOP = 0.30
CRYPTO_HARD_STOP = 0.40

# --- 差異化移動停利設定 ---
STOCK_TRAIL_INIT = 0.25
STOCK_TRAIL_TIGHT = 0.15 
CRYPTO_TRAIL_INIT = 0.40 
CRYPTO_TRAIL_TIGHT = 0.25

# --- 差異化殭屍清除設定 ---
CRYPTO_ZOMBIE_DAYS = 5 

# ==========================================
# 2. 全明星戰力池 (V212)
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

CRYPTO_PROXIES = [
    'ETHU', 'BITX', 'BITU', 'WGMI',
    'MSTU', 'MSTR', 'COIN', 'CONL',
    'NVDL', 'SOXL'
]

BENCHMARKS = ['^GSPC', 'BTC-USD', '^TWII']

# ==========================================
# 3. 輔助函式
# ==========================================
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

    for cat in STRATEGIC_POOL:
        for ticker in STRATEGIC_POOL[cat]:
            if "." in ticker:
                code, suffix = ticker.split('.')
                if raw_symbol == code:
                    return ticker
            if "-" in ticker:
                code = ticker.split('-')[0]
                if raw_symbol == code:
                    return ticker
    
    if raw_symbol.isdigit() and len(raw_symbol) == 4:
         return f"{raw_symbol}.TW"
    if raw_symbol in ['BTC', 'ETH', 'SOL', 'BNB', 'AVAX']:
        return f"{raw_symbol}-USD"

    return raw_symbol

def get_asset_type(symbol):
    if "-USD" in symbol: return 'CRYPTO'
    if ".TW" in symbol or ".TWO" in symbol:
        if symbol in STRATEGIC_POOL['TW_LEVERAGE']: return 'LEVERAGE'
        return 'TW'
    if any(s == symbol for s in STRATEGIC_POOL['LEVERAGE']): return 'LEVERAGE'
    return 'US_STOCK'

def is_crypto_rules_apply(symbol):
    atype = get_asset_type(symbol)
    if atype == 'CRYPTO': return True
    if symbol in CRYPTO_PROXIES: return True
    return False

def calculate_indicators(df):
    if len(df) < 100: return None
    df = df.copy()
    
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['MA100'] = df['Close'].rolling(window=100).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    df['Momentum'] = df['Close'].pct_change(periods=20)
    
    return df.iloc[-1]

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
                has_date = 'EntryDate' in header if header else False
                
                for row in reader:
                    if not row or len(row) < 2: continue
                    symbol = normalize_symbol(row[0])
                    try:
                        entry_price = float(row[1])
                        entry_date = datetime.now().strftime('%Y-%m-%d')
                        if has_date:
                            try:
                                date_idx = header.index('EntryDate')
                                if len(row) > date_idx and row[date_idx]:
                                    entry_date = row[date_idx]
                            except ValueError:
                                if len(row) >= 3 and '-' in str(row[-1]):
                                    entry_date = row[-1]
                        
                        holdings[symbol] = {
                            'entry_price': entry_price, 
                            'entry_date': entry_date
                        }
                    except ValueError: continue 
            except StopIteration: pass 

        print(f"📋 已讀取持倉監控名單: {list(holdings.keys())}")
        return holdings
    except Exception as e:
        print(f"❌ 讀取 CSV 失敗: {e}")
        return {}

def update_portfolio_csv(holdings, new_buys=None):
    try:
        data_to_write = []
        for symbol, data in holdings.items():
            data_to_write.append([symbol, data['entry_price'], data['entry_date']])
        
        if new_buys:
            for buy in new_buys:
                symbol = buy['Symbol']
                price = buy['Price']
                date = datetime.now().strftime('%Y-%m-%d')
                if not any(row[0] == symbol for row in data_to_write):
                     data_to_write.append([symbol, price, date])

        with open(PORTFOLIO_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Symbol', 'EntryPrice', 'EntryDate'])
            writer.writerows(data_to_write)
        print("✅ Portfolio CSV 已更新")
    except Exception as e:
        print(f"❌ 更新 CSV 失敗: {e}")

def get_live_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info.get('last_price')
        if price is None or np.isnan(price):
             hist = ticker.history(period="1d")
             if not hist.empty:
                 price = hist['Close'].iloc[-1]
        
        if price is not None and not np.isnan(price) and price > 0:
            return price
    except Exception:
        pass
    return None

# ==========================================
# 4. 分析引擎
# ==========================================
def analyze_market():
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

    regime = {}
    spy_series = closes.get('^GSPC', closes.get('SPY'))
    if spy_series is not None:
        spy_last = spy_series.iloc[-1]
        spy_ma200 = spy_series.rolling(200).mean().iloc[-1]
        regime['US_BULL'] = spy_last > spy_ma200
    else:
        regime['US_BULL'] = True 

    btc_series = closes.get('BTC-USD')
    if btc_series is not None:
        btc_last = btc_series.iloc[-1]
        btc_ma100 = btc_series.rolling(100).mean().iloc[-1]
        regime['CRYPTO_BULL'] = btc_last > btc_ma100
    else:
        regime['CRYPTO_BULL'] = True

    tw_series = closes.get('^TWII')
    if tw_series is not None:
        tw_last = tw_series.iloc[-1]
        tw_ma60 = tw_series.rolling(60).mean().iloc[-1]
        regime['TW_BULL'] = tw_last > tw_ma60
    else:
        regime['TW_BULL'] = regime['US_BULL'] 

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

    sells = []
    keeps = []
    
    for symbol, data in portfolio.items():
        if symbol not in current_prices: continue
        
        curr_price = current_prices[symbol]
        ma50 = 0
        if symbol in closes.columns:
            series = closes[symbol].dropna()
            if len(series) >= 60:
                row = calculate_indicators(pd.DataFrame({'Close': series}))
                ma50 = row['MA50']
        
        entry_price = data['entry_price']
        entry_date_str = data.get('entry_date', datetime.now().strftime('%Y-%m-%d'))
        try:
            entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d')
        except ValueError:
            entry_date = datetime.now()

        atype = get_asset_type(symbol)
        use_crypto_rules = is_crypto_rules_apply(symbol)
        
        is_winter = False
        if atype == 'CRYPTO' and not regime['CRYPTO_BULL']: is_winter = True
        elif atype in ['US_STOCK', 'LEVERAGE'] and not regime['US_BULL']: is_winter = True
        elif atype == 'TW' and not regime['TW_BULL']: is_winter = True
        
        profit_pct = (curr_price - entry_price) / entry_price
        
        if use_crypto_rules:
            stop_pct = CRYPTO_HARD_STOP
            rule_name = "瘋狗規則"
        else:
            stop_pct = STOCK_HARD_STOP
            rule_name = "股票規則"

        hard_stop_price = entry_price * (1 - stop_pct)
        
        reason = ""
        days_held = (datetime.now() - entry_date).days

        if not reason and use_crypto_rules and days_held > CRYPTO_ZOMBIE_DAYS and curr_price <= entry_price:
             reason = f"💤 殭屍清除 (> {CRYPTO_ZOMBIE_DAYS}天滯漲)"

        if not reason:
            if is_winter:
                reason = "❄️ 分區冬眠 (清倉)"
            elif curr_price < hard_stop_price:
                reason = f"🔴 深淵止損 (-{int(stop_pct*100)}%)"
            elif ma50 > 0 and curr_price < ma50:
                 reason = "❌ 跌破季線 (MA50)"
        
        if reason:
            sells.append({'Symbol': symbol, 'Price': curr_price, 'Reason': reason, 'PnL': f"{profit_pct*100:.1f}%"})
        else:
            final_score = 0
            if symbol in closes.columns and len(closes[symbol].dropna()) >= 20:
                series = closes[symbol].dropna()
                row = calculate_indicators(pd.DataFrame({'Close': series}))
                score = row['Momentum']
                
                multiplier = 1.0
                if symbol in TIER_1_ASSETS: multiplier = 1.2
                if atype == 'CRYPTO': multiplier = 1.4
                if atype == 'LEVERAGE': multiplier = 1.5
                
                final_score = score * multiplier
            
            keeps.append({
                'Symbol': symbol, 'Price': curr_price, 'Entry': entry_price, 
                'Score': final_score, 'Profit': profit_pct, 
                'Rule': rule_name, 'Days': days_held
            })

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
        
        # 決定止損比例
        is_crypto_rule = is_crypto_rules_apply(t)
        sl_pct = CRYPTO_HARD_STOP if is_crypto_rule else STOCK_HARD_STOP
        
        candidates.append({'Symbol': t, 'Price': row['Close'], 'Score': final_score, 'StopLoss': sl_pct})
        
    candidates.sort(key=lambda x: x['Score'], reverse=True)
    
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
            keeps = [k for k in keeps if k != worst_holding]
            sells.append({'Symbol': worst_holding['Symbol'], 'Price': worst_holding['Price'], 'Reason': "💀 弒君被換", 'PnL': f"{worst_holding['Profit']*100:.1f}%"})
            
    buys = []
    final_buys_for_csv = [] 
    
    open_slots = MAX_TOTAL_POSITIONS - len(keeps) - len(swaps)
    swap_buy_symbols = [s['Buy']['Symbol'] for s in swaps]
    available_candidates = [c for c in candidates if c['Symbol'] not in swap_buy_symbols]
    
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
                'StopLoss': cand['StopLoss'], # 傳遞止損資訊
                'IsBackup': is_backup
            })
            
            if not is_backup:
                final_buys_for_csv.append({'Symbol': cand['Symbol'], 'Price': cand['Price']})

    final_holdings_map = {}
    for k in keeps:
        final_holdings_map[k['Symbol']] = {'entry_price': k['Entry'], 'entry_date': portfolio[k['Symbol']]['entry_date']}
    
    update_portfolio_csv(final_holdings_map, final_buys_for_csv)

    return regime, sells, keeps, buys, swaps

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
        if response.status_code != 200:
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
            sl_pct = int(s['Buy']['StopLoss'] * 100)
            msg += f"OUT: {s['Sell']['Symbol']} ({s['Sell']['Score']:.1f})\n"
            msg += f"IN : {s['Buy']['Symbol']} ({s['Buy']['Score']:.1f})\n"
            msg += f"   🛑 建議止損: -{sl_pct}%\n"
            if 'Backup' in s:
                bk_sl = int(s['Backup']['StopLoss'] * 100)
                msg += f"   ✨ 備選: {s['Backup']['Symbol']} (止損-{bk_sl}%)\n"
        msg += "--------------------\n"

    if buys:
        msg += "🟢 **【買入指令】**\n"
        for b in buys:
            sl_pct = int(b['StopLoss'] * 100)
            if b.get('IsBackup', False):
                msg += f"✨ {b['Symbol']} @ {b['Price']:.2f} (備選)\n"
                msg += f"   評分: {b['Score']:.2f} | 止損: -{sl_pct}%\n"
            else:
                msg += f"💰 {b['Symbol']} @ {b['Price']:.2f} (首選)\n"
                msg += f"   評分: {b['Score']:.2f}\n"
                msg += f"   🛑 建議止損: -{sl_pct}%\n"
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
            msg += f"   現價: {k['Price']:.2f}\n"
    else:
        msg += "☕ 目前空手\n"

    msg += "━━━━━━━━━━━━━━\n"
    msg += "⚡:瘋狗規則 (5天殭屍清除/40%止損)\n"
    msg += "🐢:股票規則 (耐心持有/30%止損)\n"
    msg += "※ 移動停利請至平台自行設定"
    
    return msg

if __name__ == "__main__":
    result = analyze_market()
    if result:
        regime, sells, keeps, buys, swaps = result
        message = format_message(regime, sells, keeps, buys, swaps)
        send_line_notify(message)
    else:
        print("無法執行分析")
