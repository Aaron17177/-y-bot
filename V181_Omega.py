import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import csv
import warnings
from datetime import datetime, timedelta

# 忽略不必要的警告
warnings.filterwarnings("ignore")

# ==========================================
# 1. 參數設定 (V17.44 Strict Live Engine)
# ==========================================
# 核心邏輯：V17.44 Strict Backtest (Bug Fix Version)
# 執行環境：GitHub Actions (Daily)
# ==========================================

LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
PORTFOLIO_FILE = 'portfolio.csv'

USD_TWD_RATE = 32.5
# [V17.44 設定] 最大持倉數改為 3
MAX_TOTAL_POSITIONS = 3

# --- 板塊參數 (V17.44 標準) ---
SECTOR_PARAMS = {
    'CRYPTO_SPOT': {'stop': 0.40, 'zombie': 4,  'trail_1': 0.40, 'trail_2': 0.25, 'trail_3': 0.15},
    'CRYPTO_LEV':  {'stop': 0.50, 'zombie': 3,  'trail_1': 0.50, 'trail_2': 0.30, 'trail_3': 0.15},
    'CRYPTO_MEME': {'stop': 0.55, 'zombie': 3,  'trail_1': 0.55, 'trail_2': 0.30, 'trail_3': 0.15},
    'US_STOCK':    {'stop': 0.25, 'zombie': 8,  'trail_1': 0.25, 'trail_2': 0.15, 'trail_3': 0.10},
    'US_LEV':      {'stop': 0.35, 'zombie': 4,  'trail_1': 0.35, 'trail_2': 0.20, 'trail_3': 0.10},
    'LEV_3X':      {'stop': 0.55, 'zombie': 3,  'trail_1': 0.55, 'trail_2': 0.30, 'trail_3': 0.15},
    'LEV_2X':      {'stop': 0.50, 'zombie': 3,  'trail_1': 0.50, 'trail_2': 0.25, 'trail_3': 0.15},
    'TW_STOCK':    {'stop': 0.25, 'zombie': 8,  'trail_1': 0.25, 'trail_2': 0.15, 'trail_3': 0.10},
    'US_GROWTH':   {'stop': 0.40, 'zombie': 7,  'trail_1': 0.40, 'trail_2': 0.20, 'trail_3': 0.15},
    'TW_LEV_ETF':  {'stop': 0.30, 'zombie': 5,  'trail_1': 0.30, 'trail_2': 0.20, 'trail_3': 0.10},
    'CN_LEV':      {'stop': 0.45, 'zombie': 4,  'trail_1': 0.45, 'trail_2': 0.30, 'trail_3': 0.15},
    'HEDGE_LEV':   {'stop': 0.25, 'zombie': 2,  'trail_1': 0.25, 'trail_2': 0.10, 'trail_3': 0.05},
    'SAFE_HAVEN':  {'stop': 0.20, 'zombie': 10, 'trail_1': 0.20, 'trail_2': 0.10, 'trail_3': 0.05}
}

