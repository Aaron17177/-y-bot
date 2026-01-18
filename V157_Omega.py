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
from datetime import datetime
import pytz

# 嘗試匯入 shioaji，增加環境容錯性
sj = None
try:
    import shioaji as sj
except ImportError:
    pass

# ==========================================
# 1. 核心配置與環境清洗 (防範 API 400 錯誤與 Secret 格式問題)
# ==========================================
def clean_env(key):
    """徹底清除環境變數中的隱形換行與空格"""
    val = os.getenv(key)
    if val:
        return val.strip().replace('\n', '').replace('\r', '').replace(' ', '')
    return None

LINE_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER = os.getenv('LINE_USER_ID')

# 交易所/券商配置
BG_KEY = clean_env('BITGET_API_KEY')
BG_SECRET = clean_env('BITGET_SECRET_KEY')
BG_PASS = clean_env('BITGET_PASSWORD')

SJ_UID = clean_env('TWSTOCKS_API_KEY')
SJ_PASS = clean_env('TWSTOCKS_SECRET_KEY')
SJ_CERT_B64 = clean_env('SHIOAJI_PFX_BASE64')

# 初始化 Bitget 客戶端
exchange = None
if BG_KEY and BG_SECRET and BG_PASS:
    try:
        exchange = ccxt.bitget({
            'apiKey': BG_KEY, 'secret': BG_SECRET, 'password': BG_PASS, 'enableRateLimit': True
        })
    except: pass

# 幣種與 YFinance 對照
BITGET_TO_YF = {
    'PEPE': 'PEPE24478-USD', 'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD',
    'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'FLOKI': 'FLOKI-USD', 'SHIB': 'SHIB-USD'
}
YF_TO_BITGET = {v: k for k, v in BITGET_TO_YF.items()}

# ==========================================
# 2. V157 完整戰力池 (74 檔)
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

# [重要 Bug 修復] 幣圈代理人名單：即使是美股代號，也必須嚴格跟隨幣圈牛熊線
CRYPTO_PROXIES = ['BITU', 'CONL', 'MSTR', 'COIN']

ALL_TICKERS = list(set([t for sub in STRATEGIC_POOL.values() for t in sub])) + ['^GSPC', '^TWII']

# ==========================================
# 3. 模組功能 (API 同步與風控)
# ==========================================
def send_line(msg):
    if not LINE_TOKEN or not LINE_USER: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": LINE_USER, "messages": [{"type": "text", "text": msg}]}
    requests.post(url, headers=headers, json=payload)

def sync_crypto(state):
    """同步 Bitget 持倉"""
    if not exchange: return state, "⚠️ Bitget 未設定\n"
    try:
        balance = exchange.fetch_balance()
        api_holdings = {}
        for coin, total in balance['total'].items():
            if total > 0:
                ticker = BITGET_TO_YF.get(coin, f"{coin}-USD")
                if ticker in STRATEGIC_POOL['CRYPTO']: api_holdings[ticker] = total
        
        log = ""
        new_assets = state['held_assets'].copy()
        for ticker, amt in api_holdings.items():
            if ticker not in new_assets:
                new_assets[ticker] = {"entry": 0, "high": 0} 
                log += f"➕ Bitget 新增: {ticker}\n"
        for t in list(new_assets.keys()):
            if "-USD" in t and t not in api_holdings:
                del new_assets[t]; log += f"➖ Bitget 清倉: {t}\n"
        state['held_assets'] = new_assets
        return state, log if log else "✅ Bitget 對帳完成\n"
    except Exception as e:
        return state, f"❌ Bitget 異常: {str(e)[:30]}...\n"

