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

# 嘗試匯入 shioaji，避免本地測試環境沒有安裝時報錯
try:
    import shioaji as sj
except ImportError:
    sj = None

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
# 這裡對應您在 GitHub Secrets 的設定
SJ_API_KEY = os.getenv('SHIOAJI_UID')      # 您的身分證字號
SJ_SECRET_KEY = os.getenv('SHIOAJI_PASSWORD') # 您的交易密碼
SJ_CERT_B64 = os.getenv('SHIOAJI_PFX_BASE64') # 憑證 Base64 字串

# 初始化 Bitget
exchange = None
if BG_KEY and BG_SECRET and BG_PASS:
    try:
        exchange = ccxt.bitget({
            'apiKey': BG_KEY,
            'secret': BG_SECRET,
            'password': BG_PASS,
            'enableRateLimit': True,
        })
    except: pass

# Bitget 幣種對照 (處理 YF 代號差異)
BITGET_MAP = {
    'PEPE': 'PEPE24478-USD', 'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD',
    'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'FLOKI': 'FLOKI-USD', 'SHIB': 'SHIB-USD'
}
YF_TO_BITGET = {v: k for k, v in BITGET_TO_YF.items()}

# ==========================================
# 2. V157 戰力池
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
    if yf_ticker in YF_TO_BITGET: base = YF_TO_BITGET[yf_ticker]
    else: base = yf_ticker.replace('-USD', '')
    return f"{base}/USDT"

def sync_crypto(state):
    """同步 Bitget 持倉"""
    if not exchange: return state, "⚠️ Bitget API 未設定\n"
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
        
        # A. 新增
        for ticker, amt in api_holdings.items():
            if ticker not in new_assets:
                try:
                    sym = get_bitget_symbol(ticker)
                    trades = exchange.fetch_my_trades(sym, limit=1)
                    entry = trades[0]['price'] if trades else 0
                except: entry = 0
                new_assets[ticker] = {"entry": entry, "high": entry}
                log += f"➕ Bitget 新增: {ticker}\n"
        
        # B. 移除 (只檢查 Crypto)
        for t in list(new_assets.keys()):
            if "-USD" in t and t not in api_holdings:
                del new_assets[t]
                log += f"➖ Bitget 清倉: {t}\n"

        state['held_assets'] = new_assets
        return state, log if log else "✅ Bitget 對帳完成\n"
    except Exception as e:
        return state, f"❌ Bitget 錯誤: {str(e)[:30]}...\n"

def sync_tw_stock(state):
    """同步永豐金持倉 (使用官方標準流程)"""
    # 檢查是否具備所有登入要素
    if not (SJ_API_KEY and SJ_SECRET_KEY and SJ_CERT_B64):
        return state, "⚠️ 永豐金 API 未設定 (維持手動)\n"
    
    if not sj: return state, "⚠️ 環境缺少 shioaji 套件\n"

    log = ""
    # 初始化 API (simulation=False 為實盤模式，若只是查詢建議設為 True 測試)
    # 這裡我們設為 True 以確保安全，若要抓真實帳戶請改為 False
    api = sj.Shioaji(simulation=False) 
    pfx_path = "Sinopac.pfx" # 憑證檔名
    
    try:
        # 1. 還原憑證檔案 (因為 GitHub 只能存文字)
        with open(pfx_path, "wb") as f:
            f.write(base64.b64decode(SJ_CERT_B64))
        
        # 2. 登入
        # 根據您的範例：api_key 是身分證，secret_key 是密碼
        accounts = api.login(api_key=SJ_API_KEY, secret_key=SJ_SECRET_KEY)
        
        # 3. 啟用 CA (憑證簽章)
        # 根據範例：ca_passwd 是密碼，person_id 是身分證
        api.activate_ca(
            ca_path=pfx_path, 
            ca_passwd=SJ_SECRET_KEY, 
            person_id=SJ_API_KEY
        )
        
        # 4. 抓取庫存
        time.sleep(3) # 等待連線與資料同步
        positions = api.list_positions(unit=sj.constant.Unit.Share)
        
        tw_holdings = {}
        for p in positions:
            ticker = f"{p.code}.TW"
            if ticker in STRATEGIC_POOL['STOCKS']:
                tw_holdings[ticker] = {"cost": float(p.price)}
        
        new_assets = state['held_assets'].copy()
        
        # A. 移除
        for t in list(new_assets.keys()):
            if ".TW" in t and t not in tw_holdings:
                del new_assets[t]
                log += f"➖ 台股清倉: {t}\n"
        
        # B. 新增
        for t, data in tw_holdings.items():
            if t not in new_assets:
                new_assets[t] = {"entry": data['cost'], "high": data['cost']}
                log += f"➕ 台股新增: {t}\n"
            else:
                new_assets[t]['entry'] = data['cost']

        state['held_assets'] = new_assets
        
        # 5. 安全登出與清理
        api.logout()
        if os.path.exists(pfx_path): os.remove(pfx_path)
        
        return state, log if log else "✅ 台股對帳完成\n"

    except Exception as e:
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, f"❌ 台股錯誤: {str(e)[:40]}...\n"

