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

# 嘗試匯入 shioaji
sj = None
try:
    import shioaji as sj
except ImportError:
    pass

# ==========================================
# 1. 核心配置 (從 GitHub Secrets 讀取)
# ==========================================
LINE_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER = os.getenv('LINE_USER_ID')

# Bitget API
BG_KEY = os.getenv('BITGET_API_KEY')
BG_SECRET = os.getenv('BITGET_SECRET_KEY')
BG_PASS = os.getenv('BITGET_PASSWORD')

# 永豐金 Secrets
SJ_UID = os.getenv('TWSTOCKS_API_KEY')
SJ_PASS = os.getenv('TWSTOCKS_SECRET_KEY')
SJ_CERT_B64 = os.getenv('SHIOAJI_PFX_BASE64')

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
# 2. V157 Omega 完整戰力池 (100% 對齊 V117/V157)
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

def get_bitget_symbol(yf_ticker):
    if yf_ticker in REV_BITGET_MAP: base = REV_BITGET_MAP[yf_ticker]
    else: base = yf_ticker.replace('-USD', '')
    return f"{base}/USDT"

def sync_crypto(state):
    """同步 Bitget 持倉"""
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
        
        # B. 移除
        for t in list(new_assets.keys()):
            if "-USD" in t and t not in api_holdings:
                del new_assets[t]
                log += f"➖ Bitget 清倉: {t}\n"

        state['held_assets'] = new_assets
        return state, log if log else f"✅ {crypto_name} 對帳完成\n"
    except Exception as e:
        return state, f"❌ Bitget 失敗: {str(e)[:30]}...\n"

def sync_tw_stock(state):
    """同步永豐金 (修復版)"""
    missing = []
    if not SJ_UID: missing.append("UID")
    if not SJ_PASS: missing.append("Pass")
    if not SJ_CERT_B64: missing.append("Cert")
    if missing: return state, f"⚠️ 永豐金未設定: 缺 {','.join(missing)}\n"
    if not sj: return state, f"⚠️ Shioaji 載入失敗\n"

    log = ""
    # 強制實戰模式，使用絕對路徑
    api = sj.Shioaji(simulation=False)
    pfx_path = os.path.abspath("Sinopac.pfx")
    
    try:
        with open(pfx_path, "wb") as f: f.write(base64.b64decode(SJ_CERT_B64))
        
        # 登入重試機制
        retry = 3
        accounts = []
        while retry > 0:
            try:
                accounts = api.login(api_key=SJ_UID, secret_key=SJ_PASS)
                break
            except:
                retry -= 1
                time.sleep(2)
        
        if not accounts: return state, "❌ 台股登入失敗\n"

        # 啟用憑證
        api.activate_ca(ca_path=pfx_path, ca_passwd=SJ_PASS, person_id=SJ_UID)
        time.sleep(5)
        
        # 抓取證券庫存
        stock_acc = None
        for acc in accounts:
            if acc.account_type == sj.constant.AccountType.Stock:
                stock_acc = acc
                break
        
        if not stock_acc: return state, "❌ 無證券帳戶\n"

        positions = api.list_positions(account=stock_acc, unit=sj.constant.Unit.Share)
        tw_holdings = {}
        if positions:
            for p in positions:
                ticker = f"{p.code}.TW"
                if ticker in STRATEGIC_POOL['STOCKS']:
                    tw_holdings[ticker] = {"cost": float(p.price)}
        
        new_assets = state['held_assets'].copy()
        
        # 清除不存在的台股
        for t in list(new_assets.keys()):
            if ".TW" in t and t not in tw_holdings:
                del new_assets[t]
                log += f"➖ 台股清倉: {t}\n"
        
        # 新增或更新台股
        for t, data in tw_holdings.items():
            if t not in new_assets:
                new_assets[t] = {"entry": data['cost'], "high": data['cost']}
                log += f"➕ 台股新增: {t}\n"
            else:
                new_assets[t]['entry'] = data['cost']

        state['held_assets'] = new_assets
        api.logout()
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, log if log else "✅ 台股對帳完成\n"

    except Exception as e:
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, f"❌ 台股錯誤: {str(e)[:30]}...\n"

