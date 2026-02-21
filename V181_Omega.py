# =========================================================
# V17.50 VANGUARD LIVE ENGINE (純淨先鋒實盤引擎)
# 核心機制: Shadow State (影子狀態追蹤) + Catch-up Loop (防斷線追趕)
# 執行環境: GitHub Actions (Daily 13:00 UTC / 台灣 21:00)
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
DATA_DOWNLOAD_DAYS = 250 # 實盤只需取近 250 天維持 MA 運算即可
SLIPPAGE_RATE = 0.002
RATES = {
    'CRYPTO_COMM': 0.001, 'US_COMM': 0.001, 'TW_COMM': 0.001425 * 0.22,
    'TW_TAX_STOCK': 0.003, 'TW_TAX_ETF': 0.001
}

GAP_UP_LIMIT = 0.10
PANIC_VIX_THRESHOLD = 40.0
MIN_HOLD_DAYS = 3
USD_TWD_RATE = 32.5 # 備用靜態匯率
INITIAL_CAPITAL_USD = 100000.0 / USD_TWD_RATE
MAX_TOTAL_POSITIONS = 3
BASE_POSITION_SIZE = 1.0 / MAX_TOTAL_POSITIONS

STATE_FILE = 'state.json'
LINE_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')

# =========================
# 2) Strategy Parameters (對齊 V17.50 最終版)
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
    'GGLL': 'LEV_2X', 'FNGU': 'LEV_3X',
    'NVDL': 'LEV_2X', 'ASTX': 'LEV_2X',
    'HOOX': 'LEV_2X', 'IONX': 'LEV_2X', 'OKLL': 'LEV_2X', 'RKLX': 'LEV_2X',
    'LUNR': 'US_GROWTH', 'QUBT': 'US_GROWTH',
    'PLTR': 'US_GROWTH', 'SMCI': 'US_GROWTH', 'CRWD': 'US_GROWTH', 'PANW': 'US_GROWTH',
    'APP': 'US_GROWTH', 'SHOP': 'US_GROWTH',
    'IONQ': 'US_GROWTH', 'RGTI': 'US_GROWTH', 'RKLB': 'US_GROWTH', 'VRT': 'US_GROWTH',
    'VST': 'US_GROWTH', 'ASTS': 'US_GROWTH', 'OKLO': 'US_GROWTH', 'VKTX': 'US_GROWTH',
    'HOOD': 'US_GROWTH', 'SERV': 'US_GROWTH',
    'GLD': 'US_STOCK',
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

    def get_params(self): return SECTOR_PARAMS.get(self.sector, SECTOR_PARAMS['DEFAULT'])

    @property
    def market_value(self): return self.units * self.current_price

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
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    # 預設狀態
    return {
        "cash": INITIAL_CAPITAL_USD, "positions": {}, "orders_queue": [], "cooldown_dict": {},
        "last_processed_date": (datetime.utcnow() - pd.Timedelta(days=5)).strftime('%Y-%m-%d')
    }

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

# =========================
# 4) Data & Math
# =========================
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

def check_regime(date, sym, close_df, benchmarks_ma):
    sector = get_sector(sym)
    bench = 'BTC-USD' if 'CRYPTO' in sector else '^TWII' if 'TW_' in sector else '^HSI' if 'CN_' in sector else 'QQQ'
    if bench not in close_df.columns: return True
    price, ma100, ma50 = close_df.loc[date, bench], benchmarks_ma[bench].loc[date], benchmarks_ma.get(f"{bench}_50")
    if pd.isna(price) or pd.isna(ma100): return True
    if ma50 is not None and not pd.isna(ma50.loc[date]): return (price > ma100) and (ma50.loc[date] > ma100)
    return price > ma100

