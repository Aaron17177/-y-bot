# =========================================================
# V18.00 VANGUARD LIVE ENGINE (V2 優化版)
# 基於 V17.50 + CR-01~CR-09 回測驗證優化
# CR-01: LEV_2X 板塊參數補齊 (Bugfix)
# CR-02: 非交易日分數遮蔽 (Bugfix)
# CR-06: 移除 CRYPTO_SPOT 6 個系統性虧損標的
# CR-07: MIN_HOLD_DAYS 3→5 (減少短持巨虧)
# CR-08: 移除 12 個反覆虧損標的
# CR-09: CRYPTO_SPOT 維持 MIN_HOLD=3 (高波動幣分開處理)
# CR_FIX_12: 市場狀態顯示修正 (適配台灣晚上9點排程)
# CR_FIX_13: 孤兒賣出指令修正 (持倉不存在時直接丟棄)
# CR_FIX_14: 孤兒買入指令修正 (已持有時直接丟棄)
# 保留: CR_FIX_05/07/08/09/10/11 全部 Live 基礎設施
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

DATA_DOWNLOAD_DAYS = 350  # [FIX_12] 250→350 確保 MA200 可計算
SLIPPAGE_RATE = 0.002
RATES = {
    'CRYPTO_COMM': 0.001, 'US_COMM': 0.001, 'TW_COMM': 0.001425 * 0.22,
    'LEV_COMM': 0.001,  # [OPT-04] 明確定義 LEV sector 手續費
    'TW_TAX_STOCK': 0.003, 'TW_TAX_ETF': 0.001
}

GAP_UP_LIMIT = 0.10
PANIC_VIX_THRESHOLD = 40.0
MIN_HOLD_DAYS = 3                    # [V18.05] 5→3 加速止血 (A/B 驗證 CAGR+32pp)
MIN_HOLD_DAYS_CRYPTO_SPOT = 2         # [V18.05] 3→2 CRYPTO_SPOT 更快認錯
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
    # [V18.05] Zombie 天數全面縮短 ~30% (A/B 驗證 CAGR+32pp, MaxDD 不變)
    'CRYPTO_SPOT': {'stop': 0.40, 'zombie': 7, 'trail': {2.0: 0.25, 1.0: 0.30, 0.5: 0.35, 0.0: 0.40}},
    'CRYPTO_LEV':  {'stop': 0.50, 'zombie': 5, 'trail': {3.0: 0.30, 1.0: 0.40, 0.5: 0.45, 0.0: 0.50}},
    'CRYPTO_MEME': {'stop': 0.60, 'zombie': 4, 'trail': {5.0: 0.30, 2.0: 0.40, 1.0: 0.50, 0.0: 0.60}},
    'US_STOCK':    {'stop': 0.25, 'zombie': 7, 'trail': {1.0: 0.15, 0.5: 0.20, 0.2: 0.20, 0.0: 0.25}},
    'US_LEV':      {'stop': 0.35, 'zombie': 5, 'trail': {1.0: 0.20, 0.5: 0.25, 0.2: 0.30, 0.0: 0.35}},
    'LEV_2X':      {'stop': 0.35, 'zombie': 5, 'trail': {1.0: 0.20, 0.5: 0.25, 0.2: 0.30, 0.0: 0.35}},
    'LEV_3X':      {'stop': 0.45, 'zombie': 4, 'trail': {2.0: 0.25, 1.0: 0.30, 0.5: 0.35, 0.0: 0.45}},
    'TW_STOCK':    {'stop': 0.25, 'zombie': 8, 'trail': {1.0: 0.15, 0.5: 0.20, 0.2: 0.20, 0.0: 0.25}},
    'US_GROWTH':   {'stop': 0.40, 'zombie': 7, 'trail': {1.0: 0.25, 0.5: 0.30, 0.2: 0.35, 0.0: 0.40}},
    'DEFAULT':     {'stop': 0.30, 'zombie': 7, 'trail': {1.0: 0.20, 0.5: 0.25, 0.0: 0.30}}
}