# ==========================================
# 4. 主決策引擎 (V157 邏輯)
# ==========================================
def main():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    print(f"🚀 {now} 啟動 V157 Omega 實戰版...")

    # A. 數據
    try:
        data = yf.download(ALL_TICKERS, period='300d', progress=False, auto_adjust=True)
        prices = data['Close'].ffill()
        ma20 = prices.rolling(20).mean()
        ma50 = prices.rolling(50).mean() # 季線
        
        # V157 牛熊判斷
        sp500_ma200 = prices['^GSPC'].rolling(200).mean()
        # 台股季線
        ma60_tw = prices['^TWII'].rolling(60).mean() if '^TWII' in prices else None
        
        btc_col = 'BTC-USD'
        if btc_col in prices:
            btc_ma100 = prices[btc_col].rolling(100).mean()
        else:
            btc_ma100 = sp500_ma200 # Fallback
            
        mom_20 = prices.pct_change(20)
    except:
        send_line("❌ 數據抓取失敗"); return

    # B. 狀態
    state_file = 'state.json'
    if os.path.exists(state_file):
        with open(state_file, 'r') as f: state = json.load(f)
    else: state = {"held_assets": {}}

    # C. 同步
    state, c_log = sync_crypto(state)
    state, t_log = sync_tw_stock(state)
    
    report = f"🔱 V157 Omega 戰情室\n📅 {now.strftime('%Y-%m-%d %H:%M')}\n"
    report += f"{c_log}{t_log}"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    
    today_p = prices.iloc[-1]
    
    # V157 市場濾網
    is_crypto_bull = today_p['BTC-USD'] > btc_ma100.iloc[-1] if 'BTC-USD' in prices else False
    is_stock_bull = today_p['^GSPC'] > sp500_ma200.iloc[-1]
    
    tw_bull = False
    if '^TWII' in prices and not pd.isna(ma60_tw.iloc[-1]):
        tw_bull = today_p['^TWII'] > ma60_tw.iloc[-1]
    
    report += f"📡 市場: {'美股牛' if is_stock_bull else '美股熊'} | {'台股牛' if tw_bull else '台股熊'} | {'幣圈牛' if is_crypto_bull else '幣圈熊'}\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"

    # D. 賣出監控 (V157 邏輯)
    sell_alerts = []
    current_count = 0
    
    if state['held_assets']:
        report += "💼 持倉監控：\n"
        for sym, info in list(state['held_assets'].items()):
            if sym not in today_p.index or pd.isna(today_p[sym]): continue
            current_count += 1
            
            curr_p = today_p[sym]
            entry_p = info.get('entry', 0)
            m50 = ma50[sym].iloc[-1]
            
            # 更新 trailing_max
            info['high'] = max(info.get('high', curr_p), curr_p)
            trailing_max = info['high']
            
            pnl_str = f"({(curr_p-entry_p)/entry_p*100:+.1f}%)" if entry_p > 0 else ""
            ma50_str = f"{m50:.1f}" if not pd.isna(m50) else "N/A"
            
            report += f"🔸 {sym} {pnl_str}\n"
            report += f"   現價:{curr_p:.2f} | MA50:{ma50_str}\n"

            # 1. 趨勢保護 (跌破季線)
            if not pd.isna(m50) and curr_p < m50:
                sell_alerts.append(f"❌ 賣出 {sym}: 跌破季線")
            # 2. 硬止損 (-10%)
            elif entry_p > 0 and curr_p < entry_p * 0.90:
                sell_alerts.append(f"🔴 賣出 {sym}: 硬止損 10%")
            # 3. 獲利回吐 (高點回落 25%)
            elif trailing_max > 0 and curr_p < trailing_max * 0.75:
                sell_alerts.append(f"🟠 賣出 {sym}: 獲利回吐 25%")
    else:
        report += "💼 目前無持倉 (空手觀望)\n"
    
    if sell_alerts:
        report += "\n🚨 【緊急賣出指令】\n" + "\n".join(sell_alerts) + "\n"

    # E. 買入掃描 (V157: MAX_POS=3)
    MAX_POS = 3
    slots_left = MAX_POS - current_count
    
    # 只要有空位且對應市場為牛市
    if slots_left > 0 and (is_crypto_bull or is_stock_bull or tw_bull):
        cands = []
        for t in [x for x in prices.columns if x not in ['^GSPC', '^TWII']]:
            if t in state['held_assets']: continue
            
            # 分市場過濾
            is_crypto = "-USD" in t
            is_tw = ".TW" in t
            if is_crypto and not is_crypto_bull: continue
            if is_tw and not tw_bull: continue
            if not is_crypto and not is_tw and not is_stock_bull: continue
            
            p = today_p[t]
            if pd.isna(p) or pd.isna(ma20[t].iloc[-1]) or pd.isna(ma50[t].iloc[-1]): continue
            
            # V157 進場：站上月線與季線
            if p > ma20[t].iloc[-1] and p > ma50[t].iloc[-1]:
                score = mom_20[t].iloc[-1]
                if pd.isna(score): continue
                
                is_lev = any(x in t for x in STRATEGIC_POOL['LEVERAGE'])
                # V157 槓桿加分 1.4x
                if is_lev: score *= 1.4
                
                if score > 0: 
                    reason = "[槓桿加成🔥]" if is_lev else "[強勢動能]"
                    cands.append((t, score, p, reason))
        
        cands.sort(key=lambda x: x[1], reverse=True)
        
        if cands:
            report += f"\n🚀 【進場建議】(剩 {slots_left} 席)\n"
            pos_size_pct = 33.3 
            for i, (sym, sc, p, r) in enumerate(cands[:slots_left]):
                stop = p * 0.85
                report += f"💎 {sym} {r}\n"
                report += f"   建議權重: {pos_size_pct}%\n   建議價: {p:.2f} | 止損: {stop:.1f}\n"

    # F. 存檔與發送
    send_line(report)
    with open('state.json', 'w') as f: json.dump(state, f, indent=4)
    print("✅ 任務完成。")

if __name__ == "__main__":
    main()
