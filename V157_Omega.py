import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import requests
import ccxt
import base64
import time
import gc
from datetime import datetime, timedelta
import pytz

# 嘗試匯入 shioaji
sj = None
try:
    import shioaji as sj
except ImportError:
    pass

# ==========================================
# 1. 核心配置 (Secrets & Params)
# ==========================================
LINE_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER = os.getenv('LINE_USER_ID')

# Bitget
BG_KEY = os.getenv('BITGET_API_KEY')
BG_SECRET = os.getenv('BITGET_SECRET_KEY')
BG_PASS = os.getenv('BITGET_PASSWORD')

# 永豐金 (包含字串清洗)
def clean_env(key):
    val = os.getenv(key)
    return val.strip().replace('\n', '') if val else None

SJ_UID = clean_env('TWSTOCKS_API_KEY')
SJ_PASS = clean_env('TWSTOCKS_SECRET_KEY')
SJ_CERT_B64 = clean_env('SHIOAJI_PFX_BASE64')

# 回測參數 (用於即時計算夏普)
INITIAL_TWD = 3000000.0
USD_TWD_RATE = 32.5
CAPITAL_USDT = INITIAL_TWD / USD_TWD_RATE
START_DATE = '2020-11-01'
# 確保抓取到最新日期
END_DATE = datetime.now().strftime('%Y-%m-%d')
CASH_APY = 0.045
DAILY_INTEREST = (1 + CASH_APY)**(1/365) - 1

# 嚴格成本 (V117 標準)
SLIPPAGE_FEES = {
    'CRYPTO': {'fee': 0.0020, 'slip': 0.0050}, 
    'LEVERAGE': {'fee': 0.0010, 'slip': 0.0030}, 
    'TW_STOCK': {'fee': 0.001425, 'tax': 0.003, 'slip': 0.0020},
    'US_STOCK': {'fee': 0.0010, 'slip': 0.0015}
}

# 初始化 Bitget
exchange = None
crypto_name = "Manual"
try:
    if BG_KEY and BG_SECRET and BG_PASS:
        exchange = ccxt.bitget({'apiKey': BG_KEY, 'secret': BG_SECRET, 'password': BG_PASS, 'enableRateLimit': True})
        crypto_name = "Bitget"
except: pass