# ==========================================
# 2. 戰略資產池 (V17.44 Asset Universe)
# ==========================================
ASSET_MAP = {
    # Crypto-related equities / levered crypto ETFs (Includes COIN, COIG)
    'MARA': 'CRYPTO_LEV', 'MSTR': 'CRYPTO_LEV', 'MSTX': 'CRYPTO_LEV',
    'MSTU': 'CRYPTO_LEV', 'CONL': 'CRYPTO_LEV', 'BITX': 'CRYPTO_LEV',
    'ETHU': 'CRYPTO_MEME', 'WGMI': 'CRYPTO_LEV', 'COIN': 'CRYPTO_LEV', 'COIG': 'CRYPTO_LEV',

    # Crypto spot
    'BTC-USD': 'CRYPTO_SPOT', 'ETH-USD': 'CRYPTO_SPOT', 'ADA-USD': 'CRYPTO_SPOT',
    'SOL-USD': 'CRYPTO_SPOT', 'AVAX-USD': 'CRYPTO_SPOT', 'NEAR-USD': 'CRYPTO_SPOT',
    'KAS-USD': 'CRYPTO_SPOT', 'RENDER-USD': 'CRYPTO_SPOT', 'HBAR-USD': 'CRYPTO_SPOT',
    'OP-USD': 'CRYPTO_SPOT',

    # Crypto meme
    'DOGE-USD': 'CRYPTO_MEME', 'SHIB-USD': 'CRYPTO_MEME', 'BONK-USD': 'CRYPTO_MEME',
    'PEPE24478-USD': 'CRYPTO_MEME', 'WIF-USD': 'CRYPTO_MEME', 'FLOKI-USD': 'CRYPTO_MEME',

    'SUI20947-USD': 'CRYPTO_SPOT', 'TAO22974-USD': 'CRYPTO_MEME', 'ENA-USD': 'CRYPTO_MEME',

    # US leverage (2x/3x)
    'GGLL': 'LEV_2X', 'FNGU': 'LEV_3X', 'LABU': 'LEV_3X',
    'NVDL': 'LEV_2X', 'TSLL': 'LEV_2X', 'ASTX': 'LEV_2X',
    'HOOX': 'LEV_2X', 'IONX': 'LEV_2X', 'OKLL': 'LEV_2X', 'RKLX': 'LEV_2X',
    'PLTU': 'LEV_2X', 'DPST': 'LEV_3X',

    # US growth
    'LUNR': 'US_GROWTH', 'QUBT': 'US_GROWTH', 'NNE': 'US_GROWTH',
    'PLTR': 'US_GROWTH', 'SMCI': 'US_GROWTH', 'CRWD': 'US_GROWTH', 'PANW': 'US_GROWTH',
    'APP': 'US_GROWTH', 'SHOP': 'US_GROWTH',
    'IONQ': 'US_GROWTH', 'RGTI': 'US_GROWTH', 'RKLB': 'US_GROWTH', 'VRT': 'US_GROWTH',
    'VST': 'US_GROWTH', 'ASTS': 'US_GROWTH', 'OKLO': 'US_GROWTH', 'VKTX': 'US_GROWTH',
    'HOOD': 'US_GROWTH', 'SERV': 'US_GROWTH',

    # TW stocks
    '2317.TW': 'TW_STOCK', '2454.TW': 'TW_STOCK', '2603.TW': 'TW_STOCK', '2609.TW': 'TW_STOCK', '8996.TW': 'TW_STOCK',
    '6442.TW': 'TW_STOCK', '6515.TW': 'TW_STOCK', '8299.TWO': 'TW_STOCK', '3529.TWO': 'TW_STOCK', '3081.TWO': 'TW_STOCK', '6739.TWO': 'TW_STOCK',
    '2359.TW': 'TW_STOCK', '3583.TW': 'TW_STOCK', '8054.TWO': 'TW_STOCK', '3661.TW': 'TW_STOCK', '3443.TW': 'TW_STOCK', '3035.TW': 'TW_STOCK',
    '6531.TW': 'TW_STOCK', '3324.TWO': 'TW_STOCK', '2365.TW': 'TW_STOCK',
}

TIER_1_ASSETS = [
    'RGTI', 'QUBT', 'ASTS', 'IONQ', 'LUNR', 'RKLB', 'PLTR', 'VST', 'RGTX', 'ASTX',
    'HOOX', 'IONX', 'OKLL', 'RKLX', 'PLTU',
    'ETHU', 'CONL', 'MSTR', 'MSTU', 'DOGE-USD',
    '8299.TWO', '6442.TW', '2359.TW', '3583.TW',
]

# 監控清單
WATCHLIST = list(ASSET_MAP.keys())
BENCHMARKS = ['SPY', 'QQQ', 'BTC-USD', 'ETH-USD', '^TWII', '^HSI', '^N225']

