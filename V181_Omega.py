import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import csv
import time
from datetime import datetime, timedelta

# ==========================================
# 1. 參數設定 (V212 Apex Predator - God Mode Live)
# ==========================================
# 策略核心：
# 1. 移除 RS 濾網：避免台積電效應導致的賣飛。
# 2. 調整 Crypto 貪婪模式：獲利翻倍後，放寬止損至 35% (在此僅做為通知建議)。
# 3. 新增 台股動能門檻：MOM_20 > 5% 才進場。
# 4. 維持 美股槓桿 3 天極速汰換。

LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
PORTFOLIO_FILE = 'portfolio.csv'

# --- 資金管理 ---
MAX_TOTAL_POSITIONS = 4
USD_TWD_RATE = 32.5

# --- 六大板塊專屬參數 (God Mode) ---
# 包含：硬止損(Stop), 殭屍清除天數(Zombie), 初始移動停利(Trail_Init), 獲利翻倍後移動停利(Trail_Tight)
SECTOR_PARAMS = {
    'CRYPTO_SPOT': {'stop': 0.40, 'zombie': 5,  'trail_init': 0.40, 'trail_tight': 0.35, 'desc': '幣圈現貨'},
    'CRYPTO_LEV':  {'stop': 0.45, 'zombie': 4,  'trail_init': 0.45, 'trail_tight': 0.30, 'desc': '幣圈槓桿'},
    'US_STOCK':    {'stop': 0.25, 'zombie': 12, 'trail_init': 0.25, 'trail_tight': 0.15, 'desc': '美股個股'},
    'US_LEV':      {'stop': 0.30, 'zombie': 3,  'trail_init': 0.30, 'trail_tight': 0.20, 'desc': '美股槓桿'},
    'TW_STOCK':    {'stop': 0.25, 'zombie': 12, 'trail_init': 0.25, 'trail_tight': 0.15, 'desc': '台股個股'},
    'TW_LEV':      {'stop': 0.30, 'zombie': 8,  'trail_init': 0.30, 'trail_tight': 0.20, 'desc': '台股槓桿'}
}

# ==========================================
# 2. 戰略資產池 (Strategic Pool)
# ==========================================
# 定義特定分類，未列出的將依後綴自動判斷
SPECIAL_LIST = {
    'CRYPTO_LEV': [
        'BITX', 'ETHU', 'BITU', 'WGMI', 'CONL', 'MSTU', 'MSTR', 'COIN'
    ],
    'US_LEV': [
        'NVDL', 'SOXL', 'TQQQ', 'FNGU', 'TSLL', 'USD', 'TECL', 'LABU', 'BULZ', 'SOXS'
    ],
    'TW_LEV': [
        '00631L.TW', '00670L.TW'
    ]
}

# 觀察名單 (可自行增減，程式會從這裡選股)
WATCHLIST = [
    # --- Crypto ---
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'AVAX-USD', 'NEAR-USD', 'RENDER-USD', 
    'DOGE-USD', 'SHIB-USD', 'PEPE24478-USD', 'BONK-USD', 'WIF-USD', 'SUI20947-USD',
    'BITX', 'ETHU', 'CONL', 'MSTU', 'MSTR', 'COIN', 'WGMI',
    
    # --- US Stocks & Lev ---
    'NVDA', 'NVDL', 'TSLA', 'TSLL', 'PLTR', 'APP', 'OKLO', 'RGTI', 'ASTS',
    'SMCI', 'ARM', 'AVGO', 'META', 'AMZN', 'NFLX', 'LLY', 'VRTX', 'CRWD', 
    'PANW', 'ORCL', 'SHOP', 'IONQ', 'RKLB', 'VRT', 'ANET', 'SNOW', 'COST', 
    'VST', 'MU', 'AMAT', 'LRCX', 'ASML', 'KLAC', 'GLW', 'SOXL', 'TQQQ', 'TECL', 'LABU',

    # --- TW Stocks ---
    '2330.TW', '2454.TW', '2317.TW', '2382.TW', '3231.TW', '6669.TW', '3017.TW',
    '1519.TW', '1503.TW', '2603.TW', '2609.TW', '8996.TW', '6515.TW', '6442.TW', 
    '6139.TW', '8299.TWO', '3529.TWO', '3081.TWO', '6739.TWO', '6683.TWO',
    '2359.TW', '3131.TWO', '3583.TW', '8054.TWO', '3661.TW', '3443.TW', 
    '3035.TW', '5269.TW', '6531.TW', '2388.TW'
]