# =========================
# 5) Main Live Engine
# =========================
def run_live(dry_run=False):
    print("🚀 Vanguard Live Engine 啟動...")
    close, open_, high, low, is_trading_day = get_data()
    
    state = load_state()
    
    # 決定今天我們要看的是哪一根 K 線 (以資料庫最後一個可用日為準)
    today = close.index[-1]
    
    # 若今日資料尚未產生，跳過
    if pd.isna(close.loc[today, 'SPY']) and pd.isna(close.loc[today, '^TWII']):
        today = close.index[-2]

    cash = state['cash']
    positions = {sym: Position.from_dict(d) for sym, d in state['positions'].items()}
    orders_queue = state['orders_queue']
    cooldown_dict = {sym: pd.Timestamp(d) for sym, d in state['cooldown_dict'].items()}
    
    # Precalculate
    ma20, ma50, ma60 = close.rolling(20).mean(), close.rolling(50).mean(), close.rolling(60).mean()
    benchmarks_ma = {b: close[b].rolling(100).mean() for b in ['SPY', 'QQQ', 'BTC-USD', '^TWII'] if b in close.columns}
    for b in benchmarks_ma.keys(): benchmarks_ma[f"{b}_50"] = close[b].rolling(50).mean()
    mom_20, vol_20 = close.pct_change(20), close.pct_change().rolling(20).std() * np.sqrt(252)
    scores = pd.DataFrame(index=close.index, columns=close.columns)
    
    for t in ASSET_MAP.keys():
        if t not in close.columns: continue
        trend_ok = (close[t] > ma20[t]) & (ma20[t] > ma50[t]) & (close[t] > ma60[t])
        valid_mom = (mom_20[t] > (0.08 if 'TW' in ASSET_MAP[t] else 0.05 if '3X' in ASSET_MAP[t] else 0.0)).fillna(False)
        mult = (1.0 + vol_20[t].fillna(0)) * (1.2 if t in TIER_1_ASSETS else 1.0)
        scores[t] = np.where(trend_ok & valid_mom, mom_20[t] * mult * (0.9 if 'TW' in ASSET_MAP[t] else 1.0), np.nan)
    
    vix_series = close['^VIX'] if '^VIX' in close.columns else pd.Series(20, index=close.index)
    curr_vix = vix_series.loc[today] if not pd.isna(vix_series.loc[today]) else 20.0

    # ---------------------------------------------------------
    # 模擬 1: 結算「今日」盤中是否觸發停損 (只更新最高價或清倉)
    # ---------------------------------------------------------
    cols_to_del = []
    intraday_alerts = []
    for sym, pos in positions.items():
        if not is_trading_day.loc[today, sym] or pd.isna(low.loc[today, sym]): continue
        pos.current_price = close.loc[today, sym]
        
        # 實盤中，我們用前一天的 VIX 當作今日的防禦參數
        prev_vix = vix_series.iloc[-2] if len(vix_series) > 1 else 20.0
        triggered, exec_price, reason = pos.check_intraday_exit(open_.loc[today, sym], high.loc[today, sym], low.loc[today, sym], prev_vix)
        
        if triggered:
            cash += pos.units * exec_price * (1 - SLIPPAGE_RATE) # 簡化成本
            if 'CRYPTO' in pos.sector or 'LEV' in pos.sector: cooldown_dict[sym] = today + pd.Timedelta(days=1)
            else: cooldown_dict[sym] = today + pd.Timedelta(days=5)
            cols_to_del.append(sym)
            intraday_alerts.append(f"⚠️ {sym} 今日盤中觸發: {reason}")
            
    for sym in cols_to_del: del positions[sym]

    # ---------------------------------------------------------
    # 模擬 2: 產生「明日開盤 (T+1)」的交易指令
    # ---------------------------------------------------------
    new_orders = []
    holdings_to_sell = []
    
    for sym, pos in positions.items():
        days_held = (today - pos.entry_date).days
        if curr_vix > 45.0: new_orders.append({'type': 'SELL', 'symbol': sym, 'reason': "VIX>45斷路"}); holdings_to_sell.append(sym); continue
        if days_held > pos.get_params()['zombie'] and pos.current_price <= pos.entry_price:
            new_orders.append({'type': 'SELL', 'symbol': sym, 'reason': "Zombie"}); holdings_to_sell.append(sym); continue
        if not check_regime(today, sym, close, benchmarks_ma):
            new_orders.append({'type': 'SELL', 'symbol': sym, 'reason': "Regime Fail"}); holdings_to_sell.append(sym); continue

    active_holdings = [s for s in positions if s not in holdings_to_sell]
    candidates = [s for s in scores.loc[today].dropna().sort_values(ascending=False).index 
                  if s not in positions and check_regime(today, s, close, benchmarks_ma) and (s not in cooldown_dict or today > cooldown_dict[s])]
    
    vix_scaler = 0.3 if curr_vix > 40 else 0.6 if curr_vix > 30 else 0.8 if curr_vix > 20 else 1.0
    total_eq = cash + sum(p.market_value for p in positions.values())
    target_pos_size = total_eq * BASE_POSITION_SIZE * vix_scaler
    
    proj = list(active_holdings)
    def is_allowed(cand): return True if curr_vix < 25.0 else sum(1 for x in proj if get_sector(x)==get_sector(cand)) < 2

    # 弒君換馬
    while active_holdings and candidates:
        active_holdings.sort(key=lambda x: scores.loc[today, x] if not pd.isna(scores.loc[today, x]) else -999)
        worst = active_holdings[0]
        if (today - positions[worst].entry_date).days < MIN_HOLD_DAYS: active_holdings.pop(0); continue
        
        valid_idx = next((i for i, c in enumerate(candidates) if is_allowed(c)), -1)
        if valid_idx == -1: break
        best = candidates[valid_idx]
        
        w_score = scores.loc[today, worst] if not pd.isna(scores.loc[today, worst]) else 0
        b_score = scores.loc[today, best]
        v_hold = vol_20.loc[today, worst] if not pd.isna(vol_20.loc[today, worst]) else 0.0
        if b_score > w_score * min(2.0, 1.4 + v_hold*0.1) and b_score > w_score + 0.05:
            new_orders.append({'type': 'SELL', 'symbol': worst, 'reason': f"Swap to {best}"})
            new_orders.append({'type': 'BUY', 'symbol': best, 'amount_usd': target_pos_size})
            proj.remove(worst); proj.append(best); active_holdings.pop(0); candidates.pop(valid_idx)
        else: break
        
    # 填補空缺
    open_slots = MAX_TOTAL_POSITIONS - len(active_holdings) + len([o for o in new_orders if o['type']=='SELL' and o['symbol'] in active_holdings])
    for _ in range(max(0, open_slots)):
        if not candidates or curr_vix > PANIC_VIX_THRESHOLD: break
        valid_idx = next((i for i, c in enumerate(candidates) if is_allowed(c)), -1)
        if valid_idx != -1:
            cand = candidates.pop(valid_idx)
            proj.append(cand)
            new_orders.append({'type': 'BUY', 'symbol': cand, 'amount_usd': target_pos_size})

    # Save State
    state['cash'] = cash
    state['positions'] = {sym: pos.to_dict() for sym, pos in positions.items()}
    state['orders_queue'] = new_orders
    state['cooldown_dict'] = {sym: d.strftime('%Y-%m-%d') for sym, d in cooldown_dict.items()}
    state['last_processed_date'] = today.strftime('%Y-%m-%d')

    if not dry_run: save_state(state)
    
    # 格式化 LINE 推播
    msg = f"🦁 Vanguard 實盤指示 (Dry-Run)" if dry_run else f"🦁 Vanguard 實盤指示"
    msg += f"\n📅 決策日: {today.strftime('%Y-%m-%d')} 收盤"
    msg += f"\n🔒 VIX: {curr_vix:.1f} | 總資產估算: ${total_eq:,.0f}\n━━━━━━━━━━━━━━\n"
    
    if intraday_alerts:
        msg += "🚨 【今日盤中洗盤紀錄】(系統已自動記帳)\n" + "\n".join(intraday_alerts) + "\n--------------------\n"

    sells = [o for o in new_orders if o['type'] == 'SELL']
    buys = [o for o in new_orders if o['type'] == 'BUY']
    
    if sells:
        msg += "🔴 【賣出指令】(請於明日開盤賣出)\n"
        for s in sells: msg += f"❌ 賣出 {s['symbol']} ({s.get('reason','')})\n"
        msg += "--------------------\n"
    if buys:
        msg += "🟢 【買入指令】(請於明日開盤買入)\n"
        for b in buys:
            params = SECTOR_PARAMS.get(get_sector(b['symbol']), SECTOR_PARAMS['DEFAULT'])
            curr_p = close[b['symbol']].iloc[-1]
            stop_est = curr_p * (1 - params['stop'])
            msg += f"💰 買入 {b['symbol']}\n   資金佔比: {b['amount_usd']/total_eq*100:.0f}% 總資金\n   (買入後請立即掛硬止損: {stop_est:.2f})\n"
        msg += "--------------------\n"
        
    if positions:
        msg += "🛡️ 【持倉動態防禦線】(請更新觸價單)\n"
        for sym, p in positions.items():
            params = p.get_params()
            hard = p.entry_price * (1 - params['stop'])
            profit_ratio = (p.max_price - p.entry_price) / p.entry_price
            trail_pct = params['stop']
            for threshold, pct in sorted(params['trail'].items(), key=lambda x: x[0], reverse=True):
                if profit_ratio >= threshold: trail_pct = pct; break
            if curr_vix > 30.0: trail_pct *= 0.5
            trail_price = p.max_price * (1 - trail_pct)
            def_line = max(hard, trail_price)
            msg += f"• {sym}: 跌破 {def_line:.2f} 停損/停利\n"
            
    if not sells and not buys: msg += "☕ 明日無換倉動作，維持防禦掛單即可"

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