# ==========================================
# 3. 輔助函式
# ==========================================
def normalize_symbol(raw_symbol):
    raw_symbol = str(raw_symbol).strip().upper()
    fix_map = {'6683.TW': '6683.TWO', '6739.TW': '6739.TWO'}
    if raw_symbol in fix_map: return fix_map[raw_symbol]
    
    # 兼容舊的 CSV 格式代碼
    mapping = {
        'PEPE': 'PEPE24478-USD', 'SHIB': 'SHIB-USD', 'DOGE': 'DOGE-USD',
        'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'RNDR': 'RENDER-USD'
    }
    if raw_symbol in mapping: return mapping[raw_symbol]

    if raw_symbol.isdigit():
        for t in WATCHLIST:
            if ('.TW' in t or '.TWO' in t) and t.startswith(raw_symbol + '.'):
                return t
        return f"{raw_symbol}.TW"
    return raw_symbol

def is_crypto_symbol(sym: str) -> bool:
    return sym.endswith("-USD")

def is_tw_symbol(sym: str) -> bool:
    return (".TW" in sym) or (".TWO" in sym)

def get_sector(symbol):
    return ASSET_MAP.get(symbol, 'US_STOCK')

def get_regime_index(symbol, sector):
    if 'CRYPTO' in sector: return 'BTC-USD'
    if 'CN_' in sector or symbol in ['YINN', 'CWEB']: return '^HSI'
    if 'JP_' in sector: return '^N225'
    if 'TW_' in sector or is_tw_symbol(symbol): return '^TWII'
    return 'QQQ'

def load_portfolio():
    holdings = {}
    if not os.path.exists(PORTFOLIO_FILE): return holdings
    try:
        with open(PORTFOLIO_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None) 
            for row in reader:
                if not row or len(row) < 2: continue
                symbol = normalize_symbol(row[0])
                try:
                    entry_price = float(row[1])
                    entry_date = row[2] if len(row) > 2 else datetime.now().strftime('%Y-%m-%d')
                    holdings[symbol] = {'entry_price': entry_price, 'entry_date': entry_date}
                except ValueError: continue
        return holdings
    except Exception: return {}

def update_portfolio_csv(holdings, new_buys=None):
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
        print("✅ Portfolio CSV 已更新")
    except Exception as e:
        print(f"❌ 更新 CSV 失敗: {e}")

# [V17.44 Strict Data Validation]
def validate_data_point(symbol, df_row):
    """嚴格檢查單日數據品質，對應 ohlc_sanity_mask"""
    try:
        o = df_row['Open']
        h = df_row['High']
        l = df_row['Low']
        c = df_row['Close']
        v = df_row['Volume']
        
        if pd.isna(o) or pd.isna(h) or pd.isna(l) or pd.isna(c): return False
        if o <= 0 or h <= 0 or l <= 0 or c <= 0: return False
        if h < l: return False # 數據錯誤
        
        # 檢查 High/Low 比例是否過於離譜 (數據錯誤)
        if l > 0 and (h / l > 8.0): return False 

        if not is_crypto_symbol(symbol) and (pd.isna(v) or v <= 0):
            return False # 股票必須有成交量
            
        return True
    except:
        return False