TIER_1_ASSETS = [
    'BTC-USD', 'ETH-USD', 'SOL-USD',
    'SOXL', 'NVDL', 'TQQQ', 'MSTU', 'CONL', 'FNGU', 'ETHU', 'WGMI',
    'NVDA', 'TSLA', 'MSTR', 'COIN', 'APP', 'PLTR', 'ASTS', 'SMCI',
    '2330.TW', '00631L.TW'
]

BENCHMARKS = ['^GSPC', 'BTC-USD', '^TWII']

# ==========================================
# 3. 輔助函式
# ==========================================
def normalize_symbol(raw_symbol):
    # 1. 清理輸入
    raw_symbol = str(raw_symbol).strip().upper()
    
    # 2. 處理常見 Crypto 別名
    mapping = {
        'PEPE': 'PEPE24478-USD', 'SHIB': 'SHIB-USD', 'DOGE': 'DOGE-USD',
        'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'RNDR': 'RENDER-USD'
    }
    if raw_symbol in mapping:
        return mapping[raw_symbol]
        
    # 3. [修復重點] 自動補全台股後綴 (.TW / .TWO)
    # 如果是純數字代碼，嘗試從 WATCHLIST 找尋正確的完整代碼
    if raw_symbol.isdigit():
        for t in WATCHLIST:
            # 檢查 WATCHLIST 中的台股代碼 (e.g., '2330.TW')
            if ('.TW' in t or '.TWO' in t) and t.startswith(raw_symbol + '.'):
                return t
        
        # 如果 WATCHLIST 找不到，預設嘗試加 .TW (上市)
        return f"{raw_symbol}.TW"

    return raw_symbol

def get_sector(symbol):
    # 判斷板塊歸屬
    if symbol in SPECIAL_LIST['CRYPTO_LEV']: return 'CRYPTO_LEV'
    if symbol in SPECIAL_LIST['US_LEV']: return 'US_LEV'
    if symbol in SPECIAL_LIST['TW_LEV']: return 'TW_LEV'
    
    if "-USD" in symbol: return 'CRYPTO_SPOT'
    if ".TW" in symbol or ".TWO" in symbol: return 'TW_STOCK'
    return 'US_STOCK'

def calculate_indicators(df):
    if len(df) < 100: return None
    df = df.copy()
    
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    df['MA100'] = df['Close'].rolling(window=100).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    # 原始動能 (God Mode 不使用平滑)
    df['Momentum'] = df['Close'].pct_change(periods=20)
    
    return df.iloc[-1]

