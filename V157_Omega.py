import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import requests
import ccxt
import base64
import time
import gc # 引入垃圾回收機制
from datetime import datetime
import pytz

# 嘗試匯入 shioaji
try:
    import shioaji as sj
except ImportError:
    sj = None

# ==========================================
# 1. 核心配置 & Secrets
# ==========================================
LINE_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER = os.getenv('LINE_USER_ID')

# Bitget
BG_KEY = os.getenv('BITGET_API_KEY')
BG_SECRET = os.getenv('BITGET_SECRET_KEY')
BG_PASS = os.getenv('BITGET_PASSWORD')

# 永豐金
SJ_UID = os.getenv('TWSTOCKS_API_KEY')
SJ_PASS = os.getenv('TWSTOCKS_SECRET_KEY')
SJ_CERT_B64 = os.getenv('SHIOAJI_PFX_BASE64')

# 初始化 Crypto 客戶端
exchange = None
crypto_name = "Manual"
if BG_KEY and BG_SECRET and BG_PASS:
    try:
        exchange = ccxt.bitget({'apiKey': BG_KEY, 'secret': BG_SECRET, 'password': BG_PASS})
        crypto_name = "Bitget"
    except: pass

# 幣種對照
BITGET_MAP = {
    'PEPE': 'PEPE24478-USD', 'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD',
    'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'FLOKI': 'FLOKI-USD', 'SHIB': 'SHIB-USD'
}
REV_BITGET_MAP = {v: k for k, v in BITGET_MAP.items()}

# ==========================================
# 2. V157 完整戰力池 (74檔)
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
# 3. 模組功能
# ==========================================
def send_line(msg):
    if not LINE_TOKEN or not LINE_USER: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": LINE_USER, "messages": [{"type": "text", "text": msg}]}
    requests.post(url, headers=headers, json=payload)

def get_crypto_symbol(yf_ticker):
    if yf_ticker in REV_BITGET_MAP: base = REV_BITGET_MAP[yf_ticker]
    else: base = yf_ticker.replace('-USD', '')
    return f"{base}/USDT"

def sync_crypto(state):
    """同步加密貨幣持倉"""
    if not exchange: return state, f"⚠️ Crypto API 未設定\n"
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
                    sym = get_crypto_symbol(ticker)
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
    """同步永豐金持倉"""
    if not (SJ_UID and SJ_PASS and SJ_CERT_B64): return state, "⚠️ 永豐金 API 未設定\n"
    if not sj: return state, "⚠️ 環境缺少 shioaji\n"

    log = ""
    api = sj.Shioaji()
    pfx_path = "temp_cert.pfx"
    
    try:
        with open(pfx_path, "wb") as f: f.write(base64.b64decode(SJ_CERT_B64))
        api.login(api_key=SJ_UID, secret_key=SJ_PASS)
        api.activate_ca(ca_path=pfx_path, ca_passwd=SJ_PASS, person_id=SJ_UID)
        time.sleep(2)
        
        positions = api.list_positions(unit=sj.constant.Unit.Share)
        tw_holdings = {}
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
        return state, f"❌ 台股失敗: {str(e)[:20]}...\n"

