# =========================================================
# V17.50 VANGUARD LIVE ENGINE (純淨先鋒實務佈署版)
# 修正內容: 導入全域狀態消毒機 (Global Sanitizer)，徹底根除休市繞過清創的 Bug (CR_FIX_08)
# 修正內容: 增設板塊多空雷達 (Bull/Bear Regime Radar) (CR_FIX_07)
# 修正內容: 解決 YF API 空值導致「永久吞單」的致命漏洞 (CR_FIX_05)
# =========================================================

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
import json
import os
import argparse
import requests
from datetime import datetime

warnings.filterwarnings("ignore")

# =========================
# 1) Configuration & Secrets
# =========================
DATA_DOWNLOAD_DAYS = 250
SLIPPAGE_RATE = 0.002
RATES = {
    'CRYPTO_COMM': 0.001, 'US_COMM': 0.001, 'TW_COMM': 0.001425 * 0.22,
    'TW_TAX_STOCK': 0.003, 'TW_TAX_ETF': 0.001
}

GAP_UP_LIMIT = 0.10
PANIC_VIX_THRESHOLD = 40.0
MIN_HOLD_DAYS = 3
USD_TWD_RATE = 32.5
INITIAL_CAPITAL_USD = 100000.0 / 32.5
MAX_TOTAL_POSITIONS = 3
BASE_POSITION_SIZE = 1.0 / MAX_TOTAL_POSITIONS

STATE_FILE = 'state.json'
LINE_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')

# =========================
# 2) Strategy Parameters
# =========================
SECTOR_PARAMS = {
    'CRYPTO_SPOT': {'stop': 0.40, 'zombie': 10, 'trail': {2.0: 0.25, 1.0: 0.30, 0.5: 0.35, 0.0: 0.40}},
    'CRYPTO_LEV':  {'stop': 0.50, 'zombie': 8,  'trail': {3.0: 0.30, 1.0: 0.40, 0.5: 0.45, 0.0: 0.50}},
    'CRYPTO_MEME': {'stop': 0.60, 'zombie': 5,  'trail': {5.0: 0.30, 2.0: 0.40, 1.0: 0.50, 0.0: 0.60}},
    'US_STOCK':    {'stop': 0.25, 'zombie': 10, 'trail': {1.0: 0.15, 0.5: 0.20, 0.2: 0.20, 0.0: 0.25}},
    'US_LEV':      {'stop': 0.35, 'zombie': 8,  'trail': {1.0: 0.20, 0.5: 0.25, 0.2: 0.30, 0.0: 0.35}},
    'LEV_3X':      {'stop': 0.45, 'zombie': 5,  'trail': {2.0: 0.25, 1.0: 0.30, 0.5: 0.35, 0.0: 0.45}},
    'TW_STOCK':    {'stop': 0.25, 'zombie': 12, 'trail': {1.0: 0.15, 0.5: 0.20, 0.2: 0.20, 0.0: 0.25}},
    'US_GROWTH':   {'stop': 0.40, 'zombie': 10, 'trail': {1.0: 0.25, 0.5: 0.30, 0.2: 0.35, 0.0: 0.40}},
    'DEFAULT':     {'stop': 0.30, 'zombie': 10, 'trail': {1.0: 0.20, 0.5: 0.25, 0.0: 0.30}}
}

