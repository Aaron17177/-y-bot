import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import requests
import ccxt
import base64
import time
from datetime import datetime
import pytz

# 嘗試匯入 shioaji，並捕捉錯誤以便日誌顯示
sj = None
sj_error = None
try:
    import shioaji as sj
except ImportError as e:
    sj_error = str(e)

# ==========================================
# 1. 核心配置 (從 GitHub Secrets 讀取)
# ==========================================
LINE_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER = os.getenv('LINE_USER_ID')

# 幣安/Bitget 設定
BN_KEY = os.getenv('BINANCE_API_KEY'); BN_SECRET = os.getenv('BINANCE_SECRET_KEY')
BG_KEY = os.getenv('BITGET_API_KEY'); BG_SECRET = os.getenv('BITGET_SECRET_KEY'); BG_PASS = os.getenv('BITGET_PASSWORD')

# 永豐金 Secrets
SJ_UID = os.getenv('TWSTOCKS_API_KEY')
SJ_PASS = os.getenv('TWSTOCKS_SECRET_KEY')
SJ_CERT_B64 = os.getenv('SHIOAJI_PFX_BASE64')

# 初始化 Bitget 客戶端
exchange = None
if BG_KEY and BG_SECRET and BG_PASS:
    try:
        exchange = ccxt.bitget({
            'apiKey': BG_KEY,
            'secret': BG_SECRET,
            'password': BG_PASS,
            'enableRateLimit': True,
        })
    except Exception as e:
        print(f"⚠️ Bitget 連線初始化失敗: {e}")

# --- [修正點] 幣種代號對照表必須先定義 ---
BITGET_TO_YF = {
    'PEPE': 'PEPE24478-USD', 'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD',
    'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'FLOKI': 'FLOKI-USD', 'SHIB': 'SHIB-USD'
}
# 反向對照表 (現在可以正確生成了)
YF_TO_BITGET = {v: k for k, v in BITGET_TO_YF.items()}

# ==========================================
# 2. V157 Omega 完整戰力池 (100% 對齊)
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

# 包含 ^TWII 以便判斷台股趨勢
ALL_TICKERS = list(set([t for sub in STRATEGIC_POOL.values() for t in sub])) + ['^GSPC', '^TWII']

# ==========================================
# 3. 功能模組
# ==========================================
def send_line_push(message):
    """LINE Messaging API 推播"""
    if not LINE_TOKEN or not LINE_USER:
        print("❌ LINE 配置缺失，訊息內容：\n", message)
        return
    
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": LINE_USER, "messages": [{"type": "text", "text": message}]}
    try: requests.post(url, headers=headers, json=payload)
    except: pass

def get_bitget_symbol(yf_ticker):
    if yf_ticker in YF_TO_BITGET: base = YF_TO_BITGET[yf_ticker]
    else: base = yf_ticker.replace('-USD', '')
    return f"{base}/USDT"

def sync_holdings_with_bitget(state):
    """自動偵測 Bitget 持倉"""
    if not exchange: return state, "⚠️ Bitget API 未設定\n"
    
    try:
        exchange.timeout = 15000 
        balance = exchange.fetch_balance()
        api_holdings = {}
        for coin, total in balance['total'].items():
            if total > 0:
                ticker = BITGET_TO_YF.get(coin, f"{coin}-USD")
                if ticker in STRATEGIC_POOL['CRYPTO']: api_holdings[ticker] = total
        
        sync_log = ""
        new_assets = state['held_assets'].copy()
        
        # A. 更新/新增 API 偵測到的幣種
        for ticker, amount in api_holdings.items():
            if ticker in new_assets:
                # 已存在，保留原數據
                pass
            else:
                try:
                    symbol_ccxt = get_bitget_symbol(ticker)
                    trades = exchange.fetch_my_trades(symbol_ccxt, limit=1)
                    entry_p = trades[0]['price'] if trades else 0
                except: entry_p = 0 
                new_assets[ticker] = {"entry": entry_p, "high": entry_p}
                sync_log += f"➕ Bitget 新增: {ticker}\n"

        # B. 檢查賣出 (只移除 Crypto 部分)
        for t in list(new_assets.keys()):
            if "-USD" in t and t not in api_holdings:
                del new_assets[t]
                sync_log += f"➖ Bitget 清倉: {t}\n"
        
        state['held_assets'] = new_assets
        if not sync_log: sync_log = "✅ Bitget 對帳完成\n"
        return state, sync_log

    except Exception as e:
        return state, f"❌ Bitget 異常: {str(e)[:30]}...\n"

def sync_tw_stock(state):
    """同步永豐金持倉 (Shioaji)"""
    missing = []
    if not SJ_UID: missing.append("UID")
    if not SJ_PASS: missing.append("Pass")
    if not SJ_CERT_B64: missing.append("Cert")
    
    if missing: return state, f"⚠️ 永豐金未設定: 缺 {','.join(missing)}\n"
    if not sj: return state, f"⚠️ Shioaji 載入失敗: {sj_error}\n"

    log = ""
    api = sj.Shioaji()
    pfx_path = "temp_cert.pfx"
    
    try:
        with open(pfx_path, "wb") as f:
            f.write(base64.b64decode(SJ_CERT_B64))
        
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
            cost = data['cost']
            if t not in new_assets:
                new_assets[t] = {"entry": cost, "high": cost}
                log += f"➕ 台股新增: {t}\n"
            else:
                new_assets[t]['entry'] = cost

        state['held_assets'] = new_assets
        api.logout()
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, log if log else "✅ 台股對帳完成\n"

    except Exception as e:
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, f"❌ 台股異常: {str(e)[:30]}...\n"