# ==========================================
# 5. 主決策引擎 (實戰核心 - 輕量穩定版)
# ==========================================
def main():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    print(f"🚀 V157 Omega 啟動...")
    
    # A. 抓取數據 (縮短週期並關閉多線程以防崩潰)
    try:
        data = yf.download(ALL_TICKERS, period='252d', progress=False, auto_adjust=True, threads=False)
        prices = data['Close'].ffill()
        
        # V157 核心指標
        ma20 = prices.rolling(20).mean()
        ma50 = prices.rolling(50).mean() # 季線
        
        ma200_spy = prices['^GSPC'].rolling(200).mean()
        
        # 台股季線
        tw_idx = '^TWII' if '^TWII' in prices else '^GSPC'
        ma60_tw = prices[tw_idx].rolling(60).mean()
        
        # 幣圈牛熊
        btc_ma100 = prices['BTC-USD'].rolling(100).mean() if 'BTC-USD' in prices else ma200_spy
        
        # 動能計算 (使用 fill_method=None 避免警告與錯誤)
        mom_20 = prices.pct_change(20, fill_method=None)
        
        # 手動清理記憶體
        del data
        gc.collect()
        
    except Exception as e:
        print(f"Error: {e}")
        send_line("❌ 數據抓取失敗: 記憶體溢出或網絡錯誤"); return

    # B. 狀態與同步
    state_file = 'state.json'
    if os.path.exists(state_file):
        with open(state_file, 'r') as f: state = json.load(f)
    else: state = {"held_assets": {}}

    state, c_log = sync_crypto(state)
    state, t_log = sync_tw_stock(state)
    
    # C. 簡易大盤夏普 (只算 SPY，避免全體計算崩潰)
    spy_ret = prices['^GSPC'].pct_change(fill_method=None).dropna()
    sharpe = (spy_ret.mean() / spy_ret.std()) * np.sqrt(252)
    
    # D. 報告生成
    report = f"🔱 V157 Omega 戰情室\n📅 {now.strftime('%Y-%m-%d %H:%M')}\n"
    report += f"{c_log}{t_log}"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    
    today_p = prices.iloc[-1]
    
    # 環境判定
    spy_bull = today_p['^GSPC'] > ma200_spy.iloc[-1]
    btc_bull = today_p['BTC-USD'] > btc_ma100.iloc[-1] if 'BTC-USD' in prices else False
    tw_bull = today_p[tw_idx] > ma60_tw.iloc[-1]
    
    report += f"📡 市場氣象 (SPY夏普: {sharpe:.2f})\n"
    report += f"🇺🇸 美股: {'🟢牛' if spy_bull else '🔴熊'} | 🇹🇼 台股: {'🟢牛' if tw_bull else '🔴熊'}\n"
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
            
            curr_p = today_p[sym]
            entry_p = info.get('entry', 0)
            m50 = ma50[sym].iloc[-1]
            
            info['high'] = max(info.get('high', curr_p), curr_p)
            stop_line = info['high'] * 0.75
            
            pnl = (curr_p - entry_p)/entry_p*100 if entry_p > 0 else 0
            icon = "🔥" if pnl > 0 else "❄️"
            
            ma50_str = f"{m50:.1f}" if not pd.isna(m50) else "N/A"
            report += f"🔸 {sym} ({icon}{pnl:.1f}%)\n"
            report += f"   現:{curr_p:.1f} | 止:{stop_line:.1f}\n"
            
            if curr_p < m50: sell_alerts.append(f"❌ 賣出 {sym} (破季線)")
            elif curr_p < stop_line: sell_alerts.append(f"🟠 賣出 {sym} (移動停利)")

    if sell_alerts:
        report += "\n🚨 【緊急賣出訊號】\n" + "\n".join(sell_alerts) + "\n"

    # 買入建議
    cands = []
    slots = 3 - positions
    
    if slots > 0 and (spy_bull or btc_bull or tw_bull):
        for t in [x for x in prices.columns if x not in ['^GSPC', '^TWII']]:
            if t in state['held_assets']: continue
            
            # 分市場過濾
            is_crypto = "-USD" in t
            is_tw = ".TW" in t
            if is_crypto and not btc_bull: continue
            if is_tw and not tw_bull: continue
            if not is_crypto and not is_tw and not spy_bull: continue
            
            p = today_p[t]
            if pd.isna(p) or pd.isna(ma50[t].iloc[-1]): continue
            
            # V117 進場：站上月線與季線
            if p > ma20[t].iloc[-1] and p > ma50[t].iloc[-1]:
                score = mom_20[t].iloc[-1]
                if pd.isna(score): continue
                
                is_lev = any(x in t for x in STRATEGIC_POOL['LEVERAGE'])
                if is_lev: score *= 1.4
                
                if score > 0: 
                    reason = "[槓桿加成]" if is_lev else "[強勢動能]"
                    if score > 0.5: reason += "🔥"
                    cands.append((t, score, p, reason))
        
        cands.sort(key=lambda x: x[1], reverse=True)
        if cands:
            report += f"\n🚀 【進場建議】(剩 {slots} 席)\n"
            for i, (sym, sc, p, r) in enumerate(cands[:slots]):
                stop = p * 0.85
                report += f"💎 {sym} {r}\n"
                report += f"   建議權重: 33% | 價:{p:.2f}\n"

    send_line(report)
    with open('state.json', 'w') as f: json.dump(state, f, indent=4)

if __name__ == "__main__":
    main()