def load_portfolio():
    holdings = {}
    if not os.path.exists(PORTFOLIO_FILE):
        return holdings

    try:
        with open(PORTFOLIO_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            try:
                header = next(reader) # Skip header
                for row in reader:
                    if not row or len(row) < 2: continue
                    # 在讀取時就進行標準化，修復缺少後綴的問題
                    symbol = normalize_symbol(row[0])
                    try:
                        entry_price = float(row[1])
                        # 嘗試讀取日期，若無則預設今日
                        entry_date = row[2] if len(row) > 2 else datetime.now().strftime('%Y-%m-%d')
                        holdings[symbol] = {'entry_price': entry_price, 'entry_date': entry_date}
                    except ValueError: continue 
            except StopIteration: pass 
        return holdings
    except Exception as e:
        print(f"❌ 讀取 CSV 失敗: {e}")
        return {}

def update_portfolio_csv(holdings, new_buys=None):
    # 此函數只會模擬更新，不會實際覆蓋，除非您有需要本地寫入
    # GitHub Action 環境中，寫入檔案不會持久化，除非 Commit
    try:
        data_to_write = []
        for symbol, data in holdings.items():
            data_to_write.append([symbol, data['entry_price'], data['entry_date']])
        
        if new_buys:
            today = datetime.now().strftime('%Y-%m-%d')
            for buy in new_buys:
                if not any(row[0] == buy['Symbol'] for row in data_to_write):
                    data_to_write.append([buy['Symbol'], buy['Price'], today])

        with open(PORTFOLIO_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Symbol', 'EntryPrice', 'EntryDate'])
            writer.writerows(data_to_write)
        print("✅ Portfolio CSV 已更新 (暫存)")
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
# 4. 分析引擎 (God Mode Engine)
# ==========================================
def analyze_market():
    portfolio = load_portfolio()
    
    # 合併所有需要下載的標的
    all_tickers = list(set(BENCHMARKS + list(portfolio.keys()) + WATCHLIST))
    
    print(f"📥 下載 {len(all_tickers)} 檔標的數據...")
    try:
        # 下載較長天期以計算 MA200
        data = yf.download(all_tickers, period="300d", progress=False, auto_adjust=False)
        if data.empty: return None
        closes = data['Close'].ffill()
    except Exception as e:
        print(f"❌ 數據下載失敗: {e}")
        return None

    # --- 1. 判斷大盤環境 (Regime) ---
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

    # 獲取當前價格
    current_prices = {}
    for t in all_tickers:
        if t in closes.columns:
            current_prices[t] = closes[t].iloc[-1]
    
    sells = []
    keeps = []
    
    # --- 2. 持倉健檢 (賣出邏輯) ---
    for symbol, data in portfolio.items():
        if symbol not in current_prices: 
            # 如果還是找不到價格，標記為 NaN (避免崩潰，並提示)
            sells.append({
                'Symbol': symbol, 'Price': 0, 
                'Reason': "❌ 無法獲取報價(代碼錯誤?)", 'PnL': "nan%",
                'Sector': 'UNKNOWN'
            })
            continue
        
        curr_price = current_prices[symbol]
        
        # 再次確認價格有效性
        if np.isnan(curr_price) or curr_price == 0:
             sells.append({
                'Symbol': symbol, 'Price': 0, 
                'Reason': "❌ 無法獲取報價(代碼錯誤?)", 'PnL': "nan%",
                'Sector': 'UNKNOWN'
            })
             continue

        entry_price = data['entry_price']
        entry_date_str = data.get('entry_date', datetime.now().strftime('%Y-%m-%d'))
        
        try:
            entry_date = datetime.strptime(entry_date_str, '%Y-%m-%d')
        except ValueError:
            entry_date = datetime.now()

        sector = get_sector(symbol)
        params = SECTOR_PARAMS.get(sector, SECTOR_PARAMS['US_STOCK'])
        
        is_winter = False
        if 'CRYPTO' in sector and not regime['CRYPTO_BULL']: is_winter = True
        elif 'US' in sector and not regime['US_BULL']: is_winter = True
        elif 'TW' in sector and not regime['TW_BULL']: is_winter = True
        
        profit_pct = (curr_price - entry_price) / entry_price
        days_held = (datetime.now() - entry_date).days
        
        reason = ""

        # A. 殭屍清除 (Zombie Cleanup)
        if days_held > params['zombie'] and profit_pct <= 0:
            reason = f"💤 殭屍清除 (持有{days_held}天未獲利)"
        
        # B. 分區冬眠 (Hibernation)
        elif is_winter:
            reason = "❄️ 分區冬眠 (跌破長均線)"
            
        # C. 硬止損 (Hard Stop)
        elif profit_pct < -params['stop']:
            reason = f"🔴 觸及止損 ({profit_pct*100:.1f}%)"
        
        # D. 季線保護 (Stocks Only)
        elif sector in ['US_STOCK', 'TW_STOCK']:
             series = closes[symbol].dropna()
             if len(series) >= 60:
                 ma50 = series.rolling(50).mean().iloc[-1] 
                 ma60 = series.rolling(60).mean().iloc[-1] 
                 threshold = ma60 if sector == 'TW_STOCK' else ma50
                 if curr_price < threshold:
                     reason = "❌ 跌破季線"

        if reason:
            sells.append({
                'Symbol': symbol, 'Price': curr_price, 
                'Reason': reason, 'PnL': f"{profit_pct*100:.1f}%",
                'Sector': sector
            })
        else:
            # 計算持倉分數 (用於換馬比較)
            score = 0
            if symbol in closes.columns and len(closes[symbol].dropna()) >= 20:
                 series = closes[symbol].dropna()
                 # God Mode: 使用原始 MOM20，不平滑
                 mom = series.pct_change(periods=20).iloc[-1]
                 
                 multiplier = 1.0
                 if symbol in TIER_1_ASSETS: multiplier = 1.2
                 if 'CRYPTO' in sector: multiplier = 1.4
                 if 'LEV' in sector: multiplier = 1.5
                 
                 score = mom * multiplier

            keeps.append({
                'Symbol': symbol, 'Price': curr_price, 'Entry': entry_price, 
                'Score': score, 'Profit': profit_pct, 
                'Days': days_held, 'Sector': sector
            })

    # --- 3. 選股掃描 (買入邏輯) ---
    candidates = []
    
    scan_pool = []
    if regime['CRYPTO_BULL']: 
        scan_pool += [t for t in WATCHLIST if 'CRYPTO' in get_sector(t)]
    if regime['US_BULL']: 
        scan_pool += [t for t in WATCHLIST if 'US' in get_sector(t)]
    if regime['TW_BULL']: 
        scan_pool += [t for t in WATCHLIST if 'TW' in get_sector(t)]
    
    scan_pool = list(set(scan_pool)) # 去重

    for t in scan_pool:
        if t in portfolio or t not in closes.columns: continue
        
        series = closes[t].dropna()
        if len(series) < 65: continue # 資料不足
        
        row = calculate_indicators(pd.DataFrame({'Close': series}))
        
        # 均線多頭排列過濾
        if not (row['Close'] > row['MA20'] and row['MA20'] > row['MA50'] and row['Close'] > row['MA60']):
            continue
            
        raw_score = row['Momentum'] # MOM20
        
        # God Mode: 台股動能門檻 > 5%
        sector = get_sector(t)
        if sector == 'TW_STOCK' and raw_score < 0.05:
            continue
            
        if pd.isna(raw_score) or raw_score <= 0: continue
        
        multiplier = 1.0
        if t in TIER_1_ASSETS: multiplier = 1.2
        if 'CRYPTO' in sector: multiplier = 1.4
        if 'LEV' in sector: multiplier = 1.5
        
        final_score = raw_score * multiplier
        stop_loss_pct = SECTOR_PARAMS[sector]['stop']
        
        candidates.append({
            'Symbol': t, 'Price': row['Close'], 'Score': final_score, 
            'Sector': sector, 'StopLoss': stop_loss_pct
        })
        
    candidates.sort(key=lambda x: x['Score'], reverse=True)
    
    # --- 4. 弒君換馬 (Killer Swap) ---
    swaps = []
    if keeps and candidates:
        worst_holding = min(keeps, key=lambda x: x['Score'])
        best_candidate = candidates[0]
        
        # 換馬條件：新標的分數 > 舊標的 1.5 倍
        if best_candidate['Score'] > worst_holding['Score'] * 1.5:
            swap_info = {
                'Sell': worst_holding,
                'Buy': best_candidate,
                'Reason': f"💀 弒君換馬 ({best_candidate['Score']:.2f} > {worst_holding['Score']:.2f} * 1.5)"
            }
            if len(keeps) >= MAX_TOTAL_POSITIONS:
                swaps.append(swap_info)
                # 從 keeps 移除，避免重複計算
                keeps = [k for k in keeps if k != worst_holding]
                # 加到 sells 列表以便通知
                sells.append({'Symbol': worst_holding['Symbol'], 'Price': worst_holding['Price'], 
                              'Reason': "💀 弒君被換", 'PnL': f"{worst_holding['Profit']*100:.1f}%", 'Sector': worst_holding['Sector']})

    # --- 5. 決定最終買入 ---
    buys = []
    buy_targets = []
    
    # 先處理 Swap 的買入
    for s in swaps:
        buy_targets.append(s['Buy'])
    
    # 處理空位買入
    open_slots = MAX_TOTAL_POSITIONS - len(keeps) - len(swaps) # keeps 已經扣掉被換的了
    
    # 排除已經在 swap 名單的
    swap_symbols = [s['Buy']['Symbol'] for s in swaps]
    available_candidates = [c for c in candidates if c['Symbol'] not in swap_symbols]
    
    if open_slots > 0 and available_candidates:
        # 取前 N 名填補空位
        for i in range(min(open_slots, len(available_candidates))):
            buy_targets.append(available_candidates[i])
            
    # 格式化 Buys 輸出
    for t in buy_targets:
        buys.append(t)

    final_csv_buys = [{'Symbol': b['Symbol'], 'Price': b['Price']} for b in buys]
    
    # 模擬更新 CSV
    # update_portfolio_csv(portfolio, final_csv_buys) 

    return regime, sells, keeps, buys, swaps

def send_line_notify(msg):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 未設定 LINE Token，僅顯示訊息。")
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
    msg = f"🦁 **V212 God Mode**\n{datetime.now().strftime('%Y-%m-%d')}\n"
    msg += "━━━━━━━━━━━━━━\n"
    
    us_icon = "🟢" if regime.get('US_BULL', False) else "❄️"
    crypto_icon = "🟢" if regime.get('CRYPTO_BULL', False) else "❄️"
    tw_icon = "🟢" if regime.get('TW_BULL', False) else "❄️"
    msg += f"環境: 美{us_icon} | 幣{crypto_icon} | 台{tw_icon}\n"
    msg += "━━━━━━━━━━━━━━\n"

    # --- 賣出指令 ---
    if sells:
        msg += "🔴 **【賣出指令】**\n"
        for s in sells:
            msg += f"❌ 賣出 {s['Symbol']}\n"
            msg += f"   原因: {s['Reason']}\n"
            msg += f"   現價: {s['Price']:.2f} (損益: {s['PnL']})\n"
        msg += "--------------------\n"

    # --- 弒君換馬 ---
    if swaps:
        msg += "💀 **【弒君換馬】**\n"
        for s in swaps:
            buy_price = s['Buy']['Price']
            stop_pct = s['Buy']['StopLoss']
            stop_price = buy_price * (1 - stop_pct)
            
            # 取得移動停利參數
            sector_params = SECTOR_PARAMS.get(s['Buy']['Sector'], SECTOR_PARAMS['US_STOCK'])
            trail_init = int(sector_params['trail_init'] * 100)
            
            msg += f"📉 賣出: {s['Sell']['Symbol']} (弱勢)\n"
            msg += f"🚀 買入: {s['Buy']['Symbol']} (強勢)\n"
            msg += f"   👉 硬止損設: {stop_price:.2f} (-{int(stop_pct*100)}%)\n"
            msg += f"   👉 移動停利: 回撤 {trail_init}% 出場\n"
        msg += "--------------------\n"

    # --- 買入指令 ---
    if buys:
        swap_buys = [s['Buy']['Symbol'] for s in swaps]
        pure_buys = [b for b in buys if b['Symbol'] not in swap_buys]
        
        if pure_buys:
            msg += "🟢 **【買入指令】**\n"
            for b in pure_buys:
                buy_price = b['Price']
                stop_pct = b['StopLoss']
                stop_price = buy_price * (1 - stop_pct)
                
                sector_params = SECTOR_PARAMS.get(b['Sector'], SECTOR_PARAMS['US_STOCK'])
                trail_init = int(sector_params['trail_init'] * 100)
                
                msg += f"💰 買入: {b['Symbol']} @ {buy_price:.2f}\n"
                msg += f"   👉 硬止損設: {stop_price:.2f} (-{int(stop_pct*100)}%)\n"
                msg += f"   👉 移動停利: 回撤 {trail_init}% 出場\n"
            msg += "--------------------\n"

    # --- 持倉監控 ---
    if keeps:
        msg += "🛡️ **【持倉監控】**\n"
        for k in keeps:
            pnl = k['Profit'] * 100
            emoji = "😍" if pnl > 20 else "🤢" if pnl < 0 else "😐"
            
            params = SECTOR_PARAMS.get(k['Sector'], {'zombie': 99, 'trail_init': 0.25, 'trail_tight': 0.15})
            
            zombie_left = params['zombie'] - k['Days']
            zombie_msg = ""
            if k['Profit'] <= 0:
                if zombie_left <= 1:
                    zombie_msg = f"⚠️ 瀕死! 剩{zombie_left}天"
                else:
                    zombie_msg = f"🧟 剩{zombie_left}天"
            
            if k['Profit'] > 1.0: # 獲利 > 100%
                trail_action = f"🔥 貪婪模式! 改回撤 {int(params['trail_tight']*100)}% 出場"
            else:
                trail_action = f"🐢 維持回撤 {int(params['trail_init']*100)}% 出場"

            msg += f"{emoji} {k['Symbol']} ({pnl:+.1f}%) {zombie_msg}\n"
            msg += f"   {trail_action}\n"
    else:
        if not buys and not swaps:
            msg += "☕ 目前空手，好好休息\n"

    msg += "━━━━━━━━━━━━━━"
    return msg

if __name__ == "__main__":
    result = analyze_market()
    if result:
        regime, sells, keeps, buys, swaps = result
        message = format_message(regime, sells, keeps, buys, swaps)
        print(message) # Console 預覽
        send_line_notify(message)
    else:
        print("無法執行分析")