# ==========================================
# 4. 分析引擎 (Strict Live Engine)
# ==========================================
def analyze_market():
    portfolio = load_portfolio()
    all_tickers = list(set(BENCHMARKS + list(portfolio.keys()) + WATCHLIST))

    print(f"📥 下載 {len(all_tickers)} 檔數據 (V17.44 Strict Mode)...")
    try:
        # [V17.44 關鍵] auto_adjust=False，手動處理匯率
        data = yf.download(all_tickers, period="300d", progress=False, auto_adjust=False, actions=False)
        if data.empty: return None
        
        # 處理 MultiIndex
        if len(all_tickers) == 1:
            # 只有一檔時，yf 返回的是沒有第二層 column 的 df，需手動構造
            closes = data['Close'].to_frame()
            opens = data['Open'].to_frame()
            lows = data['Low'].to_frame()
            highs = data['High'].to_frame()
            volumes = data['Volume'].to_frame()
            closes.columns = [all_tickers[0]]
            opens.columns = [all_tickers[0]]
            lows.columns = [all_tickers[0]]
            highs.columns = [all_tickers[0]]
            volumes.columns = [all_tickers[0]]
        else:
            closes = data['Close'].ffill()
            opens = data['Open'].ffill()
            lows = data['Low'].ffill()
            highs = data['High'].ffill()
            volumes = data['Volume'].ffill()

        # [V17.44 關鍵] 手動匯率轉換
        for t in all_tickers:
            if is_tw_symbol(t):
                if t in closes.columns: closes[t] /= USD_TWD_RATE
                if t in opens.columns: opens[t] /= USD_TWD_RATE
                if t in lows.columns: lows[t] /= USD_TWD_RATE
                if t in highs.columns: highs[t] /= USD_TWD_RATE

    except Exception as e:
        print(f"❌ 數據下載失敗: {e}"); return None

    # --- 1. 準備數據與指標 ---
    sells = []; keeps = []; buys = []; swaps = []
    
    # 取得每檔標的「最新一筆有效數據」的索引
    latest_data = {} 
    
    for t in all_tickers:
        if t not in closes.columns: continue
        # 建立臨時 DataFrame 檢查最後一筆數據
        last_idx = closes.index[-1]
        row = {
            'Open': opens.loc[last_idx, t],
            'High': highs.loc[last_idx, t],
            'Low': lows.loc[last_idx, t],
            'Close': closes.loc[last_idx, t],
            'Volume': volumes.loc[last_idx, t] if t in volumes.columns else 0
        }
        
        # [V17.44] 嚴格數據檢查
        if validate_data_point(t, row):
            latest_data[t] = {
                'Close': row['Close'],
                'Open': row['Open'], # 用於模擬計算
                'Low': row['Low'],   # 用於止損檢查
                'Price': row['Close']
            }
        else:
            print(f"⚠️ {t} 今日數據異常或無交易，跳過分析")

    # 基準指數判斷 (Regime Check Logic)
    def get_benchmark_status(idx_symbol, ma_window):
        if idx_symbol not in closes.columns: return True # 若無數據預設為 True 避免卡死，但實戰應有數據
        series = closes[idx_symbol].dropna()
        if len(series) < ma_window: return True
        p = series.iloc[-1]
        ma = series.rolling(ma_window).mean().iloc[-1]
        return p > ma

    regime_status = {
        'QQQ': get_benchmark_status('QQQ', 200),
        'SPY': get_benchmark_status('SPY', 200),
        'BTC-USD': get_benchmark_status('BTC-USD', 100),
        'ETH-USD': get_benchmark_status('ETH-USD', 100),
        '^TWII': get_benchmark_status('^TWII', 60),
        '^HSI': get_benchmark_status('^HSI', 60),
        '^N225': get_benchmark_status('^N225', 60)
    }

    # --- 2. 持倉健檢 (Phase 0 & 1) ---
    for symbol, data in portfolio.items():
        if symbol not in latest_data: continue # 無今日數據，跳過檢查 (保持持倉)
        
        curr_price = latest_data[symbol]['Close']
        low_price = latest_data[symbol]['Low'] # 用於模擬盤中觸發止損
        entry_price = data['entry_price']
        entry_date = datetime.strptime(data['entry_date'], '%Y-%m-%d')
        days_held = (datetime.now() - entry_date).days

        sector = get_sector(symbol)
        params = SECTOR_PARAMS.get(sector, SECTOR_PARAMS['US_STOCK'])

        profit_pct = (curr_price - entry_price) / entry_price
        
        # 取得歷史高點 (模擬 Trailing High)
        # 實戰中只能用 Recent High 來近似，取持有期間內的最高 Close
        hist_series = closes[symbol].dropna()
        # 簡單起見，取最近 60 天最高價當作 Trailing High 的近似
        # V17.44 回測中是紀錄真實 Trailing High，實戰用近期高點代替
        recent_high = hist_series.tail(min(days_held + 1, 60)).max() 
        trailing_high = max(recent_high, curr_price)

        reason = ""
        
        # A. 盤中硬止損 (Intraday Stop) - V17.44 Phase 0
        hard_stop_price = entry_price * (1 - params['stop'])
        if low_price <= hard_stop_price:
             reason = f"🔴 觸及止損 (Low:{low_price:.2f} <= Stop:{hard_stop_price:.2f})"

        # B. 殭屍清除 (Zombie) - V17.44 Phase 1
        elif days_held > params['zombie'] and curr_price <= entry_price:
            reason = f"💤 殭屍清除 (> {params['zombie']}天且未獲利)"

        # C. 分區冬眠 (Regime) - V17.44 Phase 1
        elif sector not in ['SAFE_HAVEN', 'HEDGE_LEV']:
            regime_idx = get_regime_index(symbol, sector)
            # 檢查 Check Regime Pass 邏輯
            pass_regime = True
            msg = ""
            
            # 1. Primary Index Check
            if regime_idx in regime_status and not regime_status[regime_idx]:
                pass_regime = False
                msg = f"{regime_idx} < MA"
            
            # 2. Dual Crypto Check (For Altcoins)
            if sector in ['CRYPTO_SPOT', 'CRYPTO_MEME'] and symbol not in ['BTC-USD', 'ETH-USD']:
                if not regime_status['ETH-USD']:
                    pass_regime = False
                    msg = "ETH < MA"

            if not pass_regime:
                reason = f"❄️ 分區冬眠 ({msg})"

        # D. 移動停利 (Trailing Stop) - V17.44 Phase 1 (Signal Gen)
        if not reason:
            if profit_pct > 1.0: limit = 1 - params['trail_3']
            elif profit_pct > 0.3: limit = 1 - params['trail_2']
            else: limit = 1 - params['trail_1']
            
            trail_stop_price = trailing_high * limit
            if curr_price < trail_stop_price:
                reason = f"🛡️ 階梯停利 (回撤 > {(1-limit)*100:.0f}%)"
            
            # MA50 技術出場
            ma50 = hist_series.rolling(50).mean().iloc[-1]
            if curr_price < ma50:
                reason = "❌ 跌破季線 (MA50)"

        # 計算得分 (用於換馬)
        mom_20 = hist_series.pct_change(20).iloc[-1]
        vol_20 = hist_series.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)
        score = 0
        if not pd.isna(mom_20) and mom_20 > 0:
            mult = 1.0 + vol_20
            if symbol in TIER_1_ASSETS: mult *= 1.2
            # ADR Check (簡單判斷)
            if 'ADR' in sector: mult *= 1.1
            score = mom_20 * mult
            if 'TW' in sector: score *= 0.9

        if reason:
            sells.append({'Symbol': symbol, 'Price': curr_price, 'Reason': reason, 'PnL': f"{profit_pct*100:.1f}%", 'Sector': sector})
        else:
            limit_display = params['trail_1'] # Default display
            if profit_pct > 0.3: limit_display = params['trail_2']
            if profit_pct > 1.0: limit_display = params['trail_3']
            keeps.append({'Symbol': symbol, 'Price': curr_price, 'Entry': entry_price, 'Score': score, 'Profit': profit_pct, 'Days': days_held, 'Sector': sector, 'TrailLimit': limit_display})

    # --- 3. 選股掃描 (Candidates - V17.44 Phase 2) ---
    candidates = []
    
    # Exclude logic handled by EXCLUDED_SECTORS=[] (already empty in V17.44)
    
    for t in WATCHLIST:
        if t in portfolio or t not in latest_data: continue # 已持倉或無數據
        
        series = closes[t].dropna()
        if len(series) < 65: continue # 確保有足夠數據算 MA60

        p = series.iloc[-1]
        m20 = series.rolling(20).mean().iloc[-1]
        m50 = series.rolling(50).mean().iloc[-1]
        m60 = series.rolling(60).mean().iloc[-1]

        # [V17.44] 嚴格趨勢濾網
        if not (p > m20 and m20 > m50 and p > m60): continue

        sector = get_sector(t)
        
        # [V17.44] Regime Check
        regime_idx = get_regime_index(t, sector)
        
        # Index Strength Check (Local Strength)
        idx_ret = 0
        spy_ret = 0
        if regime_idx in closes.columns:
            idx_series = closes[regime_idx].dropna()
            if len(idx_series) > 20: idx_ret = idx_series.pct_change(20).iloc[-1]
        if 'SPY' in closes.columns:
            spy_series = closes['SPY'].dropna()
            if len(spy_series) > 20: spy_ret = spy_series.pct_change(20).iloc[-1]
            
        # Crypto & US Tech don't need to beat SPY, others do
        if regime_idx not in ['QQQ', 'BTC-USD', 'SPY']:
            if idx_ret < spy_ret: continue

        # Benchmark MA Check
        pass_regime = True
        if regime_idx in regime_status and not regime_status[regime_idx]: pass_regime = False
        if sector in ['CRYPTO_SPOT', 'CRYPTO_MEME'] and t not in ['BTC-USD', 'ETH-USD']:
             if not regime_status['ETH-USD']: pass_regime = False
        
        if not pass_regime: continue

        mom_20 = series.pct_change(20).iloc[-1]
        
        # [V17.44] Hurdles
        if 'TW' in sector and mom_20 < 0.08: continue 
        if 'LEV_3X' in sector and mom_20 < 0.05: continue
        if 'LEV_2X' in sector and mom_20 < 0.02: continue
        if pd.isna(mom_20) or mom_20 <= 0: continue

        vol_20 = series.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)
        if pd.isna(vol_20): vol_20 = 0

        mult = 1.0 + vol_20
        if t in TIER_1_ASSETS: mult *= 1.2
        
        final_score = mom_20 * mult
        if 'TW' in sector: final_score *= 0.9

        candidates.append({'Symbol': t, 'Price': p, 'Score': final_score, 'Sector': sector})

    candidates.sort(key=lambda x: x['Score'], reverse=True)

    # --- 4. 弒君換馬 (Killer Swap - V17.44 Phase 5) ---
    while keeps and candidates:
        worst_holding = min(keeps, key=lambda x: x['Score'])
        
        existing_targets = [s['Buy']['Symbol'] for s in swaps]
        available_candidates = [c for c in candidates if c['Symbol'] not in existing_targets]
        
        if not available_candidates: break
            
        best_candidate = available_candidates[0]

        vol_hold = closes[worst_holding['Symbol']].pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)
        if pd.isna(vol_hold): vol_hold = 0

        # V17.44 Swap Threshold logic
        swap_thresh = 1.4 + (vol_hold * 0.1)
        swap_thresh = min(swap_thresh, 2.0)

        if best_candidate['Score'] > worst_holding['Score'] * swap_thresh:
            swaps.append({
                'Sell': worst_holding,
                'Buy': best_candidate,
                'Reason': f"Score {best_candidate['Score']:.2f} > {worst_holding['Score']:.2f} * {swap_thresh:.1f}"
            })
            keeps = [k for k in keeps if k != worst_holding]
            sells.append({'Symbol': worst_holding['Symbol'], 'Price': worst_holding['Price'], 'Reason': "💀 弒君換馬", 'PnL': f"{worst_holding['Profit']*100:.1f}%", 'Sector': worst_holding['Sector']})
        else:
            break

    # --- 5. 填補空位 (Fill Slots - V17.44 Phase 6) ---
    buy_targets = [s['Buy'] for s in swaps]
    
    # 這裡的邏輯是：預期持倉數 = (目前持倉 - 待賣出) + 待買入
    # 所以空位 = MAX - (len(keeps) + len(swaps))
    open_slots = MAX_TOTAL_POSITIONS - len(keeps) - len(swaps) 
    
    existing_buys = [b['Symbol'] for b in buy_targets]
    pool_idx = 0
    while open_slots > 0 and pool_idx < len(candidates):
        cand = candidates[pool_idx]
        if cand['Symbol'] not in existing_buys:
            buy_targets.append(cand)
            open_slots -= 1
        pool_idx += 1

    return regime_status, sells, keeps, buy_targets, swaps