ASSET_MAP = {
    # [CR-06] ADA-USD, HBAR-USD 移除 (CRYPTO_SPOT 老鼠屎)
    'BTC-USD': 'CRYPTO_SPOT',
    # [CR-06] SOL-USD, NEAR-USD 移除 (CRYPTO_SPOT 老鼠屎)
    'AVAX-USD': 'CRYPTO_SPOT',
    'KAS-USD': 'CRYPTO_MEME', 'RENDER-USD': 'CRYPTO_MEME',
    'ETH-USD': 'CRYPTO_SPOT','SOL-USD': 'CRYPTO_SPOT', 'NEAR-USD': 'CRYPTO_MEME',
    'DOGE-USD': 'CRYPTO_MEME', 'SHIB-USD': 'CRYPTO_MEME', 'BONK-USD': 'CRYPTO_MEME',
    'PEPE24478-USD': 'CRYPTO_MEME', 'WIF-USD': 'CRYPTO_MEME',
    # [CR-06] SUI20947-USD 移除; [CR-08] ENA-USD 移除
    'TAO22974-USD': 'CRYPTO_MEME',

    'FNGU': 'LEV_2X',
    # [CR-08] NVDL 移除
    'ASTX': 'LEV_2X','GGLL':'US_GROWTH',
    # [V18.10 流動性] 'HOOX' 移除（日 $2.8M, $20M 目標下 10% 部位佔比太薄）
    'IONX': 'LEV_2X', 'OKLL': 'LEV_2X', 'RKLX': 'LEV_2X',
    'LUNR': 'US_GROWTH', 'QUBT': 'US_GROWTH',
    'PLTR': 'US_GROWTH', 'CRWD': 'US_STOCK', 'PANW': 'US_GROWTH',  # [V18.06] 重分類
    

    'APP': 'US_GROWTH','BE':'US_STOCK','ISRG':'US_GROWTH',  # [V18.06] 重分類
    'CRCL': 'US_GROWTH','MU':'US_GROWTH','SNDK':'US_STOCK',  # [V18.06] 重分類

    'LEU': 'US_GROWTH',  # [BUG-03] 移除重複 'BE' key

    'IONQ': 'US_STOCK', 'RGTI': 'US_GROWTH', 'RKLB': 'US_GROWTH', 'VRT': 'US_GROWTH',  # [V18.06] 重分類
    'VST': 'US_GROWTH', 'ASTS': 'US_GROWTH', 'OKLO': 'US_GROWTH',
    'HOOD': 'US_GROWTH',  # [V18.10 流動性] 'SERV' 移除（日 $25M，1.1% 部位佔比偏薄）
    'GLD': 'US_STOCK','GLW': 'US_STOCK',
    # === A/B Test 倖存者保留 ===
    # [CR-08] UGL 移除; [CR-06] PENDLE-USD 移除
    'AGQ': 'US_STOCK',
    'ALAB': 'US_GROWTH', 'ARM': 'US_GROWTH', 'CEG': 'US_GROWTH', 'URA': 'US_STOCK',
    # [V18.10 NO_TW_EXPANDED] 移除全部 .TW / .TWO（自動化路徑：Alpaca + Binance）
    # 回測：CAGR 856%, MaxDD -54%, Sharpe 1.70 (vs baseline CAGR 1021%, MaxDD -49%)
    # 替代品：US 半導體供應鏈 + IP + 槓桿 ETF
    'AMAT': 'US_GROWTH',   # Applied Materials (沉積/蝕刻)
    'LRCX': 'US_GROWTH',   # Lam Research
    'ASML': 'US_GROWTH',   # ASML (微影)
    'TER':  'US_GROWTH',   # Teradyne (測試，補 6515)
    'TSM':  'US_GROWTH',   # TSMC ADR
    # --- V18.01 新增標的 ---
    'MSTR': 'US_GROWTH', 'COIN': 'US_GROWTH', 'MARA': 'US_STOCK',
    'SMCI': 'US_GROWTH', 'AXON': 'US_GROWTH',
    'XRP-USD': 'CRYPTO_SPOT', 'SUI20947-USD': 'CRYPTO_MEME',
    # --- V18.02 擴大標的池 ---
    'NVDA': 'US_GROWTH', 'TSLA': 'US_GROWTH', 'META': 'US_GROWTH',
    'AVGO': 'US_GROWTH', 'AMD': 'US_GROWTH',
    'SHOP': 'US_GROWTH', 'NET': 'US_STOCK', 'ANET': 'US_GROWTH',
    # --- V18.04 美股擴展 ---
    'TMDX': 'US_GROWTH',   # TransMedics (器官運輸)
    'LLY': 'US_STOCK',     # Eli Lilly (GLP-1)
    'HIMS': 'US_GROWTH',   # Hims (遠距醫療)
    'RDDT': 'US_GROWTH',   # Reddit (社群)
    # [V18.10] 'CYBR' 移除（Alpaca tradable=False，可能合併下市）
    'GOOG': 'US_STOCK',    # Google
    'UBER': 'US_GROWTH',   # Uber (出行)
    'SPOT': 'US_GROWTH',   # Spotify (串流)
    'FTNT': 'US_GROWTH',   # Fortinet (網安)
    'NU': 'US_GROWTH',     # Nu Holdings (FinTech)

    # [V18.10] 補強 universe (NO_TW 後)
    # 半導體深化
    'KLAC': 'US_GROWTH',   # KLA - 量測檢測
    'ENTG': 'US_GROWTH',   # Entegris - 半導體耗材
    'ON':   'US_GROWTH',   # ON Semi - 類比/車用
    'MCHP': 'US_STOCK',    # Microchip - MCU
    'ADI':  'US_STOCK',    # Analog Devices
    'NXPI': 'US_STOCK',    # NXP - 車用半導體
    'MRVL': 'US_GROWTH',   # Marvell - ASIC
    # 網通/儲存
    'NTAP': 'US_STOCK',    # NetApp - 企業儲存
    'PSTG': 'US_GROWTH',   # Pure Storage
    # AI 基礎設施
    'DELL': 'US_GROWTH',   # Dell - AI 伺服器
    'HPE':  'US_STOCK',    # HPE
    # 槓桿 ETF
    'QLD':  'LEV_2X',      # 2x QQQ
    'USD':  'LEV_2X',      # 2x Semiconductor
    'SOXL': 'LEV_3X',      # 3x SOXX
    # ADR
    'SE':   'US_GROWTH',   # Sea Limited
    # [V18.11 註記] 嘗試加 16 檔小型股 (RIOT/HUT/SMR/...) → CAGR 856→665, MaxDD -54→-63
    # 結論：universe 過大稀釋動能訊號，回到 78 美股最優
}

TIER_1_ASSETS = [
    # --- 核心降維：回歸第一性原理的 TIER_1 ---
    # 爆發力妖股：
    'RGTI', 'QUBT', 'ASTS', 'IONQ', 'RKLB', 'VST', 'SNDK', 'ALAB', 'PLTR',
    # 幣圈王者：
    'BTC-USD', 'ETH-USD', 'BONK-USD', 'DOGE-USD',
    # AI/科技巨頭 (信仰加權)：
    'NVDA', 'TSLA', 'META', 'AVGO', 'AMD', 'PANW',
    # 戰略資產/特許經營：
    'MSTR', 'COIN', 'AXON'
]  # V18.02

ALL_TICKERS = list(set(list(ASSET_MAP.keys()) + ['SPY', 'QQQ', 'BTC-USD', '^TWII', '^HSI', '^VIX', 'TWD=X']))

# =========================
# 3) Live State & Position Engine
# =========================