# 幣種對照
BITGET_MAP = {'PEPE': 'PEPE24478-USD', 'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD', 'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'FLOKI': 'FLOKI-USD', 'SHIB': 'SHIB-USD'}
REV_BITGET_MAP = {v: k for k, v in BITGET_MAP.items()}

# ==========================================
# 2. V157 完整戰力池 (74檔 全開)
# ==========================================
STRATEGIC_POOL = {
    'CRYPTO': [
        'BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'AVAX-USD', 
        'DOGE-USD', 'SHIB-USD', 'PEPE24478-USD', 'BONK-USD', 'WIF-USD',
        'SUI-USD', 'APT-USD', 'NEAR-USD', 'RENDER-USD', 'FET-USD',
        'INJ-USD', 'STX-USD', 'TIA-USD', 'SEI-USD', 'ONDO-USD',
        'PYTH-USD', 'JUP-USD', 'FLOKI-USD', 'LINK-USD', 'LTC-USD'
    ],
    'LEVERAGE': ['NVDL', 'TQQQ', 'SOXL', 'FNGU', 'TSLL', 'CONL', 'BITU', 'TECL', 'USD'],
    'STOCKS': [
        'NVDA', 'AMD', 'TSLA', 'SMCI', 'PLTR', 'MSTR', 'COIN', 
        'MU', 'ARM', 'AVGO', 'META', 'AMZN', 'NFLX', 'LLY', 'VRTX',
        'CRWD', 'PANW', 'ORCL', 'SHOP', 'UBER', 'MELI', 'COST', 'QCOM',
        'VRT', 'ANET', 'SNOW', 'TSM', 'ASML', 'AAPL', 'MSFT', 'GOOGL',
        '2330.TW', '2454.TW', '2382.TW', '3231.TW', '6669.TW', '3017.TW',
        '1519.TW', '1503.TW', '2317.TW'
    ]
}
ALL_TICKERS = list(set([t for sub in STRATEGIC_POOL.values() for t in sub])) + ['^GSPC', '^TWII']

# ==========================================
# 3. 模組功能 (通訊 & API)
# ==========================================
def send_line(msg):
    if not LINE_TOKEN or not LINE_USER: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": LINE_USER, "messages": [{"type": "text", "text": msg}]}
    requests.post(url, headers=headers, json=payload)

def get_bitget_symbol(yf_ticker):
    if yf_ticker in REV_BITGET_MAP: base = REV_BITGET_MAP[yf_ticker]
    else: base = yf_ticker.replace('-USD', '')
    return f"{base}/USDT"

def calculate_trade_impact(symbol, price, action):
    category = 'US_STOCK'
    if "-USD" in symbol: category = 'CRYPTO'
    elif symbol in STRATEGIC_POOL['LEVERAGE']: category = 'LEVERAGE'
    elif ".TW" in symbol: category = 'TW_STOCK'
    cfg = SLIPPAGE_FEES[category]
    fee_rate = cfg['fee'] + (cfg.get('tax', 0) if action == 'sell' else 0)
    return price * (1 + cfg['slip'] + fee_rate) if action == 'buy' else price * (1 - cfg['slip'] - fee_rate)

def sync_crypto(state):
    if not exchange: return state, "⚠️ Crypto API 未設定\n"
    try:
        exchange.timeout = 15000
        balance = exchange.fetch_balance()
        api_holdings = {}
        for coin, total in balance['total'].items():
            if total > 0:
                ticker = BITGET_MAP.get(coin, f"{coin}-USD")
                if ticker in STRATEGIC_POOL['CRYPTO']: api_holdings[ticker] = total
        
        log = ""
        new_assets = state['held_assets'].copy()
        
        for ticker, amt in api_holdings.items():
            if ticker not in new_assets:
                try:
                    sym = get_bitget_symbol(ticker)
                    trades = exchange.fetch_my_trades(sym, limit=1)
                    entry = trades[0]['price'] if trades else 0
                except: entry = 0
                new_assets[ticker] = {"entry": entry, "high": entry}
                log += f"➕ {crypto_name} 新增: {ticker}\n"
        
        for t in list(new_assets.keys()):
            if "-USD" in t and t not in api_holdings:
                del new_assets[t]
                log += f"➖ {crypto_name} 清倉: {t}\n"

        state['held_assets'] = new_assets
        return state, log if log else f"✅ {crypto_name} 同步完成\n"
    except Exception as e:
        return state, f"❌ Crypto 失敗: {str(e)[:20]}...\n"

def sync_tw_stock(state):
    """永豐金 API 同步 (修復版)"""
    if not (SJ_UID and SJ_PASS and SJ_CERT_B64): return state, "⚠️ 永豐金 API 未設定\n"
    if not sj: return state, "⚠️ 環境缺少 shioaji\n"

    log = ""
    # 強制實戰模式，使用絕對路徑
    api = sj.Shioaji(simulation=False)
    pfx_path = os.path.abspath("Sinopac.pfx")
    
    try:
        with open(pfx_path, "wb") as f: f.write(base64.b64decode(SJ_CERT_B64))
        
        # 登入檢查
        accounts = api.login(api_key=SJ_UID, secret_key=SJ_PASS)
        if not accounts: return state, "❌ 台股登入失敗: 帳密錯誤\n"
            
        api.activate_ca(ca_path=pfx_path, ca_passwd=SJ_PASS, person_id=SJ_UID)
        time.sleep(5) # 等待簽章
        
        positions = api.list_positions(unit=sj.constant.Unit.Share)
        tw_holdings = {}
        if positions:
            for p in positions:
                ticker = f"{p.code}.TW"
                if ticker in STRATEGIC_POOL['STOCKS']:
                    tw_holdings[ticker] = {"cost": float(p.price)}
        
        new_assets = state['held_assets'].copy()
        for t in list(new_assets.keys()):
            if ".TW" in t and t not in tw_holdings:
                del new_assets[t]
                log += f"➖ 台股清倉: {t}\n"
        
        for t, data in tw_holdings.items():
            if t not in new_assets:
                new_assets[t] = {"entry": data['cost'], "high": data['cost']}
                log += f"➕ 台股新增: {t}\n"
            else: new_assets[t]['entry'] = data['cost']

        state['held_assets'] = new_assets
        api.logout()
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, log if log else "✅ 台股同步完成\n"
    except Exception as e:
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, f"❌ 台股失敗: {str(e)[:30]}...\n"

# ==========================================
# 4. 歷史審計引擎 (V117 回測核心 - 為了算夏普值)
# ==========================================
def run_simulation(prices, opens):
    # 指標
    ma20 = prices.rolling(20).mean(); ma50 = prices.rolling(50).mean()
    mom_20 = prices.pct_change(20, fill_method=None)
    
    ma200_spy = prices['^GSPC'].rolling(200).mean()
    btc_col = 'BTC-USD'
    btc_ma100 = prices[btc_col].rolling(100).mean() if btc_col in prices else ma200_spy

    # 會計
    settled_cash = CAPITAL_USDT
    unsettled_q = [] 
    portfolio = {t: 0.0 for t in ALL_TICKERS if t not in ['^GSPC', '^TWII']}
    current_targets = []
    
    equity_curve = []
    pending_orders = []

    # 模擬迴圈 (這就是你覺得「長」的部分)
    for i in range(len(prices)):
        date = prices.index[i]
        if date < pd.Timestamp(START_DATE): continue
        
        # A. 結算
        new_c = 0; rem_q = []
        for amt, u_d in unsettled_q:
            if date >= u_d: new_c += amt
            else: rem_q.append((amt, u_d))
        unsettled_q = rem_q; settled_cash += new_c
        
        # B. 執行
        for order in pending_orders:
            sym = order['symbol']; action = order['action']
            if sym not in opens.columns: continue
            open_p = opens.loc[date, sym]
            
            # 零價與跳空保護
            if pd.isna(open_p) or open_p <= 1e-12: continue
            prev_c = prices.iloc[i-1][sym]
            is_lev = any(x in sym for x in STRATEGIC_POOL['LEVERAGE'])
            if action == 'buy' and open_p > prev_c * (1.03 if is_lev else 1.05): continue

            if action == 'buy' and settled_cash >= order['amount']:
                cost = calculate_trade_impact(sym, open_p, 'buy')
                portfolio[sym] += order['amount'] / cost
                settled_cash -= order['amount']
                if sym not in current_targets: current_targets.append(sym)
            elif action == 'sell' and portfolio[sym] > 0:
                net_p = calculate_trade_impact(sym, open_p, 'sell')
                proceeds = portfolio[sym] * net_p
                unsettled_q.append((proceeds, date + timedelta(days=1)))
                portfolio[sym] = 0.0
                if sym in current_targets: current_targets.remove(sym)
        pending_orders = []

        # C. 淨值
        stock_mv = sum([portfolio[t]*prices.loc[date,t] for t in portfolio if portfolio[t]>0 and not pd.isna(prices.loc[date,t])])
        total_eq = settled_cash + sum([x[0] for x in unsettled_q]) + stock_mv
        equity_curve.append(total_eq)

        # D. 決策 (V117)
        today_p = prices.iloc[i]
        spy_bull = today_p['^GSPC'] > ma200_spy.iloc[i]
        btc_bull = today_p[btc_col] > btc_ma100.iloc[i] if btc_col in prices else False
        
        tw_bull = False
        if '^TWII' in prices:
             m60tw = prices['^TWII'].rolling(60).mean().iloc[i]
             tw_bull = today_p['^TWII'] > m60tw if not pd.isna(m60tw) else False

        # 賣出
        for t in list(current_targets):
            curr_p = prices.loc[date, t]
            m50 = ma50.loc[date, t]
            if not pd.isna(m50) and curr_p < m50:
                pending_orders.append({'symbol': t, 'action': 'sell'})

        # 買入 (每 2 天)
        MAX_POS = 3
        if i % 2 == 0 and len(current_targets) < MAX_POS:
            if spy_bull or btc_bull or tw_bull:
                cands = []
                for t in portfolio:
                    if t in current_targets: continue
                    
                    # 市場分流
                    is_c = "-USD" in t; is_t = ".TW" in t
                    if is_c and not btc_bull: continue
                    if is_t and not tw_bull: continue
                    if not is_c and not is_t and not spy_bull: continue

                    if today_p[t] > ma20.loc[date, t] and today_p[t] > ma50.loc[date, t]:
                        sc = mom_20.loc[date, t]
                        if not pd.isna(sc) and sc > 0:
                            if any(x in t for x in STRATEGIC_POOL['LEVERAGE']): sc *= 1.4
                            cands.append((t, sc, today_p[t]))
                
                cands.sort(key=lambda x: x[1], reverse=True)
                for c in cands:
                    if len(current_targets) + len(pending_orders) < MAX_POS:
                        if settled_cash > 5000:
                            amt = settled_cash / (MAX_POS - len(current_targets))
                            pending_orders.append({'symbol': c[0], 'action': 'buy', 'amount': amt})

        if settled_cash > 0: settled_cash += settled_cash * DAILY_INTEREST

    return pd.Series(equity_curve, index=prices.index[prices.index >= pd.Timestamp(START_DATE)])

# ==========================================
# 5. 主程式
# ==========================================
def main():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    print(f"🚀 V157 Omega 完整版啟動...")
    
    # 1. 抓取數據
    try:
        # 分批下載以省記憶體 (Crypto / Stocks)
        # 這裡為了完整回測，必須抓長一點
        data = yf.download(ALL_TICKERS, start='2019-01-01', progress=False, auto_adjust=True, threads=False)
        prices = data['Close'].ffill()
        
        # 指標
        ma20 = prices.rolling(20).mean(); ma50 = prices.rolling(50).mean()
        ma200_spy = prices['^GSPC'].rolling(200).mean()
        btc_ma100 = prices['BTC-USD'].rolling(100).mean() if 'BTC-USD' in prices else ma200_spy
        mom_20 = prices.pct_change(20, fill_method=None)
        
        # 台股季線
        ma60_tw = prices['^TWII'].rolling(60).mean() if '^TWII' in prices else None

    except Exception as e:
        send_line(f"❌ 數據錯誤: {e}"); return

    # 2. 執行回測引擎 (算出夏普值 & 2025 績效)
    eq_curve = run_simulation(prices, data['Open'].ffill())
    
    # 績效計算
    ret_all = (eq_curve.iloc[-1] / INITIAL_TWD - 1) * 100
    mdd = ((eq_curve - eq_curve.cummax()) / eq_curve.cummax()).min() * 100
    daily_ret = eq_curve.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252)
    
    # 2025 專項
    eq_25 = eq_curve[eq_curve.index.year == 2025]
    if not eq_25.empty:
        ret_25 = (eq_25.iloc[-1] / eq_25.iloc[0] - 1) * 100
        mdd_25 = ((eq_25 - eq_25.cummax()) / eq_25.cummax()).min() * 100
    else:
        ret_25, mdd_25 = 0, 0

    # 3. 讀取狀態 & 同步 API
    state_file = 'state.json'
    if os.path.exists(state_file):
        with open(state_file, 'r') as f: state = json.load(f)
    else: state = {"held_assets": {}}

    state, c_log = sync_crypto(state)
    state, t_log = sync_tw_stock(state)
    
    # 4. 生成今日訊號
    today_p = prices.iloc[-1]
    spy_bull = today_p['^GSPC'] > ma200_spy.iloc[-1]
    btc_p = today_p['BTC-USD'] if 'BTC-USD' in today_p else 0
    btc_bull = btc_p > btc_ma100.iloc[-1]
    tw_bull = today_p['^TWII'] > ma60_tw.iloc[-1] if '^TWII' in prices else False
    
    report = f"🔱 V157 Omega 終極戰情\n📅 {now.strftime('%Y-%m-%d %H:%M')}\n"
    report += f"{c_log}{t_log}"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    
    report += f"📊 歷史審計 (2020-Now)\n"
    report += f"總回報: {ret_all:.0f}% | 夏普: {sharpe:.2f}\n"
    report += f"最大回撤: {mdd:.1f}%\n"
    report += f"2025績效: {ret_25:.1f}% (MDD {mdd_25:.1f}%)\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    
    report += f"📡 市場氣象站\n"
    report += f"🇺🇸 美股: {'🟢牛' if spy_bull else '🔴熊'}\n"
    report += f"🇹🇼 台股: {'🟢牛' if tw_bull else '🔴熊'}\n"
    report += f"₿  幣圈: {'🟢牛' if btc_bull else '🔴熊'}\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"

    # 持倉監控
    sell_alerts = []
    positions = 0
    if state['held_assets']:
        report += "💼 持倉監控：\n"
        for sym, info in list(state['held_assets'].items()):
            if sym not in today_p.index or pd.isna(today_p[sym]): continue
            positions += 1
            curr_p = today_p[sym]; entry_p = info.get('entry', 0)
            m50 = ma50[sym].iloc[-1]
            
            info['high'] = max(info.get('high', curr_p), curr_p)
            stop_line = info['high'] * 0.75
            
            pnl_str = f"({(curr_p-entry_p)/entry_p*100:+.1f}%)" if entry_p > 0 else ""
            ma50_str = f"{m50:.1f}" if not pd.isna(m50) else "N/A"
            report += f"🔸 {sym} {pnl_str}\n   現:{curr_p:.1f} | 止:{stop_line:.1f}\n"
            
            if not pd.isna(m50) and curr_p < m50: sell_alerts.append(f"❌ 賣出 {sym}: 破季線")
            elif curr_p < stop_line: sell_alerts.append(f"🟠 賣出 {sym}: 移動停利")
            elif entry_p > 0 and curr_p < entry_p * 0.85: sell_alerts.append(f"🔴 賣出 {sym}: 硬止損")

    if sell_alerts: report += "\n🚨 【緊急賣出】\n" + "\n".join(sell_alerts) + "\n"

    # 買入建議
    cands = []
    slots = 3 - positions
    if slots > 0 and (spy_bull or btc_bull or tw_bull):
        for t in [x for x in prices.columns if x not in ['^GSPC', '^TWII']]:
            if t in state['held_assets']: continue
            is_c = "-USD" in t; is_t = ".TW" in t
            if is_c and not btc_bull: continue
            if is_t and not tw_bull: continue
            if not is_c and not is_t and not spy_bull: continue
            
            p = today_p[t]
            if pd.isna(p) or pd.isna(ma50[t].iloc[-1]): continue
            
            if p > ma20[t].iloc[-1] and p > ma50[t].iloc[-1]:
                score = mom_20[t].iloc[-1]
                if pd.isna(score): continue
                if any(x in t for x in STRATEGIC_POOL['LEVERAGE']): score *= 1.4
                if score > 0: 
                    reason = "[槓桿🔥]" if score > 0.5 else "[強勢]"
                    cands.append((t, score, p, reason))
        
        cands.sort(key=lambda x: x[1], reverse=True)
        if cands:
            report += f"\n🚀 【進場建議】(剩 {slots} 席)\n"
            for i in range(min(slots, 3)):
                sym, sc, p, r = cands[i]
                report += f"💎 {sym} {r}\n   價:{p:.2f} | 止:{p*0.85:.1f}\n"

    send_line(report)
    with open('state.json', 'w') as f: json.dump(state, f, indent=4)

if __name__ == "__main__":
    main()