def send_line_notify(msg):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 未設定 LINE Token"); print(msg); return

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'}
    data = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg}]}
    try:
        requests.post(url, headers=headers, json=data)
    except Exception as e:
        print(f"發送 LINE 失敗: {e}")

def format_message(regime, sells, keeps, buys, swaps):
    msg = f"🦁 **V17.44 Apex Sniper (Strict Live)**\n{datetime.now().strftime('%Y-%m-%d')}\n━━━━━━━━━━━━━━\n"
    msg += f"🌍 市場環境 (Regime Check)\n"
    
    # 簡化顯示
    key_indices = {'SPY': '美股', 'BTC-USD': '幣圈', '^TWII': '台股'}
    for k, name in key_indices.items():
        status = "🟢" if regime.get(k, False) else "❄️"
        msg += f"{name}: {status} "
    msg += "\n━━━━━━━━━━━━━━\n"

    if sells:
        msg += "🔴 **【賣出指令 (Pending Sell)】**\n"
        for s in sells:
            msg += f"❌ 賣出: {s['Symbol']}\n"
            msg += f"   原因: {s['Reason']}\n"
            msg += f"   損益: {s['PnL']}\n"
        msg += "--------------------\n"

    if swaps:
        msg += "💀 **【弒君換馬 (Multikill)】**\n"
        for s in swaps:
            msg += f"📉 賣出: {s['Sell']['Symbol']} (弱)\n"
            msg += f"🚀 買入: {s['Buy']['Symbol']} (強)\n"
            msg += f"   原因: {s['Reason']}\n"
        msg += "--------------------\n"

    if buys:
        msg += "🟢 **【買入指令 (Pending Buy)】**\n"
        for b in buys:
            params = SECTOR_PARAMS.get(b['Sector'], SECTOR_PARAMS['US_STOCK'])
            stop_pct = params['stop']
            trail_pct = params['trail_1']
            stop_price = b['Price'] * (1 - stop_pct)

            msg += f"💰 買入: {b['Symbol']}\n"
            msg += f"   現價: {b['Price']:.2f}\n"
            msg += f"   分數: {b['Score']:.2f}\n"
            msg += f"   👮 設定: 停損 -{int(stop_pct*100)}%\n"
            msg += f"   (🛑 災難底線: {stop_price:.2f})\n"
        msg += "--------------------\n"

    if keeps:
        msg += "🛡️ **【持倉監控】**\n"
        for k in keeps:
            pnl = k['Profit'] * 100
            emoji = "😍" if pnl > 20 else "😐" if pnl > 0 else "🤢"
            params = SECTOR_PARAMS.get(k['Sector'], SECTOR_PARAMS['US_STOCK'])
            limit_pct = int(k['TrailLimit'] * 100)
            msg += f"{emoji} {k['Symbol']} ({pnl:+.1f}%)\n"
            msg += f"   🔥 動能: {k['Score']:.2f}\n"
            msg += f"   👮 移停: {limit_pct}%\n"
    else:
        if not buys and not swaps:
            msg += "☕ 目前空手，好好休息\n"

    msg += "━━━━━━━━━━━━━━"
    return msg

if __name__ == "__main__":
    res = analyze_market()
    if res:
        regime, sells, keeps, buys, swaps = res
        current_holdings = load_portfolio()

        # 1. 執行賣出 (包含 Stop/Zombie/Swap Sells)
        # 注意：實戰中這裡只是更新 CSV 狀態，實際下單需人工或 Broker API
        for s in sells:
            if s['Symbol'] in current_holdings:
                del current_holdings[s['Symbol']]

        # 2. 執行買入 (包含 Swap Buys/New Buys)
        final_csv_buys = [{'Symbol': b['Symbol'], 'Price': b['Price']} for b in buys]
        
        # 更新 CSV (模擬成交)
        # 實戰建議：可以在這裡加一個開關，決定是否自動更新 CSV，或是等確認成交後手動更新
        update_portfolio_csv(current_holdings, final_csv_buys)

        # 發送通知
        msg = format_message(regime, sells, keeps, buys, swaps)
        print(msg)
        send_line_notify(msg)
    else:
        print("❌ 分析失敗")
