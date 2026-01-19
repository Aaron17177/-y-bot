import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import requests
import ccxt
import time
import gc
import traceback
from datetime import datetime, timedelta
import pytz

# ==========================================
# 1. 核心配置與環境清洗
# ==========================================
def clean_env(key):
    val = os.getenv(key)
    if val:
        return val.strip().replace('\n', '').replace('\r', '').replace(' ', '')
    return None

LINE_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER = os.getenv('LINE_USER_ID')

# Bitget API
BG_KEY = clean_env('BITGET_API_KEY')
BG_SECRET = clean_env('BITGET_SECRET_KEY')
BG_PASS = clean_env('BITGET_PASSWORD')

# ⚠️ 已移除永豐金 API 設定，改為純訊號模式

# 初始化 Bitget
exchange = None
crypto_name = "Manual"
try:
    if BG_KEY and BG_SECRET and BG_PASS:
        exchange = ccxt.bitget({
            'apiKey': BG_KEY, 'secret': BG_SECRET, 'password': BG_PASS, 'enableRateLimit': True
        })
        crypto_name = "Bitget"
except: pass

# 幣種對照
BITGET_MAP = {'PEPE': 'PEPE24478-USD', 'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD', 'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'FLOKI': 'FLOKI-USD', 'SHIB': 'SHIB-USD'}
REV_BITGET_MAP = {v: k for k, v in BITGET_MAP.items()}

# ==========================================
# 2. V157 完整戰力池 (台股/美股/幣圈全保留)
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
        # 台股完整保留
        '2330.TW', '2454.TW', '2382.TW', '3231.TW', '6669.TW', '3017.TW',
        '1519.TW', '1503.TW', '2317.TW'
    ]
}

# 代理人名單
CRYPTO_PROXIES = ['BITU', 'CONL', 'MSTR', 'COIN']

ALL_TICKERS = list(set([t for sub in STRATEGIC_POOL.values() for t in sub])) + ['^GSPC', '^TWII']

# ==========================================
# 3. 模組功能 (通訊 & Bitget API)
# ==========================================
def send_line(msg):
    if not LINE_TOKEN or not LINE_USER: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": LINE_USER, "messages": [{"type": "text", "text": msg}]}
    for _ in range(3):
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code == 200: break
        except: time.sleep(2)

def get_bitget_symbol(yf_ticker):
    if yf_ticker in REV_BITGET_MAP: base = REV_BITGET_MAP[yf_ticker]
    else: base = yf_ticker.replace('-USD', '')
    return f"{base}/USDT"

def sync_crypto(state):
    """同步 Bitget 持倉"""
    if not exchange: return state, "⚠️ Bitget 未設定\n"
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
        
        # A. 更新
        for ticker, amt in api_holdings.items():
            if ticker not in new_assets:
                try:
                    sym = get_bitget_symbol(ticker)
                    trades = exchange.fetch_my_trades(sym, limit=1)
                    entry = trades[0]['price'] if trades else 0
                except: entry = 0
                new_assets[ticker] = {"entry": entry, "high": entry}
                log += f"➕ Bitget 新增: {ticker}\n"
        
        # B. 移除 (只針對 Crypto)
        for t in list(new_assets.keys()):
            if "-USD" in t and t not in api_holdings:
                del new_assets[t]
                log += f"➖ Bitget 清倉: {t}\n"

        state['held_assets'] = new_assets
        return state, log if log else "✅ Bitget 對帳完成\n"
    except Exception as e:
        return state, f"❌ Bitget 異常: {str(e)[:30]}...\n"

# ⚠️ 移除 sync_tw_stock 函式，改為手動維護台股持倉