def sync_tw_stock(state):
    """同步永豐金持倉 (徹底解決 400 與 139 崩潰問題)"""
    if not (SJ_UID and SJ_PASS and SJ_CERT_B64): return state, "⚠️ 台股 API 未設定\n"
    if not sj: return state, "⚠️ 環境無 shioaji 套件\n"
    
    api = sj.Shioaji(simulation=False)
    pfx_path = os.path.abspath("Sinopac.pfx")
    try:
        with open(pfx_path, "wb") as f: f.write(base64.b64decode(SJ_CERT_B64))
        
        # [防崩潰關鍵] fetch_contract=False 節省 90% 記憶體
        accounts = api.login(SJ_UID, SJ_PASS, fetch_contract=False)
        if not accounts: return state, "❌ 台股登入失敗\n"
        
        # [防 400 關鍵] 顯式搜尋證券帳戶
        stock_acc = next((a for a in accounts if a.account_type == sj.constant.AccountType.Stock), None)
        if not stock_acc: return state, "❌ 找不到證券帳戶\n"
        
        api.activate_ca(pfx_path, SJ_PASS, SJ_UID)
        time.sleep(3)
        
        positions = api.list_positions(stock_acc, unit=sj.constant.Unit.Share)
        tw_holdings = {f"{p.code}.TW": float(p.price) for p in (positions or []) if f"{p.code}.TW" in STRATEGIC_POOL['STOCKS']}
        
        new_assets = state['held_assets'].copy()
        log = ""
        for t in list(new_assets.keys()):
            if ".TW" in t and t not in tw_holdings:
                del new_assets[t]; log += f"➖ 台股清倉: {t}\n"
        for t, price in tw_holdings.items():
            if t not in new_assets:
                new_assets[t] = {"entry": price, "high": price}
                log += f"➕ 台股新增: {t}\n"
            else:
                new_assets[t]['entry'] = price
        
        state['held_assets'] = new_assets
        api.logout()
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, log if log else "✅ 台股對帳完成\n"
    except Exception as e:
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, f"❌ 台股失敗: {str(e)[:40]}...\n"