class Position:
    def __init__(self, symbol, entry_date, entry_price, units, sector, max_price=None, current_price=None,
                 entry_price_twd=None, max_price_twd=None):
        self.symbol = symbol
        self.entry_date = entry_date if isinstance(entry_date, pd.Timestamp) else pd.Timestamp(entry_date)
        self.entry_price = float(entry_price)
        self.units = float(units)
        self.sector = sector
        self.max_price = float(max_price) if max_price else float(entry_price)
        self.current_price = float(current_price) if current_price else float(entry_price)
        # 台股專用：直接存 NT$ 原價，避免匯率來回轉換誤差
        self.entry_price_twd = float(entry_price_twd) if entry_price_twd else None
        self.max_price_twd = float(max_price_twd) if max_price_twd else None

    @classmethod
    def from_dict(cls, data):
        return cls(data['symbol'], data['entry_date'], data['entry_price'], 
                   data['units'], data['sector'], data.get('max_price'), data.get('current_price'),
                   data.get('entry_price_twd'), data.get('max_price_twd'))

    def to_dict(self):
        d = {
            'symbol': self.symbol, 'entry_date': self.entry_date.strftime('%Y-%m-%d'),
            'entry_price': self.entry_price, 'units': self.units,
            'sector': self.sector, 'max_price': self.max_price, 'current_price': self.current_price
        }
        if self.entry_price_twd is not None: d['entry_price_twd'] = self.entry_price_twd
        if self.max_price_twd is not None: d['max_price_twd'] = self.max_price_twd
        return d

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

        if curr_vix > 30.0: trail_pct = min(trail_pct * 1.3, params['stop'])  # [BUG-01] 高波動放寬 trail，不收緊
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
    # [OPT-04] 原子寫入：先寫 tmp 再 rename，防止中斷損壞
    tmp = STATE_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=4)
    os.replace(tmp, STATE_FILE)

def get_data(start_date=None):
    if start_date is None:
        start_date = datetime.utcnow() - pd.Timedelta(days=DATA_DOWNLOAD_DAYS)
    start_str = start_date.strftime('%Y-%m-%d')
    data = yf.download(ALL_TICKERS, start=start_str, progress=False, auto_adjust=True)
    if isinstance(data.columns, pd.MultiIndex):
        raw_close, close = data['Close'], data['Close'].ffill()
        open_, high, low = data['Open'].ffill(), data['High'].ffill(), data['Low'].ffill()
    else:
        raw_close, close = data, data.ffill()
        open_, high, low = close.copy(), close.copy(), close.copy()

    is_trading_day = ~raw_close.isna()
    twd_series = close['TWD=X'].ffill().bfill() if 'TWD=X' in close.columns else pd.Series(USD_TWD_RATE, index=close.index)

    # [FIX_11] 保留台股原始台幣 High，供 FIX_10 精確更新 max_price_twd
    raw_high_twd = high.copy()

    for col in close.columns:
        if '.TW' in col or '.TWO' in col:
            close[col] /= twd_series; open_[col] /= twd_series
            high[col]  /= twd_series; low[col]   /= twd_series

    cols_to_drop = [c for c in close.columns if c == 'TWD=X']
    if cols_to_drop:
        for df in [close, open_, high, low, is_trading_day, raw_high_twd]: df.drop(columns=cols_to_drop, inplace=True)
        
    # [FIX_09] 回傳 twd_series + raw_high_twd 供顯示換算使用
    return close, open_, high, low, is_trading_day, twd_series, raw_high_twd

def get_sector(sym): return ASSET_MAP.get(sym, 'US_STOCK')

def get_costs(sector, sym, gross_amount, action):
    comm = gross_amount * RATES.get(f"{sector.split('_')[0]}_COMM", RATES['US_COMM'])
    tax = gross_amount * (RATES['TW_TAX_ETF'] if sym.startswith('00') else RATES['TW_TAX_STOCK']) if action == 'SELL' and 'TW' in sector else 0.0
    return comm, tax

# [BROKER_LOG] 旁路記錄 — 每筆 BUY/SELL 成交寫一行到 broker_trades.csv，失敗不影響主邏輯
BROKER_TRADES_CSV = 'broker_trades.csv'
BROKER_TRADES_HEADER = "timestamp,symbol,side,qty,signal_price,fill_price,slippage_pct,reason,sector\n"

def log_broker_trade(symbol, side, qty, signal_price, fill_price, reason, sector):
    try:
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        slip_pct = (fill_price / signal_price - 1.0) * 100.0 if signal_price else 0.0
        row = f"{timestamp},{symbol},{side},{qty:.6f},{signal_price:.6f},{fill_price:.6f},{slip_pct:+.4f},{reason},{sector}\n"
        write_header = not os.path.exists(BROKER_TRADES_CSV)
        with open(BROKER_TRADES_CSV, 'a') as f:
            if write_header:
                f.write(BROKER_TRADES_HEADER)
            f.write(row)
    except Exception as e:
        print(f"⚠️ log_broker_trade failed for {symbol} {side}: {e}")