ASSET_MAP = {
    'BTC-USD': 'CRYPTO_SPOT', 'ADA-USD': 'CRYPTO_SPOT',
    'SOL-USD': 'CRYPTO_SPOT', 'AVAX-USD': 'CRYPTO_SPOT', 'NEAR-USD': 'CRYPTO_SPOT',
    'KAS-USD': 'CRYPTO_SPOT', 'RENDER-USD': 'CRYPTO_SPOT', 'HBAR-USD': 'CRYPTO_SPOT',
    'DOGE-USD': 'CRYPTO_MEME', 'SHIB-USD': 'CRYPTO_MEME', 'BONK-USD': 'CRYPTO_MEME',
    'PEPE24478-USD': 'CRYPTO_MEME', 'WIF-USD': 'CRYPTO_MEME', 'FLOKI-USD': 'CRYPTO_MEME',
    'SUI20947-USD': 'CRYPTO_SPOT', 'TAO22974-USD': 'CRYPTO_MEME', 'ENA-USD': 'CRYPTO_MEME',
    'GGLL': 'LEV_2X', 'FNGU': 'LEV_3X', 'NVDL': 'LEV_2X', 'ASTX': 'LEV_2X',
    'HOOX': 'LEV_2X', 'IONX': 'LEV_2X', 'OKLL': 'LEV_2X', 'RKLX': 'LEV_2X',
    'LUNR': 'US_GROWTH', 'QUBT': 'US_GROWTH', 'PLTR': 'US_GROWTH', 'SMCI': 'US_GROWTH', 
    'CRWD': 'US_GROWTH', 'PANW': 'US_GROWTH', 'APP': 'US_GROWTH', 'SHOP': 'US_GROWTH',
    'IONQ': 'US_GROWTH', 'RGTI': 'US_GROWTH', 'RKLB': 'US_GROWTH', 'VRT': 'US_GROWTH',
    'VST': 'US_GROWTH', 'ASTS': 'US_GROWTH', 'OKLO': 'US_GROWTH', 'VKTX': 'US_GROWTH',
    'HOOD': 'US_GROWTH', 'SERV': 'US_GROWTH', 'GLD': 'US_STOCK',
    '2317.TW': 'TW_STOCK', '2603.TW': 'TW_STOCK', '2609.TW': 'TW_STOCK', '8996.TW': 'TW_STOCK',
    '6442.TW': 'TW_STOCK', '8299.TWO': 'TW_STOCK', '3529.TWO': 'TW_STOCK', '6739.TWO': 'TW_STOCK',
    '2359.TW': 'TW_STOCK', '8054.TWO': 'TW_STOCK', '3035.TW': 'TW_STOCK',
    '6531.TW': 'TW_STOCK', '3324.TWO': 'TW_STOCK',
}

TIER_1_ASSETS = [
    'RGTI', 'QUBT', 'ASTS', 'IONQ', 'LUNR', 'RKLB', 'PLTR', 'VST', 'RGTX', 'ASTX',
    'HOOX', 'IONX', 'OKLL', 'RKLX', 'PLTU',
    'DOGE-USD', 'BONK-USD', 'WIF-USD', 'KAS-USD', 'RENDER-USD',
    '8299.TWO', '6442.TW', '2359.TW'
]

ALL_TICKERS = list(set(list(ASSET_MAP.keys()) + ['SPY', 'QQQ', 'BTC-USD', '^TWII', '^HSI', '^VIX', 'TWD=X']))