# ==========================================
# 4. 主決策引擎
# ==========================================
def main():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    print(f"🚀 V157 Omega 啟動...")
    
    # 1. 抓取數據 (300d)
    try:
        data = yf.download(ALL_TICKERS, period='300d', progress=False, auto_adjust=True)
        prices = data['Close'].ffill()
        ma20 = prices.rolling(20).mean()
        ma50 = prices.rolling(50).mean() # 季線
        
        # 基準指標
        ma200_spy = prices['^GSPC'].rolling(200).mean()
        ma60_tw = prices['^TWII'].rolling(60).mean() if '^TWII' in prices else None
        btc_ma100 = prices['BTC-USD'].rolling(100).mean() if 'BTC-USD' in prices else ma200_spy
        
        mom_20 = prices.pct_change(20)
    except:
        send_line_push("❌ 數據抓取失敗"); return

    # 2. 讀取狀態
    state_file = 'state.json'
    if os.path.exists(state_file):
        with open(state_file, 'r') as f: state = json.load(f)
    else: state = {"held_assets": {}}

    # 3. 雙軌同步
    state, c_log = sync_holdings_with_bitget(state)
    state, t_log = sync_tw_stock(state)
    
    today_p = prices.iloc[-1]
    
    # 環境判定 (三市場獨立)
    spy_bull = today_p['^GSPC'] > ma200_spy.iloc[-1]
    btc_p = today_p['BTC-USD'] if 'BTC-USD' in today_p else 0
    btc_bull = btc_p > btc_ma100.iloc[-1]
    
    tw_bull = False
    if '^TWII' in prices and not pd.isna(ma60_tw.iloc[-1]):
        tw_bull = today_p['^TWII'] > ma60_tw.iloc[-1]
    
    report = f"🔱 V157 Omega 戰情室\n📅 {now.strftime('%Y-%m-%d %H:%M')}\n"
    report += f"{c_log}{t_log}"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    
    spy_icon = "🟢" if spy_bull else "🔴"
    tw_icon = "🟢" if tw_bull else "🔴"
    btc_icon = "🟢" if btc_bull else "🔴"
    
    report += f"📡 市場氣象站\n"
    report += f"🇺🇸 美股: {spy_icon} (SPY > 200MA)\n"
    report += f"🇹🇼 台股: {tw_icon} (TWII > 60MA)\n"
    report += f"₿  幣圈: {btc_icon} (BTC > 100MA)\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"

    # 4. 持倉監控
    sell_alerts = []
    positions_count = 0
    if state['held_assets']:
        report += "💼 持倉狀態：\n"
        for sym, info in list(state['held_assets'].items()):
            if sym not in today_p.index or pd.isna(today_p[sym]): continue
            positions_count += 1
            
            curr_p = today_p[sym]
            entry_p = info.get('entry', 0)
            m50 = ma50[sym].iloc[-1]
            
            # 更新最高價
            info['high'] = max(info.get('high', curr_p), curr_p)
            stop_line = info['high'] * 0.75
            
            # 損益
            pnl = (curr_p - entry_p)/entry_p*100 if entry_p > 0 else 0
            icon = "🔥" if pnl > 0 else "❄️"
            
            ma50_str = f"{m50:.1f}" if not pd.isna(m50) else "N/A"
            report += f"🔸 {sym} ({icon}{pnl:.1f}%)\n"
            report += f"   現:{curr_p:.2f} | 止:{stop_line:.1f}\n"
            
            if not pd.isna(m50) and curr_p < m50:
                sell_alerts.append(f"❌ 賣出 {sym} (破季線)")
            elif curr_p < stop_line:
                sell_alerts.append(f"🟠 賣出 {sym} (移動停利)")
    else:
        report += "💼 目前無持倉 (空手觀望)\n"

    if sell_alerts:
        report += "\n🚨 【緊急賣出訊號】\n" + "\n".join(sell_alerts) + "\n"

    # 5. 買入建議
    cands = []
    slots = 3 - positions_count
    
    # 只要有空位且對應市場為牛市，就掃描
    if slots > 0 and (spy_bull or btc_bull or tw_bull):
        for t in [x for x in prices.columns if x not in ['^GSPC', '^TWII']]:
            if t in state['held_assets']: continue
            
            # 分市場過濾 (嚴格執行)
            is_crypto = "-USD" in t
            is_tw = ".TW" in t
            if is_crypto and not btc_bull: continue
            if is_tw and not tw_bull: continue
            if not is_crypto and not is_tw and not spy_bull: continue
            
            p = today_p[t]
            if pd.isna(p) or pd.isna(ma20[t].iloc[-1]) or pd.isna(ma50[t].iloc[-1]): continue
            
            # V157 進場條件：站上月線與季線
            if p > ma20[t].iloc[-1] and p > ma50[t].iloc[-1]:
                score = mom_20[t].iloc[-1]
                if pd.isna(score): continue
                
                is_lev = any(x in t for x in STRATEGIC_POOL['LEVERAGE'])
                if is_lev: score *= 1.4
                
                if score > 0: 
                    reason = "[槓桿加成🔥]" if is_lev else "[強勢動能]"
                    cands.append((t, score, p, reason))
        
        cands.sort(key=lambda x: x[1], reverse=True)
        if cands:
            report += f"\n🚀 【進場建議】(剩 {slots} 席)\n"
            pos_size_pct = 33.3 
            for i, (sym, sc, p, r) in enumerate(cands[:slots]):
                stop = p * 0.85
                report += f"💎 {sym} {r}\n"
                report += f"   建議權重: {pos_size_pct}%\n   建議價: {p:.2f} | 止損: {stop:.1f}\n"

    # 6. 發送與歸檔
    send_line_push(report)
    with open('state.json', 'w') as f: json.dump(state, f, indent=4)
    print("✅ 任務完成。")

if __name__ == "__main__":
    main()