def check_regime(date, sym, close_df, benchmarks_ma):
    sector = get_sector(sym)
    bench = 'BTC-USD' if 'CRYPTO' in sector else '^TWII' if 'TW_' in sector else '^HSI' if 'CN_' in sector else 'QQQ'
    if bench not in close_df.columns: return True
    price = close_df.loc[date, bench]
    ma100 = benchmarks_ma[bench].loc[date]
    ma50_series = benchmarks_ma.get(f"{bench}_50")  # [BUG-05] 明確命名為 Series
    if pd.isna(price) or pd.isna(ma100): return True
    if ma50_series is not None:
        ma50_val = ma50_series.loc[date]
        if not pd.isna(ma50_val):
            return (price > ma100) and (ma50_val > ma100)
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

    # --- [FIX_11] 先讀檔，根據您的買入日期，動態決定要抓多久的資料 ---
    state = load_state()
    positions = {sym: Position.from_dict(d) for sym, d in state['positions'].items()}

    earliest_entry = pd.Timestamp(datetime.utcnow().date() - pd.Timedelta(days=DATA_DOWNLOAD_DAYS))
    if positions:
        min_entry = min([pos.entry_date for pos in positions.values()])
        if min_entry < earliest_entry:
            earliest_entry = min_entry - pd.Timedelta(days=5) # 提早5天策安全
            
    close, open_, high, low, is_trading_day, twd_series, raw_high_twd = get_data(start_date=earliest_entry)

    # 抓取最新匯率供介面顯示
    latest_twd_rate = twd_series.iloc[-1] if not twd_series.empty else USD_TWD_RATE

    today_utc = datetime.utcnow().date()
    completed_dates = [d for d in close.index if d.date() < today_utc]
    if not completed_dates: return

    cash = state['cash']

    # --- [FIX_10] 歷史最高價全自動掃描與修復機制 ---
    naive_high_idx = high.index.tz_localize(None) # 消除 yfinance 時區
    for sym, pos in positions.items():
        if sym in high.columns:
            try:
                # 程式在這裡自動執行：「從您告訴我的買入日期，一路掃描到今天的最高價」
                mask = naive_high_idx >= pos.entry_date
                hist_highs = high.loc[mask, sym]
                if not hist_highs.empty:
                    real_max = hist_highs.max()
                    if pd.notna(real_max) and real_max > pos.max_price:
                        pos.max_price = real_max
                        # [FIX_11] 台股：用原始台幣 High 精確更新，不經匯率來回轉換
                        if 'TW' in pos.sector and sym in raw_high_twd.columns:
                            twd_highs = raw_high_twd.loc[mask, sym]
                            if not twd_highs.empty:
                                pos.max_price_twd = float(twd_highs.max())
            except Exception as e:
                print(f"⚠️ {sym} 最高價修復失敗: {e}")
                
    orders_queue = state['orders_queue']
    cooldown_dict = {sym: pd.Timestamp(d) for sym, d in state['cooldown_dict'].items()}

    # [OPT-03] 清除過期 cooldown
    today_ts = pd.Timestamp(today_utc)
    cooldown_dict = {sym: d for sym, d in cooldown_dict.items() if d > today_ts}

    orders_queue = sanitize_queue(positions, orders_queue)

    # [CR_FIX_13/14] 孤兒指令清理：迴圈外先清一次，避免 dates_to_process 為空時指令永遠卡著
    orders_queue = [o for o in orders_queue
                    if not (o['type'] == 'SELL' and o['symbol'] not in positions)
                    and not (o['type'] == 'BUY' and o['symbol'] in positions)]

    last_processed = pd.Timestamp(state['last_processed_date'])
    dates_to_process = [d for d in completed_dates if d > last_processed]

    ma20, ma50, ma60 = close.rolling(20).mean(), close.rolling(50).mean(), close.rolling(60).mean()
    benchmarks_ma = {b: close[b].rolling(100).mean() for b in ['SPY', 'QQQ', 'BTC-USD', '^TWII'] if b in close.columns}
    for b in list(benchmarks_ma.keys()): benchmarks_ma[f"{b}_50"] = close[b].rolling(50).mean()

    # [FIX_12] Macro Kill Switch: SPY/QQQ MA200
    spy_ma200 = close['SPY'].rolling(200).mean() if 'SPY' in close.columns else None
    qqq_ma200 = close['QQQ'].rolling(200).mean() if 'QQQ' in close.columns else None
        
    MIN_SCORE_THRESHOLD = 0.02  # [OPT-08] 分數最低門檻，避免開倉品質太差
    mom_20, vol_20 = close.pct_change(20), close.pct_change().rolling(20).std() * np.sqrt(252)
    scores = pd.DataFrame(index=close.index, columns=close.columns)
    for t in ASSET_MAP.keys():
        if t not in close.columns: continue
        trend_ok = (close[t] > ma20[t]) & (ma20[t] > ma50[t]) & (close[t] > ma60[t])
        valid_mom = (mom_20[t] > (0.08 if 'TW' in ASSET_MAP[t] else 0.05 if '3X' in ASSET_MAP[t] else 0.0)).fillna(False)
        mult = (1.0 + vol_20[t].fillna(0)) * (1.2 if t in TIER_1_ASSETS else 1.0)
        # [V18.05] 移除台股 0.9x 懲罰 — 手續費已在 get_costs() 精確扣除，不需雙重課稅
        scores[t] = np.where(trend_ok & valid_mom, mom_20[t] * mult, np.nan)

    # [CR-02] 非交易日分數遮蔽：台股休市日不參與排名 (防止 ffill 假價格汙染信號)
    for t in ASSET_MAP.keys():
        if t in scores.columns and t in is_trading_day.columns:
            scores.loc[~is_trading_day[t], t] = np.nan

    vix_series = close['^VIX'] if '^VIX' in close.columns else pd.Series(20, index=close.index)

    intraday_alerts = []

    for date in dates_to_process:
        # [OPT-01] 重命名：signal_date=前一交易日(產生信號), exec_date=執行日(開盤下單)
        date_idx = close.index.get_loc(date)  # [OPT-02] O(1) 取代 list().index() O(n)
        signal_date = close.index[date_idx - 1] if date_idx > 0 else date
        exec_date = date
        
        sell_orders = [o for o in orders_queue if o['type'] == 'SELL']
        buy_orders  = [o for o in orders_queue if o['type'] == 'BUY']
        pending_orders = []

        for o in sell_orders:
            sym = o['symbol']
            # [CR_FIX_13] 先檢查持倉是否存在，避免孤兒賣出指令卡在隊列
            if sym not in positions: continue
            if not is_trading_day.loc[exec_date, sym] or pd.isna(open_.loc[exec_date, sym]): 
                pending_orders.append(o)
                continue
            exec_price = open_.loc[exec_date, sym] * (1 - SLIPPAGE_RATE)
            comm, tax = get_costs(positions[sym].sector, sym, positions[sym].units * exec_price, 'SELL')
            cash += (positions[sym].units * exec_price) - comm - tax
            # [BROKER_LOG] 排隊 SELL 成交記錄
            log_broker_trade(
                symbol=sym, side='SELL', qty=positions[sym].units,
                signal_price=float(open_.loc[exec_date, sym]), fill_price=float(exec_price),
                reason=o.get('reason', 'SELL_QUEUED'), sector=positions[sym].sector,
            )
            del positions[sym]

        for o in buy_orders:
            sym, amount = o['symbol'], o['amount_usd']
            # [CR_FIX_14] 已持有該標的則丟棄孤兒買入指令
            if sym in positions: continue
            if not is_trading_day.loc[exec_date, sym] or pd.isna(open_.loc[exec_date, sym]):
                pending_orders.append(o)
                continue
                
            has_pending_sells = any(x['type']=='SELL' for x in pending_orders)
            if cash < amount * 0.90 and has_pending_sells:
                pending_orders.append(o)
                continue
            
            if cash <= 0 or (open_.loc[exec_date, sym]/close.loc[signal_date, sym]) > (1+GAP_UP_LIMIT): 
                continue
            
            exec_price = open_.loc[exec_date, sym] * (1 + SLIPPAGE_RATE)
            temp_comm, _ = get_costs(get_sector(sym), sym, 1.0, 'BUY')
            units = min(cash, amount) / (exec_price * (1 + temp_comm))
            if units * exec_price < 100: continue
            
            cost = units * exec_price
            comm, _ = get_costs(get_sector(sym), sym, cost, 'BUY')
            cash -= (cost + comm)
            positions[sym] = Position(sym, exec_date, exec_price, units, get_sector(sym))
            # [BROKER_LOG] 排隊 BUY 成交記錄
            log_broker_trade(
                symbol=sym, side='BUY', qty=units,
                signal_price=float(open_.loc[exec_date, sym]), fill_price=float(exec_price),
                reason=o.get('reason', 'BUY_QUEUED'), sector=get_sector(sym),
            )

        orders_queue = pending_orders

        cols_to_del = []
        curr_vix_trail = vix_series.loc[signal_date] if not pd.isna(vix_series.loc[signal_date]) else 20.0
        for sym, pos in positions.items():
            if not is_trading_day.loc[exec_date, sym] or pd.isna(low.loc[exec_date, sym]): continue
            pos.current_price = close.loc[exec_date, sym]
            triggered, exec_price, reason = pos.check_intraday_exit(open_.loc[exec_date, sym], high.loc[exec_date, sym], low.loc[exec_date, sym], curr_vix_trail)
            if triggered:
                signal_exec_price = exec_price  # [BROKER_LOG] 捕捉 pre-slippage 觸發價
                exec_price *= (1 - SLIPPAGE_RATE)
                comm, tax = get_costs(pos.sector, sym, pos.units * exec_price, 'SELL')
                cash += (pos.units * exec_price) - comm - tax
                if 'CRYPTO' in pos.sector or 'LEV' in pos.sector: cooldown_dict[sym] = exec_date + pd.Timedelta(days=1)
                else: cooldown_dict[sym] = exec_date + pd.Timedelta(days=5)
                # [BROKER_LOG] 盤中觸發出場記錄（TRAIL_EXIT/HARD_STOP/GAP_* 等）
                log_broker_trade(
                    symbol=sym, side='SELL', qty=pos.units,
                    signal_price=float(signal_exec_price), fill_price=float(exec_price),
                    reason=reason, sector=pos.sector,
                )
                cols_to_del.append(sym)
                if date == dates_to_process[-1]: intraday_alerts.append(f"⚠️ {sym} 於 {exec_date.strftime('%m/%d')} 盤中觸發: {reason}")
        for sym in cols_to_del: del positions[sym]

        curr_vix = vix_series.loc[exec_date] if not pd.isna(vix_series.loc[exec_date]) else 20.0
        
        holdings_to_sell = []
        for sym, pos in positions.items():
            if not is_trading_day.loc[exec_date, sym]: continue
            if curr_vix > 45.0: 
                if not any(o['type'] == 'SELL' and o['symbol'] == sym for o in orders_queue):
                    orders_queue.append({'type': 'SELL', 'symbol': sym, 'reason': "VIX>45斷路"})
                holdings_to_sell.append(sym); continue
            if (exec_date - pos.entry_date).days > pos.get_params()['zombie'] and pos.current_price <= pos.entry_price:
                if not any(o['type'] == 'SELL' and o['symbol'] == sym for o in orders_queue):
                    orders_queue.append({'type': 'SELL', 'symbol': sym, 'reason': "Zombie"})
                holdings_to_sell.append(sym); continue
            if not check_regime(exec_date, sym, close, benchmarks_ma):
                if not any(o['type'] == 'SELL' and o['symbol'] == sym for o in orders_queue):
                    orders_queue.append({'type': 'SELL', 'symbol': sym, 'reason': "Regime Fail"})
                holdings_to_sell.append(sym); continue

        active_holdings = [
            s for s in positions 
            if s not in holdings_to_sell 
            and not any(o['type'] == 'SELL' and o['symbol'] == s for o in orders_queue)
        ]
        
        # [OPT-08] 加入最低分數門檻篩選
        candidates = [s for s in scores.loc[exec_date].dropna().sort_values(ascending=False).index 
                      if s not in positions and check_regime(exec_date, s, close, benchmarks_ma)
                      and (s not in cooldown_dict or exec_date > cooldown_dict[s])
                      and scores.loc[exec_date, s] >= MIN_SCORE_THRESHOLD]
        
        # [V18.07] VIX Boost: VIX 低時加碼 (A/B 驗證 CAGR+116pp, MaxDD -49.39% < -50% 底線)
        vix_scaler = 0.4 if curr_vix > 40 else 0.7 if curr_vix > 30 else 1.0 if curr_vix > 20 else 1.15 if curr_vix > 15 else 1.3
        # [OPT-06] 先更新所有持倉 current_price 再算 total_eq
        for sym_upd, pos_upd in positions.items():
            if sym_upd in close.columns and not pd.isna(close.loc[exec_date, sym_upd]):
                pos_upd.current_price = close.loc[exec_date, sym_upd]
        total_eq = cash + sum(p.market_value for p in positions.values())

        # --- [FIX_12] Macro Kill Switch: SPY 或 QQQ 在 MA200 下方 = 禁止開倉 ---
        macro_bearish = False
        if spy_ma200 is not None and exec_date in spy_ma200.index and not pd.isna(spy_ma200.loc[exec_date]):
            if close.loc[exec_date, 'SPY'] < spy_ma200.loc[exec_date]:
                macro_bearish = True
        if qqq_ma200 is not None and exec_date in qqq_ma200.index and not pd.isna(qqq_ma200.loc[exec_date]):
            if close.loc[exec_date, 'QQQ'] < qqq_ma200.loc[exec_date]:
                macro_bearish = True
        if macro_bearish:
            candidates = []

        # [V18.05] 動態倉位：排名 #1 的標的 40%，其餘各 30% (A/B 驗證 CAGR+100pp)
        def get_pos_size(rank):
            return total_eq * 0.40 * vix_scaler if rank == 0 else total_eq * 0.30 * vix_scaler
        proj = list(active_holdings)
        
        def is_allowed(cand): return True if curr_vix < 25.0 else sum(1 for x in proj if get_sector(x)==get_sector(cand)) < 2

        while active_holdings and candidates:
            active_holdings.sort(key=lambda x: scores.loc[exec_date, x] if not pd.isna(scores.loc[exec_date, x]) else -999)
            worst = active_holdings[0]
            # [CR-09] CRYPTO_SPOT 用 MIN_HOLD=3，其餘用 MIN_HOLD=5
            min_hold = MIN_HOLD_DAYS_CRYPTO_SPOT if ASSET_MAP.get(worst, '') == 'CRYPTO_SPOT' else MIN_HOLD_DAYS
            if (exec_date - positions[worst].entry_date).days < min_hold: active_holdings.pop(0); continue
            
            valid_idx = next((i for i, c in enumerate(candidates) if is_allowed(c)), -1)
            if valid_idx == -1: break
            best = candidates[valid_idx]
            
            w_score = scores.loc[exec_date, worst] if not pd.isna(scores.loc[exec_date, worst]) else 0
            b_score = scores.loc[exec_date, best]
            v_hold = vol_20.loc[exec_date, worst] if not pd.isna(vol_20.loc[exec_date, worst]) else 0.0
            if b_score > w_score * min(2.0, 1.4 + v_hold*0.1) and b_score > w_score + 0.05:
                if not any(o['type'] == 'SELL' and o['symbol'] == worst for o in orders_queue):
                    orders_queue.append({'type': 'SELL', 'symbol': worst, 'reason': f"Swap to {best}"})
                if not any(o['type'] == 'BUY' and o['symbol'] == best for o in orders_queue):
                    orders_queue.append({'type': 'BUY', 'symbol': best, 'amount_usd': get_pos_size(0)})
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
                    orders_queue.append({'type': 'BUY', 'symbol': cand, 'amount_usd': get_pos_size(len(positions))})
                proj.append(cand)
                
        # 每日結算後，再次確保對列完美
        orders_queue = sanitize_queue(positions, orders_queue)
        # [OPT-07] 利息計算移到策略信號判斷後（更精確）
        if cash > 0: cash *= ((1 + 0.04) ** (1/365))
        state['last_processed_date'] = exec_date.strftime('%Y-%m-%d')

    state['cash'] = cash
    state['positions'] = {sym: pos.to_dict() for sym, pos in positions.items()}
    state['orders_queue'] = orders_queue
    state['cooldown_dict'] = {sym: d.strftime('%Y-%m-%d') for sym, d in cooldown_dict.items()}

    if not dry_run: save_state(state)

    total_eq = cash + sum(p.market_value for p in positions.values())
    latest_vix = vix_series.iloc[-1]
    # [CR_FIX_12 v2] Market status for TW 9PM schedule
    # TW 9PM: TW already closed -> NaN = real holiday
    #         US not yet open -> NaN = normal, NOT holiday
    # yfinance union index has today (TW/crypto data exists)
    # but SPY raw_close=NaN -> is_trading_day=False (expected!)
    def _market_status(ticker):
        tw_today = pd.Timestamp(today_utc)
        is_tw_market = (ticker == '^TWII')
        if tw_today in is_trading_day.index and ticker in is_trading_day.columns:
            val = is_trading_day.loc[tw_today, ticker]
            if pd.notna(val) and val:
                return "🟢 今日有交易"
            else:
                # TW: already closed, NaN = genuine holiday
                # US: not yet open, NaN = normal on weekdays
                if is_tw_market:
                    return "🛑 今日休市"
                else:
                    return "🟡 待開盤" if tw_today.weekday() < 5 else "🛑 休市"
        # Today not in index (all markets have no data)
        if tw_today.weekday() >= 5:
            return "🛑 休市"
        return "🛑 今日休市" if is_tw_market else "🟡 待開盤"

    tw_open = _market_status('^TWII')
    us_open = _market_status('SPY')

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
    # [FIX_12] 顯示 MA200 巨觀狀態
    _macro_bear = False
    if spy_ma200 is not None and len(spy_ma200.dropna()) > 0:
        if close['SPY'].iloc[-1] < spy_ma200.dropna().iloc[-1]: _macro_bear = True
    if qqq_ma200 is not None and len(qqq_ma200.dropna()) > 0:
        if close['QQQ'].iloc[-1] < qqq_ma200.dropna().iloc[-1]: _macro_bear = True
    macro_icon = "🔴 MA200↓ 禁止開倉" if _macro_bear else "🟢 允許開倉"
    msg += f"\n🌍 巨觀防禦：{macro_icon}"
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
        msg += "\U0001F7E2 \u3010\u8cb7\u5165\u6307\u4ee4\u3011(\u8acb\u65bc\u958b\u76e4\u8cb7\u5165)\n"
        for b in buys:
            sym = b['symbol']
            sector = get_sector(sym)
            params = SECTOR_PARAMS.get(sector, SECTOR_PARAMS['DEFAULT'])
            stop_pct = params['stop']
            pct_str = str(int(stop_pct * 100))
            alloc_str = str(round(b['amount_usd'] / total_eq * 100))
            if 'TW' in sector:
                curr_p_usd = close[sym].iloc[-1] if sym in close.columns and not pd.isna(close[sym].iloc[-1]) else 0
                est_stop_ntd = curr_p_usd * (1 - stop_pct) * latest_twd_rate if curr_p_usd > 0 else 0
                msg += "\U0001F4B0 \u8cb7\u5165 " + sym + "\n"
                msg += "   \u76ee\u6a19\u4f54\u6bd4: " + alloc_str + "% \u7e3d\u8cc7\u91d1\n"
                msg += "   \U0001F4F1 \u53e3\u888b\u8b49\u5238 \u2192 \u79fb\u52d5\u505c\u5229\u505c\u640d\u55ae\uff1a\n"
                msg += "   \u2460 \u56de\u6a94\u8d85\u904e(\u542b): " + pct_str + "%\n"
                msg += "   \u2461 \u505c\u640d\u50f9(\u542b): NT$" + str(int(est_stop_ntd)) + "  \u26a0\ufe0f\u7c97\u7565(\u660e\u665a\u66f4\u65b0\u7cbe\u78ba\u503c)\n"
                msg += "   \u2462 \u50f9\u683c: \u6574\u80a1\u2192\u5e02\u50f9 / \u96f6\u80a1\u2192\u8dcc\u505c\n"
                msg += "   \u2463 \u6709\u6548\u671f: ROD\n"
            elif 'CRYPTO' in sector:
                msg += "\U0001F4B0 \u8cb7\u5165 " + sym + "\n"
                msg += "   \u76ee\u6a19\u4f54\u6bd4: " + alloc_str + "% \u7e3d\u8cc7\u91d1\n"
                msg += "   \U0001F4F1 \u5e63\u5b89 \u2192 \u8ffd\u8e64\u6b62\u640d\uff1a\n"
                msg += "   \u2460 T/D(%): " + pct_str + "%\n"
                msg += "   \u2461 \u89f8\u767c\u65b9\u5f0f: \u5e02\u50f9\n"
            else:
                msg += "\U0001F4B0 \u8cb7\u5165 " + sym + "\n"
                msg += "   \u76ee\u6a19\u4f54\u6bd4: " + alloc_str + "% \u7e3d\u8cc7\u91d1\n"
                msg += "   \U0001F4F1 Firstrade \u2192 \u8ffd\u8e64\u505c\u640d\u50f9%\uff1a\n"
                msg += "   \u2460 \u8ffd\u8e64\u5024%: " + pct_str + "\n"
                msg += "   \u2461 \u6709\u6548\u671f: 90\u5929\n"
        msg += "--------------------\n"

    if positions:
        msg += "\U0001F6E1\ufe0f \u3010\u639b\u55ae\u8a08\u7b97\u5668 \u2705\u7cbe\u78ba\u5024\u3011\u76f4\u63a5\u7167\u8a2d\n"
        for sym, p in positions.items():
            params = p.get_params()
            stop_pct = params['stop']
            profit_ratio = (p.max_price - p.entry_price) / p.entry_price
            # 台股：用台幣原價算獲利比例才精確
            if 'TW' in p.sector and p.entry_price_twd is not None and p.max_price_twd is not None:
                profit_ratio = (p.max_price_twd - p.entry_price_twd) / p.entry_price_twd
            trail_pct = stop_pct
            for threshold, pct in sorted(params['trail'].items(), key=lambda x: x[0], reverse=True):
                if profit_ratio >= threshold:
                    trail_pct = pct
                    break
            if latest_vix > 30.0:
                trail_pct = min(trail_pct * 1.3, stop_pct)
            cur_trail_pct = trail_pct
            use_trail = trail_pct < stop_pct
            hard_price = p.entry_price * (1 - stop_pct)
            trail_price = p.max_price * (1 - cur_trail_pct)
            final_price = max(hard_price, trail_price)
            pct_str = str(int(cur_trail_pct * 100)) if use_trail else str(int(stop_pct * 100))
            profit_str = str(int(profit_ratio * 100))
            # NaN guard: yfinance 下載失敗時 entry/max price 可能為 NaN，跳過該檔避免 int(NaN) crash
            def _bad(v):
                try:
                    return v is None or (isinstance(v, float) and np.isnan(v))
                except Exception:
                    return True
            if _bad(p.entry_price) or _bad(p.max_price) or _bad(final_price):
                msg += "\u26a0\ufe0f " + sym + " \u8cc7\u6599\u66ab\u6642\u6293\u4e0d\u5230\uff0c\u7565\u904e\u672c\u8f2a\n"
                continue
            if 'TW' in p.sector:
                # 台股：優先用 entry_price_twd (精確台幣)，沒有才 fallback 匯率換算
                if p.entry_price_twd is not None:
                    entry_ntd = p.entry_price_twd
                    max_ntd = p.max_price_twd if p.max_price_twd else p.max_price * latest_twd_rate
                    final_ntd = entry_ntd * (1 - stop_pct) if not use_trail else max_ntd * (1 - cur_trail_pct)
                    final_ntd = max(entry_ntd * (1 - stop_pct), final_ntd)  # 取兩者較高
                else:
                    entry_ntd = p.entry_price * latest_twd_rate
                    max_ntd = p.max_price * latest_twd_rate
                    final_ntd = final_price * latest_twd_rate
                if _bad(entry_ntd) or _bad(max_ntd) or _bad(final_ntd):
                    msg += "\u26a0\ufe0f " + sym + " \u53f0\u5e63\u50f9\u683c\u8cc7\u6599\u7f3a\u5931\uff0c\u7565\u904e\u672c\u8f2a\n"
                    continue
                msg += "\U0001F4CC " + sym + " (\u53e3\u888b\u8b49\u5238)\n"
                msg += "   \u6210\u4ea4: NT$" + str(int(entry_ntd)) + " | \u6700\u9ad8: NT$" + str(int(max_ntd)) + "\n"
                if use_trail:
                    msg += "   \U0001F504 \u56de\u6a94: " + pct_str + "%  \u505c\u640d\u50f9: \u2705NT$" + str(int(final_ntd)) + "\n"
                    msg += "   (\u6700\u9ad8\u7372\u5229 " + profit_str + "%\uff0c\u5df2\u6536\u7dca | \u9700\u66f4\u65b0\u639b\u55ae!)\n"
                else:
                    msg += "   \u56de\u6a94: " + pct_str + "%  \u505c\u640d\u50f9: \u2705NT$" + str(int(final_ntd)) + "\n"
            elif 'CRYPTO' in p.sector:
                msg += "\U0001F4CC " + sym + " (\u5e63\u5b89)\n"
                msg += "   \u6210\u4ea4: $" + ("%.4f" % p.entry_price) + " | \u6700\u9ad8: $" + ("%.4f" % p.max_price) + "\n"
                if use_trail:
                    msg += "   \U0001F504 T/D: " + pct_str + "%  \u89f8\u767c\u50f9: \u2705$" + ("%.4f" % final_price) + "\n"
                    msg += "   (\u6700\u9ad8\u7372\u5229 " + profit_str + "%\uff0c\u5df2\u6536\u7dca | \u9700\u66f4\u65b0\u639b\u55ae!)\n"
                else:
                    msg += "   T/D: " + pct_str + "%  \u89f8\u767c\u50f9: \u2705$" + ("%.4f" % final_price) + "\n"
            else:
                msg += "\U0001F4CC " + sym + " (Firstrade)\n"
                msg += "   \u6210\u4ea4: $" + ("%.2f" % p.entry_price) + " | \u6700\u9ad8: $" + ("%.2f" % p.max_price) + "\n"
                if use_trail:
                    msg += "   \U0001F504 \u8ffd\u8e64\u5024: " + pct_str + "%  \u89f8\u767c\u50f9: \u2705$" + ("%.2f" % final_price) + "\n"
                    msg += "   (\u6700\u9ad8\u7372\u5229 " + profit_str + "%\uff0c\u5df2\u6536\u7dca | \u9700\u66f4\u65b0\u639b\u55ae!)\n"
                else:
                    msg += "   \u8ffd\u8e64\u5024: " + pct_str + "%  \u89f8\u767c\u50f9: \u2705$" + ("%.2f" % final_price) + "\n"

    # [ALLOC_CHECK] \u5009\u4f4d\u914d\u7f6e\u6aa2\u67e5\uff08\u4f9d\u52d5\u80fd\u6392\u540d\u6a19\u76ee\u6a19\u4f54\u6bd4 + \u5be6\u969b\u4f54\u6bd4 + \u504f\u96e2\u5ea6\uff09
    if positions and total_eq > 0:
        try:
            # \u7528\u6700\u65b0\u4ea4\u6613\u65e5 + \u91cd\u7b97 vix_scaler\uff08\u907f\u514d exec_date/vix_scaler \u672a\u5b9a\u7fa9\uff09
            latest_score_date = close.index[-1]
            _vs = 0.4 if latest_vix > 40 else 0.7 if latest_vix > 30 else 1.0 if latest_vix > 20 else 1.15 if latest_vix > 15 else 1.3
            ranked = []
            for sym_r, p_r in positions.items():
                sc = scores.loc[latest_score_date, sym_r] if (sym_r in scores.columns and latest_score_date in scores.index) else np.nan
                ranked.append((sym_r, p_r, sc if not pd.isna(sc) else -999))
            ranked.sort(key=lambda x: x[2], reverse=True)
            medals = ["\U0001F947", "\U0001F948", "\U0001F949"]  # \ud83e\udd47\ud83e\udd48\ud83e\udd49
            msg += "\n\U0001F4CA \u3010\u5009\u4f4d\u914d\u7f6e\u6aa2\u67e5\u3011(\u4f9d\u52d5\u80fd\u6392\u540d)\n"
            msg += f"   VIX \u52a0\u78bc: {_vs:.2f}x\n"
            for idx, (sym_r, p_r, _) in enumerate(ranked):
                base_target = 0.40 if idx == 0 else 0.30
                target_with_vix = base_target * _vs * 100
                actual_pct = (p_r.market_value / total_eq) * 100 if total_eq > 0 else 0
                deviation = actual_pct - target_with_vix
                medal = medals[idx] if idx < 3 else "\u2796"
                dev_icon = "\U0001F7E2" if abs(deviation) < 5 else ("\U0001F7E1" if abs(deviation) < 10 else "\U0001F534")
                msg += f"{medal} #{idx+1} {sym_r}\n"
                msg += f"   \u76ee\u6a19: {int(round(target_with_vix))}% | \u5be6\u969b: {int(round(actual_pct))}% | {dev_icon} \u504f\u96e2: {deviation:+.1f}pp\n"
        except Exception as e:
            msg += f"\n\u26a0\ufe0f \u5009\u4f4d\u914d\u7f6e\u6aa2\u67e5\u5931\u6557: {e}\n"

    if not sells and not buys:
        msg += "\u2615 \u4eca\u65e5\u7121\u63db\u5009\u52d5\u4f5c\uff0c\u7dad\u6301\u9632\u7a7e\u639b\u55ae\u5373\u53ef"


    print(msg)
    if not dry_run and LINE_TOKEN and LINE_USER_ID:
        # [OPT-05] LINE 訊息長度檢查與分割（上限 5000 字）
        def send_line_messages(full_msg):
            MAX_LEN = 4900  # 保留 buffer
            msgs = []
            while len(full_msg) > MAX_LEN:
                split_idx = full_msg.rfind('\n', 0, MAX_LEN)
                if split_idx == -1: split_idx = MAX_LEN
                msgs.append(full_msg[:split_idx])
                full_msg = full_msg[split_idx:].lstrip('\n')
            if full_msg: msgs.append(full_msg)
            # LINE push API 每次最多 5 則訊息
            for i in range(0, len(msgs), 5):
                batch = [{'type': 'text', 'text': m} for m in msgs[i:i+5]]
                requests.post('https://api.line.me/v2/bot/message/push',
                              headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_TOKEN}'},
                              json={'to': LINE_USER_ID, 'messages': batch})
        try:
            send_line_messages(msg)
        except Exception as e: print(f"LINE 發送失敗: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="不儲存 state 且不發送 LINE")
    args = parser.parse_args()
    run_live(dry_run=args.dry_run)