# ==========================================
# 4. 主決策引擎 (V157 邏輯完美對齊)
# ==========================================
def main():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    print(f"🚀 V164 Omega 啟動 (最終完美定案版)...")
    
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
        btc_ma100 = prices['BTC-USD'].rolling(100).mean() if 'BTC-USD' in prices else ma200_spy
        
        # 動能評分 (對齊 V117/V157)
        mom_20 = prices.pct_change(20, fill_method=None)
    except Exception as e:
        send_line(f"❌ 數據掃描失敗: {e}"); return

    # B. 狀態與同步
    state_file = 'state.json'
    if os.path.exists(state_file):
        with open(state_file, 'r') as f: state = json.load(f)
    else: state = {"held_assets": {}}

    state, c_log = sync_crypto(state)
    state, t_log = sync_tw_stock(state)
    
    today_p = prices.iloc[-1]
    
    # 市場氣象判定 (格式 100% 對齊要求)
    spy_bull = today_p['^GSPC'] > ma200_spy.iloc[-1]
    tw_bull = today_p['^TWII'] > ma60_tw.iloc[-1] if ma60_tw is not None else False
    btc_p = today_p['BTC-USD'] if 'BTC-USD' in today_p else 0
    btc_bull = btc_p > btc_ma100.iloc[-1]
    
    report = f"🔱 V157 Omega 戰情室\n📅 {now.strftime('%Y-%m-%d %H:%M')}\n"
    report += f"{c_log}{t_log}➖➖➖➖➖➖➖➖➖➖\n"
    
    report += f"📡 市場氣象站\n"
    report += f"🇺🇸 美股: {'🟢' if spy_bull else '🔴'} (SPY > 200MA)\n"
    report += f"🇹🇼 台股: {'🟢' if tw_bull else '🔴'} (TWII > 60MA)\n"
    report += f"₿  幣圈: {'🟢' if btc_bull else '🔴'} (BTC > 100MA)\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"

    # C. 持倉監控 (V157 出場邏輯)
    sell_alerts = []
    positions_count = 0
    if state['held_assets']:
        report += "💼 持倉監控：\n"
        for sym, info in list(state['held_assets'].items()):
            if sym not in today_p.index or pd.isna(today_p[sym]): continue
            positions_count += 1
            
            curr_p = today_p[sym]; entry_p = info.get('entry', 0)
            m50 = ma50[sym].iloc[-1]
            
            # 更新移動停利高點
            info['high'] = max(info.get('high', curr_p), curr_p)
            
            # V157 防線：25% 移動停利 / 15% 硬止損
            stop_line = info['high'] * 0.75
            hard_stop = entry_p * 0.85 if entry_p > 0 else 0
            final_stop = max(stop_line, hard_stop) if entry_p > 0 else stop_line
            
            pnl = f"({(curr_p-entry_p)/entry_p*100:+.1f}%)" if entry_p > 0 else ""
            report += f"🔸 {sym} {pnl}\n   現:{curr_p:.2f} | 止:{final_stop:.1f}\n"
            
            # [出場判定] 增加 Crypto Proxy 檢測
            is_btc_proxy = sym in CRYPTO_PROXIES
            if is_btc_proxy and not btc_bull:
                 sell_alerts.append(f"❌ 賣出 {sym}: 幣圈轉為熊市")
            elif not pd.isna(m50) and curr_p < m50: 
                sell_alerts.append(f"❌ 賣出 {sym}: 破季線")
            elif curr_p < stop_line: 
                sell_alerts.append(f"🟠 賣出 {sym}: 移動停利觸發")
            elif entry_p > 0 and curr_p < hard_stop: 
                sell_alerts.append(f"🔴 賣出 {sym}: 硬止損觸發")
    else:
        report += "💼 目前無持倉 (空手觀望)\n"

    if sell_alerts:
        report += "\n🚨 【緊急賣出訊號】\n" + "\n".join(sell_alerts) + "\n"

    # D. 買入建議與候補 (V157 進場條件：MA20 & MA50 + 代理人規則)
    cands = []
    for t in [x for x in prices.columns if x not in ['^GSPC', '^TWII']]:
        if t in state['held_assets']: continue
        
        is_c = "-USD" in t
        is_t = ".TW" in t
        is_btc_proxy = t in CRYPTO_PROXIES

        # [V164 修正] 嚴格資產分類濾網
        if is_btc_proxy:
            if not spy_bull or not btc_bull: continue # BITU/MSTR 雙牛才進
        elif is_c:
            if not btc_bull: continue
        elif is_t:
            if not tw_bull: continue
        else:
            if not spy_bull: continue
        
        p = today_p[t]
        if pd.isna(p) or pd.isna(ma50[t].iloc[-1]): continue
        
        # V157 入場門檻：必須站上 MA20 與 MA50
        if p > ma20[t].iloc[-1] and p > ma50[t].iloc[-1]:
            score = mom_20[t].iloc[-1]
            if pd.isna(score) or score <= 0: continue
            
            # V157 槓桿加成 1.4x
            is_lev = any(x in t for x in STRATEGIC_POOL['LEVERAGE'])
            if is_lev: score *= 1.4
            
            reason = "[槓桿加成🔥]" if is_lev else "[強勢動能]"
            cands.append((t, score, p, reason))
    
    cands.sort(key=lambda x: x[1], reverse=True)
    slots = 3 - positions_count
    
    if slots > 0 and cands:
        report += f"\n🚀 【進場建議】(剩 {slots} 席)\n"
        for i in range(min(slots, len(cands))):
            sym, sc, p, r = cands[i]
            report += f"💎 {sym} {r}\n"
            report += f"   建議權重: 33.3%\n   建議價: {p:.2f} | 止損: {p*0.85:.1f}\n"
        
        # 第四名候補顯示
        if len(cands) > slots:
            sym4, sc4, p4, r4 = cands[slots]
            report += f"\n💡 候補觀察 (第 4 名)\n🔹 {sym4} {r4}\n   參考價: {p4:.2f} | 止損: {p4*0.85:.1f}\n"

    # E. 存檔與推播
    send_line(report)
    with open('state.json', 'w') as f: json.dump(state, f, indent=4)
    print("✅ 任務執行圓滿成功。")

if __name__ == "__main__":
    main()