# ==========================================
# 4. 主決策引擎 (100% 對齊 V157 回測邏輯)
# ==========================================
def main():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    print(f"🚀 V157 Omega 啟動...")
    
    try:
        # 抓取 300 天數據確保指標準確
        data = yf.download(ALL_TICKERS, period='300d', progress=False, auto_adjust=True)
        prices = data['Close'].ffill()
        
        # V157 核心指標：20MA / 50MA (季線)
        ma20 = prices.rolling(20).mean()
        ma50 = prices.rolling(50).mean()
        
        # 市場基準
        ma200_spy = prices['^GSPC'].rolling(200).mean()
        ma60_tw = prices['^TWII'].rolling(60).mean() if '^TWII' in prices else None
        
        btc_col = 'BTC-USD'
        btc_ma100 = prices['BTC-USD'].rolling(100).mean() if 'BTC-USD' in prices else ma200_spy
        
        mom_20 = prices.pct_change(20)
    except Exception as e:
        send_line(f"❌ 數據抓取失敗: {e}"); return

    # B. 狀態載入
    state_file = 'state.json'
    if os.path.exists(state_file):
        with open(state_file, 'r') as f: state = json.load(f)
    else: state = {"held_assets": {}}

    # C. 執行同步
    state, c_log = sync_crypto(state)
    state, t_log = sync_tw_stock(state)
    
    today_p = prices.iloc[-1]
    
    # 1. 市場氣象站 (格式對齊)
    spy_bull = today_p['^GSPC'] > ma200_spy.iloc[-1]
    btc_p = today_p['BTC-USD'] if 'BTC-USD' in today_p else 0
    btc_bull = btc_p > btc_ma100.iloc[-1]
    
    tw_bull = False
    if '^TWII' in prices and not pd.isna(ma60_tw.iloc[-1]):
        tw_bull = today_p['^TWII'] > ma60_tw.iloc[-1]
    
    report = f"🔱 V157 Omega 戰情室\n📅 {now.strftime('%Y-%m-%d %H:%M')}\n"
    report += f"{c_log}{t_log}"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    
    report += f"📡 市場氣象站\n"
    report += f"🇺🇸 美股: {'🟢' if spy_bull else '🔴'} (SPY > 200MA)\n"
    report += f"🇹🇼 台股: {'🟢' if tw_bull else '🔴'} (TWII > 60MA)\n"
    report += f"₿  幣圈: {'🟢' if btc_bull else '🔴'} (BTC > 100MA)\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"

    # 2. 持倉監控 (V157 出場邏輯)
    sell_alerts = []
    positions_count = 0
    if state['held_assets']:
        report += "💼 持倉監控：\n"
        for sym, info in list(state['held_assets'].items()):
            if sym not in today_p.index or pd.isna(today_p[sym]): continue
            positions_count += 1
            
            curr_p = today_p[sym]
            entry_p = info.get('entry', 0)
            m50 = ma50[sym].iloc[-1]
            
            # 更新最高價
            info['high'] = max(info.get('high', curr_p), curr_p)
            
            # V157 防線：25% 移動停利 / 15% 硬止損
            stop_line = info['high'] * 0.75
            hard_stop = entry_p * 0.85 if entry_p > 0 else 0
            final_stop = max(stop_line, hard_stop)
            
            pnl_str = f"({(curr_p-entry_p)/entry_p*100:+.1f}%)" if entry_p > 0 else ""
            ma50_str = f"{m50:.1f}" if not pd.isna(m50) else "N/A"
            
            report += f"🔸 {sym} {pnl_str}\n"
            report += f"   現價:{curr_p:.2f} | 止損:{final_stop:.1f}\n"
            
            # 出場條件
            if not pd.isna(m50) and curr_p < m50:
                sell_alerts.append(f"❌ 賣出 {sym} (破季線)")
            elif curr_p < stop_line:
                sell_alerts.append(f"🟠 賣出 {sym} (移動停利)")
            elif entry_p > 0 and curr_p < hard_stop:
                sell_alerts.append(f"🔴 賣出 {sym} (硬止損)")
    else:
        report += "💼 目前無持倉 (空手觀望)\n"

    if sell_alerts:
        report += "\n🚨 【緊急賣出指令】\n" + "\n".join(sell_alerts) + "\n"

    # 3. 買入建議 (V157 進場邏輯)
    cands = []
    slots = 3 - positions_count
    
    # 只要有空位 且 對應市場為牛市
    if slots > 0 and (spy_bull or btc_bull or tw_bull):
        for t in [x for x in prices.columns if x not in ['^GSPC', '^TWII']]:
            if t in state['held_assets']: continue
            
            # 市場過濾
            is_c = "-USD" in t; is_t = ".TW" in t
            if is_c and not btc_bull: continue
            if is_t and not tw_bull: continue
            if not is_c and not is_t and not spy_bull: continue
            
            p = today_p[t]
            if pd.isna(p) or pd.isna(ma20[t].iloc[-1]) or pd.isna(ma50[t].iloc[-1]): continue
            
            # V157 進場：必須同時站上 MA20 (月線) 與 MA50 (季線)
            if p > ma20[t].iloc[-1] and p > ma50[t].iloc[-1]:
                score = mom_20[t].iloc[-1]
                if pd.isna(score): continue
                
                is_lev = any(x in t for x in STRATEGIC_POOL['LEVERAGE'])
                # V157 槓桿加成 1.4x
                if is_lev: score *= 1.4
                
                if score > 0: 
                    # 格式對齊您的要求
                    reason = "[槓桿加成🔥]" if is_lev else "[強勢動能]"
                    if score > 0.5 and not is_lev: reason += "🔥"
                    cands.append((t, score, p, reason))
        
        cands.sort(key=lambda x: x[1], reverse=True)
        if cands:
            report += f"\n🚀 【進場建議】(剩 {slots} 席)\n"
            pos_size_pct = 33.3 
            for i, (sym, sc, p, r) in enumerate(cands[:slots]):
                stop = p * 0.85
                report += f"💎 {sym} {r}\n"
                report += f"   建議權重: {pos_size_pct}%\n"
                report += f"   建議價: {p:.2f} | 止損: {stop:.1f}\n"

    # F. 發送與歸檔
    send_line(report)
    with open('state.json', 'w') as f: json.dump(state, f, indent=4)
    print("✅ 任務完成。")

if __name__ == "__main__":
    main()