# =========================
# 3) Live State & Position Engine
# =========================
class Position:
    def __init__(self, symbol, entry_date, entry_price, units, sector, max_price=None, current_price=None):
        self.symbol = symbol
        self.entry_date = entry_date if isinstance(entry_date, pd.Timestamp) else pd.Timestamp(entry_date)
        self.entry_price = float(entry_price)
        self.units = float(units)
        self.sector = sector
        self.max_price = float(max_price) if max_price else float(entry_price)
        self.current_price = float(current_price) if current_price else float(entry_price)

    @classmethod
    def from_dict(cls, data):
        return cls(data['symbol'], data['entry_date'], data['entry_price'], 
                   data['units'], data['sector'], data.get('max_price'), data.get('current_price'))

    def to_dict(self):
        return {
            'symbol': self.symbol, 'entry_date': self.entry_date.strftime('%Y-%m-%d'),
            'entry_price': self.entry_price, 'units': self.units,
            'sector': self.sector, 'max_price': self.max_price, 'current_price': self.current_price
        }

    @property
    def market_value(self): return self.units * self.current_price

    def get_params(self): return SECTOR_PARAMS.get(self.sector, SECTOR_PARAMS['DEFAULT'])

    def check_intraday_exit(self, open_p, high_p, low_p, curr_vix=20.0):
        params = self.get_params()
        stop_threshold = self.entry_price * (1 - params['stop'])
        effective_peak = max(self.max_price, open_p)
        profit_ratio = (effective_peak - self.entry_price) / self.entry_price
        trail_pct = params['stop']

        for threshold, pct in sorted(params['trail'].items(), key=lambda x: x[0], reverse=True):
            if profit_ratio >= threshold:
                trail_pct = pct; break

        if curr_vix > 30.0: trail_pct *= 0.5
        trail_price = effective_peak * (1 - trail_pct)
        final_exit_price = max(trail_price, stop_threshold)

        if open_p < final_exit_price:
            return True, open_p, "GAP_STOP" if open_p < stop_threshold else "GAP_TRAIL"
        if low_p <= final_exit_price:
            return True, final_exit_price, "HARD_STOP" if final_exit_price == stop_threshold else f"TRAIL_EXIT"
        
        if high_p > self.max_price: self.max_price = high_p
        return False, 0.0, ""

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {
        "cash": INITIAL_CAPITAL_USD, "positions": {}, "orders_queue": [], "cooldown_dict": {},
        "last_processed_date": (datetime.utcnow() - pd.Timedelta(days=5)).strftime('%Y-%m-%d')
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

def get_data():
    start_str = (datetime.utcnow() - pd.Timedelta(days=DATA_DOWNLOAD_DAYS)).strftime('%Y-%m-%d')
    data = yf.download(ALL_TICKERS, start=start_str, progress=False, auto_adjust=True)
    if isinstance(data.columns, pd.MultiIndex):
        raw_close, close = data['Close'], data['Close'].ffill()
        open_, high, low = data['Open'].ffill(), data['High'].ffill(), data['Low'].ffill()
    else:
        raw_close, close = data, data.ffill()
        open_, high, low = close.copy(), close.copy(), close.copy()
    
    is_trading_day = ~raw_close.isna()
    twd_series = close['TWD=X'].ffill().bfill() if 'TWD=X' in close.columns else pd.Series(USD_TWD_RATE, index=close.index)

    for col in close.columns:
        if '.TW' in col or '.TWO' in col:
            close[col] /= twd_series; open_[col] /= twd_series
            high[col]  /= twd_series; low[col]   /= twd_series

    cols_to_drop = [c for c in close.columns if c == 'TWD=X']
    if cols_to_drop:
        for df in [close, open_, high, low, is_trading_day]: df.drop(columns=cols_to_drop, inplace=True)
    return close, open_, high, low, is_trading_day

def get_sector(sym): return ASSET_MAP.get(sym, 'US_STOCK')

def get_costs(sector, sym, gross_amount, action):
    comm = gross_amount * RATES.get(f"{sector.split('_')[0]}_COMM", RATES['US_COMM'])
    tax = gross_amount * (RATES['TW_TAX_ETF'] if sym.startswith('00') else RATES['TW_TAX_STOCK']) if action == 'SELL' and 'TW' in sector else 0.0
    return comm, tax

def check_regime(date, sym, close_df, benchmarks_ma):
    sector = get_sector(sym)
    bench = 'BTC-USD' if 'CRYPTO' in sector else '^TWII' if 'TW_' in sector else '^HSI' if 'CN_' in sector else 'QQQ'
    if bench not in close_df.columns: return True
    price, ma100, ma50 = close_df.loc[date, bench], benchmarks_ma[bench].loc[date], benchmarks_ma.get(f"{bench}_50")
    if pd.isna(price) or pd.isna(ma100): return True
    if ma50 is not None and not pd.isna(ma50.loc[date]): return (price > ma100) and (ma50.loc[date] > ma100)
    return price > ma100

# [FIX_08] 絕對淨化機制：清洗舊有髒資料，保證算術完美
def sanitize_queue(positions, orders_queue):
    unique_orders = []
    seen = set()
    for o in orders_queue:
        key = (o['type'], o['symbol'])
        if key not in seen:
            unique_orders.append(o)
            seen.add(key)
    queue = unique_orders
    
    current_holding = len(positions)
    pending_sells = len([o for o in queue if o['type'] == 'SELL'])
    buys = [o for o in queue if o['type'] == 'BUY']
    
    expected_total = current_holding - pending_sells + len(buys)
    if expected_total > MAX_TOTAL_POSITIONS:
        excess = expected_total - MAX_TOTAL_POSITIONS
        buys_to_remove = buys[-excess:]
        queue = [o for o in queue if o not in buys_to_remove]
        
    return queue

def run_live(dry_run=False):
    print("🚀 Vanguard Live Engine 啟動...")
    close, open_, high, low, is_trading_day = get_data()
    
    today_utc = datetime.utcnow().date()
    completed_dates = [d for d in close.index if d.date() < today_utc]
    if not completed_dates: return
    
    state = load_state()
    cash = state['cash']
    positions = {sym: Position.from_dict(d) for sym, d in state['positions'].items()}
    orders_queue = state['orders_queue']
    cooldown_dict = {sym: pd.Timestamp(d) for sym, d in state['cooldown_dict'].items()}
    
    # 【最關鍵防線】：一讀檔立刻消毒，即使今天休市不運算，也不會印出毒清單
    orders_queue = sanitize_queue(positions, orders_queue)

    last_processed = pd.Timestamp(state['last_processed_date'])
    dates_to_process = [d for d in completed_dates if d > last_processed]
    
    ma20, ma50, ma60 = close.rolling(20).mean(), close.rolling(50).mean(), close.rolling(60).mean()
    benchmarks_ma = {b: close[b].rolling(100).mean() for b in ['SPY', 'QQQ', 'BTC-USD', '^TWII'] if b in close.columns}
    for b in list(benchmarks_ma.keys()): benchmarks_ma[f"{b}_50"] = close[b].rolling(50).mean()
        
    mom_20, vol_20 = close.pct_change(20), close.pct_change().rolling(20).std() * np.sqrt(252)
    scores = pd.DataFrame(index=close.index, columns=close.columns)
    for t in ASSET_MAP.keys():
        if t not in close.columns: continue
        trend_ok = (close[t] > ma20[t]) & (ma20[t] > ma50[t]) & (close[t] > ma60[t])
        valid_mom = (mom_20[t] > (0.08 if 'TW' in ASSET_MAP[t] else 0.05 if '3X' in ASSET_MAP[t] else 0.0)).fillna(False)
        mult = (1.0 + vol_20[t].fillna(0)) * (1.2 if t in TIER_1_ASSETS else 1.0)
        scores[t] = np.where(trend_ok & valid_mom, mom_20[t] * mult * (0.9 if 'TW' in ASSET_MAP[t] else 1.0), np.nan)
    vix_series = close['^VIX'] if '^VIX' in close.columns else pd.Series(20, index=close.index)

    intraday_alerts = []

    for date in dates_to_process:
        date_idx = list(close.index).index(date)
        today = close.index[date_idx - 1] if date_idx > 0 else date
        tomorrow = date
        
        sell_orders = [o for o in orders_queue if o['type'] == 'SELL']
        buy_orders  = [o for o in orders_queue if o['type'] == 'BUY']
        pending_orders = []

        for o in sell_orders:
            sym = o['symbol']
            if not is_trading_day.loc[tomorrow, sym] or pd.isna(open_.loc[tomorrow, sym]): 
                pending_orders.append(o)
                continue
            if sym not in positions: continue
            exec_price = open_.loc[tomorrow, sym] * (1 - SLIPPAGE_RATE)
            comm, tax = get_costs(positions[sym].sector, sym, positions[sym].units * exec_price, 'SELL')
            cash += (positions[sym].units * exec_price) - comm - tax
            del positions[sym]

        for o in buy_orders:
            sym, amount = o['symbol'], o['amount_usd']
            if not is_trading_day.loc[tomorrow, sym] or pd.isna(open_.loc[tomorrow, sym]):
                pending_orders.append(o)
                continue
                
            has_pending_sells = any(x['type']=='SELL' for x in pending_orders)
            if cash < amount * 0.90 and has_pending_sells:
                pending_orders.append(o)
                continue
            
            if cash <= 0 or (open_.loc[tomorrow, sym]/close.loc[today, sym]) > (1+GAP_UP_LIMIT): 
                continue
            
            exec_price = open_.loc[tomorrow, sym] * (1 + SLIPPAGE_RATE)
            temp_comm, _ = get_costs(get_sector(sym), sym, 1.0, 'BUY')
            units = min(cash, amount) / (exec_price * (1 + temp_comm))
            if units * exec_price < 100: continue
            
            cost = units * exec_price
            comm, _ = get_costs(get_sector(sym), sym, cost, 'BUY')
            cash -= (cost + comm)
            positions[sym] = Position(sym, tomorrow, exec_price, units, get_sector(sym))

        orders_queue = pending_orders

        cols_to_del = []
        curr_vix_trail = vix_series.loc[today] if not pd.isna(vix_series.loc[today]) else 20.0
        for sym, pos in positions.items():
            if not is_trading_day.loc[tomorrow, sym] or pd.isna(low.loc[tomorrow, sym]): continue
            pos.current_price = close.loc[tomorrow, sym]
            triggered, exec_price, reason = pos.check_intraday_exit(open_.loc[tomorrow, sym], high.loc[tomorrow, sym], low.loc[tomorrow, sym], curr_vix_trail)
            if triggered:
                exec_price *= (1 - SLIPPAGE_RATE)
                comm, tax = get_costs(pos.sector, sym, pos.units * exec_price, 'SELL')
                cash += (pos.units * exec_price) - comm - tax
                if 'CRYPTO' in pos.sector or 'LEV' in pos.sector: cooldown_dict[sym] = tomorrow + pd.Timedelta(days=1)
                else: cooldown_dict[sym] = tomorrow + pd.Timedelta(days=5)
                cols_to_del.append(sym)
                if date == dates_to_process[-1]: intraday_alerts.append(f"⚠️ {sym} 於 {tomorrow.strftime('%m/%d')} 盤中觸發: {reason}")
        for sym in cols_to_del: del positions[sym]

        if cash > 0: cash *= ((1 + 0.04) ** (1/365))
        curr_vix = vix_series.loc[tomorrow] if not pd.isna(vix_series.loc[tomorrow]) else 20.0
        
        holdings_to_sell = []
        for sym, pos in positions.items():
            if not is_trading_day.loc[tomorrow, sym]: continue
            if curr_vix > 45.0: 
                if not any(o['type'] == 'SELL' and o['symbol'] == sym for o in orders_queue):
                    orders_queue.append({'type': 'SELL', 'symbol': sym, 'reason': "VIX>45斷路"})
                holdings_to_sell.append(sym); continue
            if (tomorrow - pos.entry_date).days > pos.get_params()['zombie'] and pos.current_price <= pos.entry_price:
                if not any(o['type'] == 'SELL' and o['symbol'] == sym for o in orders_queue):
                    orders_queue.append({'type': 'SELL', 'symbol': sym, 'reason': "Zombie"})
                holdings_to_sell.append(sym); continue
            if not check_regime(tomorrow, sym, close, benchmarks_ma):
                if not any(o['type'] == 'SELL' and o['symbol'] == sym for o in orders_queue):
                    orders_queue.append({'type': 'SELL', 'symbol': sym, 'reason': "Regime Fail"})
                holdings_to_sell.append(sym); continue

        active_holdings = [
            s for s in positions 
            if s not in holdings_to_sell 
            and not any(o['type'] == 'SELL' and o['symbol'] == s for o in orders_queue)
        ]
        
        candidates = [s for s in scores.loc[tomorrow].dropna().sort_values(ascending=False).index 
                      if s not in positions and check_regime(tomorrow, s, close, benchmarks_ma) and (s not in cooldown_dict or tomorrow > cooldown_dict[s])]
        
        vix_scaler = 0.3 if curr_vix > 40 else 0.6 if curr_vix > 30 else 0.8 if curr_vix > 20 else 1.0
        total_eq = cash + sum(p.market_value for p in positions.values())
        target_pos_size = total_eq * BASE_POSITION_SIZE * vix_scaler
        proj = list(active_holdings)
        
        def is_allowed(cand): return True if curr_vix < 25.0 else sum(1 for x in proj if get_sector(x)==get_sector(cand)) < 2

        while active_holdings and candidates:
            active_holdings.sort(key=lambda x: scores.loc[tomorrow, x] if not pd.isna(scores.loc[tomorrow, x]) else -999)
            worst = active_holdings[0]
            if (tomorrow - positions[worst].entry_date).days < MIN_HOLD_DAYS: active_holdings.pop(0); continue
            
            valid_idx = next((i for i, c in enumerate(candidates) if is_allowed(c)), -1)
            if valid_idx == -1: break
            best = candidates[valid_idx]
            
            w_score = scores.loc[tomorrow, worst] if not pd.isna(scores.loc[tomorrow, worst]) else 0
            b_score = scores.loc[tomorrow, best]
            v_hold = vol_20.loc[tomorrow, worst] if not pd.isna(vol_20.loc[tomorrow, worst]) else 0.0
            if b_score > w_score * min(2.0, 1.4 + v_hold*0.1) and b_score > w_score + 0.05:
                if not any(o['type'] == 'SELL' and o['symbol'] == worst for o in orders_queue):
                    orders_queue.append({'type': 'SELL', 'symbol': worst, 'reason': f"Swap to {best}"})
                if not any(o['type'] == 'BUY' and o['symbol'] == best for o in orders_queue):
                    orders_queue.append({'type': 'BUY', 'symbol': best, 'amount_usd': target_pos_size})
                proj.remove(worst); proj.append(best); active_holdings.pop(0); candidates.pop(valid_idx)
            else: break
            
        current_holding_count = len(positions)
        pending_sell_count = len([o for o in orders_queue if o['type'] == 'SELL'])
        pending_buy_count = len([o for o in orders_queue if o['type'] == 'BUY'])
        
        open_slots = MAX_TOTAL_POSITIONS - (current_holding_count - pending_sell_count + pending_buy_count)
        
        for _ in range(max(0, open_slots)):
            if not candidates or curr_vix > PANIC_VIX_THRESHOLD: break
            valid_idx = next((i for i, c in enumerate(candidates) if is_allowed(c)), -1)
            if valid_idx != -1:
                cand = candidates.pop(valid_idx)
                if not any(o['type'] == 'BUY' and o['symbol'] == cand for o in orders_queue):
                    orders_queue.append({'type': 'BUY', 'symbol': cand, 'amount_usd': target_pos_size})
                proj.append(cand)
                
        # 每日結算後，再次確保對列完美
        orders_queue = sanitize_queue(positions, orders_queue)
        state['last_processed_date'] = tomorrow.strftime('%Y-%m-%d')

    state['cash'] = cash
    state['positions'] = {sym: pos.to_dict() for sym, pos in positions.items()}
    state['orders_queue'] = orders_queue
    state['cooldown_dict'] = {sym: d.strftime('%Y-%m-%d') for sym, d in cooldown_dict.items()}

    if not dry_run: save_state(state)
    
    total_eq = cash + sum(p.market_value for p in positions.values())
    latest_vix = vix_series.iloc[-1]
    
    tw_open = "🟢" if is_trading_day['^TWII'].iloc[-1] else "🛑 休市"
    us_open = "🟢" if is_trading_day['SPY'].iloc[-1] else "🛑 休市"

    def get_bull_bear(bench):
        if bench not in close.columns: return "❓未知"
        p = close[bench].iloc[-1]
        ma100 = benchmarks_ma[bench].iloc[-1] if bench in benchmarks_ma else np.nan
        ma50 = benchmarks_ma.get(f"{bench}_50").iloc[-1] if f"{bench}_50" in benchmarks_ma else np.nan
        if pd.isna(p) or pd.isna(ma100): return "❓未知"
        if not pd.isna(ma50):
            return "🐂 牛" if (p > ma100) and (ma50 > ma100) else "🐻 熊"
        return "🐂 牛" if p > ma100 else "🐻 熊"

    us_status = get_bull_bear('QQQ')
    tw_status = get_bull_bear('^TWII')
    btc_status = get_bull_bear('BTC-USD')

    msg = f"🦁 Vanguard 實盤指示 (Dry-Run)" if dry_run else f"🦁 Vanguard 實盤指示"
    msg += f"\n📅 決策對象：下一個交易日開盤"
    msg += f"\n🌍 市場狀態：台股 {tw_open} | 美股 {us_open}"
    msg += f"\n🧭 板塊趨勢：美股 {us_status} | 台股 {tw_status} | 加密 {btc_status}"
    msg += f"\n🔒 VIX: {latest_vix:.1f} | 總資產估算: ${total_eq:,.0f}\n━━━━━━━━━━━━━━\n"
    
    if intraday_alerts:
        msg += "🚨 【昨日盤中防禦觸發】(系統已記帳)\n" + "\n".join(intraday_alerts) + "\n--------------------\n"

    sells = [o for o in orders_queue if o['type'] == 'SELL']
    buys = [o for o in orders_queue if o['type'] == 'BUY']
    
    if sells:
        msg += "🔴 【賣出指令】(請於開盤賣出)\n"
        for s in sells: msg += f"❌ 賣出 {s['symbol']} ({s.get('reason','')})\n"
        msg += "--------------------\n"
    if buys:
        msg += "🟢 【買入指令】(請於開盤買入)\n"
        for b in buys:
            params = SECTOR_PARAMS.get(get_sector(b['symbol']), SECTOR_PARAMS['DEFAULT'])
            curr_p = close[b['symbol']].iloc[-1] if b['symbol'] in close.columns and not pd.isna(close[b['symbol']].iloc[-1]) else 0
            stop_est = curr_p * (1 - params['stop'])
            msg += f"💰 買入 {b['symbol']}\n   目標佔比: {b['amount_usd']/total_eq*100:.0f}% 總資金\n   (買入後請立即掛硬止損: {stop_est:.2f} / -{params['stop']*100:g}%)\n"
        msg += "--------------------\n"
        
    if positions:
        msg += "🛡️ 【持倉移動防禦線】(請更新觸價單)\n"
        for sym, p in positions.items():
            params = p.get_params()
            hard = p.entry_price * (1 - params['stop'])
            profit_ratio = (p.max_price - p.entry_price) / p.entry_price
            trail_pct = params['stop']
            for threshold, pct in sorted(params['trail'].items(), key=lambda x: x[0], reverse=True):
                if profit_ratio >= threshold: trail_pct = pct; break
            if latest_vix > 30.0: trail_pct *= 0.5
            trail_price = p.max_price * (1 - trail_pct)
            def_line = max(hard, trail_price)
            
            pct_str = f"硬止損 -{params['stop']*100:g}%" if def_line == hard else f"高點回撤 -{trail_pct*100:g}%"
            msg += f"• {sym}: 跌破 {def_line:.2f} 停損/停利 ({pct_str})\n"
            
    if not sells and not buys: msg += "☕ 今日無換倉動作，維持防禦掛單即可"

    print(msg)
    if not dry_run and LINE_TOKEN and LINE_USER_ID:
        try:
            requests.post('https://api.line.me/v2/bot/message/push', 
                          headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_TOKEN}'},
                          json={"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg}]})
        except Exception as e: print(f"LINE 發送失敗: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="不儲存 state 且不發送 LINE")
    args = parser.parse_args()
    run_live(dry_run=args.dry_run)