# ==========================================
# 4. 主決策引擎 (V157 邏輯完美對齊)
# ==========================================
def main():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    print(f"🚀 V166 Omega (Stable) 啟動...")
    
    # A. 數據獲取 (threads=False 確保 GitHub Actions 穩定)
    try:
        data = yf.download(ALL_TICKERS, period='300d', progress=False, auto_adjust=True, threads=False)
        prices = data['Close'].ffill()
        del data; gc.collect()

        # V157 核心指標計算
        ma20 = prices.rolling(20).mean()
        ma50 = prices.rolling(50).mean() # 季線
        
        # 市場基準
        ma200_spy = prices['^GSPC'].rolling(200).mean()
        ma60_tw = prices['^TWII'].rolling(60).mean() if '^TWII' in prices else None
        
        btc_col = 'BTC-USD'
        btc_ma100 = prices['BTC-USD'].rolling(100).mean() if 'BTC-USD' in prices else ma200_spy
        
        mom_20 = prices.pct_change(20, fill_method=None)
    except Exception as e:
        send_line(f"❌ 數據下載失敗: {e}"); return

    # B. 狀態載入
    state_file = 'state.json'
    if os.path.exists(state_file):
        with open(state_file, 'r') as f: state = json.load(f)
    else: state = {"held_assets": {}}

    # C. 同步 (僅 Bitget)
    state, c_log = sync_crypto(state)
    
    today_p = prices.iloc[-1]
    
    # 1. 市場氣象站
    spy_bull = today_p['^GSPC'] > ma200_spy.iloc[-1]
    btc_p = today_p['BTC-USD'] if 'BTC-USD' in today_p else 0
    btc_bull = btc_p > btc_ma100.iloc[-1]
    
    tw_bull = False
    if '^TWII' in prices and not pd.isna(ma60_tw.iloc[-1]):
        tw_bull = today_p['^TWII'] > ma60_tw.iloc[-1]
    
    report = f"🔱 V157 Omega 戰情室\n📅 {now.strftime('%Y-%m-%d %H:%M')}\n"
    report += f"{c_log}"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    
    report += f"📡 市場氣象站\n"
    report += f"🇺🇸 美股: {'🟢' if spy_bull else '🔴'} (SPY > 200MA)\n"
    report += f"🇹🇼 台股: {'🟢' if tw_bull else '🔴'} (TWII > 60MA)\n"
    report += f"₿  幣圈: {'🟢' if btc_bull else '🔴'} (BTC > 100MA)\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"

    # 2. 持倉監控 (包含台股)
    sell_alerts = []
    positions = 0
    if state['held_assets']:
        report += "💼 持倉監控：\n"
        for sym, info in list(state['held_assets'].items()):
            # 確保價格存在
            if sym not in today_p.index or pd.isna(today_p[sym]): continue
            positions += 1
            
            curr_p = today_p[sym]; entry_p = info.get('entry', 0)
            m50 = ma50[sym].iloc[-1]
            
            # 更新最高價
            info['high'] = max(info.get('high', curr_p), curr_p)
            
            # V157 防線
            stop_line = info['high'] * 0.75
            hard_stop = entry_p * 0.85 if entry_p > 0 else 0
            final_stop = max(stop_line, hard_stop) if entry_p > 0 else stop_line
            
            pnl_str = f"({(curr_p-entry_p)/entry_p*100:+.1f}%)" if entry_p > 0 else ""
            ma50_str = f"{m50:.1f}" if not pd.isna(m50) else "N/A"
            report += f"🔸 {sym} {pnl_str}\n   現:{curr_p:.2f} | 止:{final_stop:.1f}\n"
            
            # 出場邏輯
            is_proxy = sym in CRYPTO_PROXIES
            if is_proxy and not btc_bull: sell_alerts.append(f"❌ 賣出 {sym}: 幣圈轉熊")
            elif not pd.isna(m50) and curr_p < m50: sell_alerts.append(f"❌ 賣出 {sym}: 破季線")
            elif curr_p < stop_line: sell_alerts.append(f"🟠 賣出 {sym}: 移動停利")
            elif entry_p > 0 and curr_p < hard_stop: sell_alerts.append(f"🔴 賣出 {sym}: 硬止損")
    else: report += "💼 目前無持倉 (空手觀望)\n"

    if sell_alerts: report += "\n🚨 【緊急賣出訊號】\n" + "\n".join(sell_alerts) + "\n"

    # 3. 買入建議與候補 (V157 邏輯)
    cands = []
    slots = 3 - positions
    if slots > 0 and (spy_bull or btc_bull or tw_bull):
        for t in [x for x in prices.columns if x not in ['^GSPC', '^TWII']]:
            if t in state['held_assets']: continue
            
            # 市場過濾
            is_c = "-USD" in t; is_t = ".TW" in t; is_proxy = t in CRYPTO_PROXIES
            if is_proxy:
                if not spy_bull or not btc_bull: continue
            elif is_c:
                if not btc_bull: continue
            elif is_t:
                if not tw_bull: continue
            else:
                if not spy_bull: continue
            
            p = today_p[t]
            if pd.isna(p) or pd.isna(ma50[t].iloc[-1]): continue
            
            # V157 進場：MA20 & MA50
            if p > ma20[t].iloc[-1] and p > ma50[t].iloc[-1]:
                score = mom_20[t].iloc[-1]
                if pd.isna(score) or score <= 0: continue
                
                is_lev = any(x in t for x in STRATEGIC_POOL['LEVERAGE'])
                if is_lev: score *= 1.4
                
                reason = "[槓桿🔥]" if is_lev else "[強勢]"
                cands.append((t, score, p, reason))
        
        cands.sort(key=lambda x: x[1], reverse=True)
        if cands:
            report += f"\n🚀 【進場建議】(剩 {slots} 席)\n"
            for i in range(min(slots, len(cands))):
                sym, sc, p, r = cands[i]
                report += f"💎 {sym} {r}\n   建議權重: 33.3%\n   建議價: {p:.2f} | 止損: {p*0.85:.1f}\n"
            
            # 顯示候補名單 (第四、第五名)
            if len(cands) > slots:
                sym4, sc4, p4, r4 = cands[slots]
                report += f"\n💡 候補觀察 (第 4 名)\n🔹 {sym4} {r4}\n   參考價: {p4:.2f} | 止損: {p4*0.85:.1f}\n"
            if len(cands) > slots + 1:
                sym5, sc5, p5, r5 = cands[slots+1]
                report += f"🔹 {sym5} {r5}\n   參考價: {p5:.2f} | 止損: {p5*0.85:.1f}\n"

    send_line(report)
    with open('state.json', 'w') as f: json.dump(state, f, indent=4)

if __name__ == "__main__":
    main()
