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

# 嘗試匯入 shioaji，若環境未安裝則跳過，避免報錯
try:
    import shioaji as sj
except ImportError:
    sj = None

# ==========================================
# 1. 核心配置 (從 GitHub Secrets 讀取)
# ==========================================
LINE_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER = os.getenv('LINE_USER_ID')

# Bitget API 配置
BG_KEY = os.getenv('BITGET_API_KEY')
BG_SECRET = os.getenv('BITGET_SECRET_KEY')
BG_PASS = os.getenv('BITGET_PASSWORD')

# 永豐金 (Shioaji) API 配置
# 對應 GitHub Secrets 變數名
SJ_UID = os.getenv('TWSTOCKS_API_KEY')      # 身分證字號
SJ_PASS = os.getenv('TWSTOCKS_SECRET_KEY')  # 交易密碼
SJ_CERT_B64 = os.getenv('SHIOAJI_PFX_BASE64') # Base64 憑證字串

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

# --- 幣種代號對照表 ---
BITGET_TO_YF = {
    'PEPE': 'PEPE24478-USD', 'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD',
    'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'FLOKI': 'FLOKI-USD', 'SHIB': 'SHIB-USD'
}
YF_TO_BITGET = {v: k for k, v in BITGET_TO_YF.items()}

# ==========================================
# 2. V157 Omega 完整戰力池
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

ALL_TICKERS = list(set([t for sub in STRATEGIC_POOL.values() for t in sub])) + ['^GSPC']

# ==========================================
# 3. 功能模組
# ==========================================
def send_line_push(message):
    """LINE Messaging API 推播"""
    if not LINE_TOKEN or not LINE_USER:
        print("❌ LINE 配置缺失，訊息內容：\n", message)
        return
    
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    payload = {
        "to": LINE_USER,
        "messages": [{"type": "text", "text": message}]
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"❌ LINE 發送失敗: {response.text}")
    except Exception as e:
        print(f"❌ LINE 連線異常: {e}")

def get_bitget_symbol(yf_ticker):
    if yf_ticker in YF_TO_BITGET: base = YF_TO_BITGET[yf_ticker]
    else: base = yf_ticker.replace('-USD', '')
    return f"{base}/USDT"

def sync_holdings_with_bitget(state):
    """自動偵測 Bitget 持倉"""
    if not exchange: return state, "⚠️ Bitget API 未設定，僅能手動同步持倉\n"
    
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
        
        # A. 更新/新增
        for ticker, amount in api_holdings.items():
            if ticker in new_assets:
                pass # 已存在，不覆蓋
            else:
                try:
                    symbol_ccxt = get_bitget_symbol(ticker)
                    trades = exchange.fetch_my_trades(symbol_ccxt, limit=1)
                    entry_p = trades[0]['price'] if trades else 0
                except: entry_p = 0 
                new_assets[ticker] = {"entry": entry_p, "high": entry_p}
                sync_log += f"➕ Bitget 新增: {ticker}\n"

        # B. 檢查賣出
        for ticker in list(new_assets.keys()):
            if "-USD" in ticker and ticker not in api_holdings:
                del new_assets[ticker]
                sync_log += f"➖ Bitget 清倉: {ticker}\n"
        
        # C. 非 Crypto 部分保留給台股同步處理
        
        state['held_assets'] = new_assets
        if not sync_log: sync_log = "✅ Bitget 對帳完成\n"
        return state, sync_log

    except Exception as e:
        err_msg = str(e)
        if "451" in err_msg or "restricted" in err_msg:
             return state, "⚠️ IP 被 Bitget 阻擋，切換至手動記帳模式。\n"
        return state, f"❌ Bitget 同步異常: {err_msg[:30]}...\n"

def sync_tw_stock(state):
    """同步永豐金持倉 (Shioaji)"""
    # 檢查是否具備所有登入要素
    if not (SJ_UID and SJ_PASS and SJ_CERT_B64):
        return state, "⚠️ 永豐金 API 未設定 (維持手動)\n"
    
    if not sj: return state, "⚠️ 環境缺少 shioaji 套件\n"

    log = ""
    api = sj.Shioaji()
    pfx_path = "temp_cert.pfx"
    
    try:
        # 1. 還原憑證
        with open(pfx_path, "wb") as f:
            f.write(base64.b64decode(SJ_CERT_B64))
        
        # 2. 登入
        api.login(api_key=SJ_UID, secret_key=SJ_PASS)
        # 啟動 CA (這是下單/查庫存必須的)
        api.activate_ca(ca_path=pfx_path, ca_passwd=SJ_PASS, person_id=SJ_UID)
        
        # 3. 抓庫存
        time.sleep(2) # 等待連線
        positions = api.list_positions(unit=sj.constant.Unit.Share)
        
        tw_holdings = {}
        for p in positions:
            ticker = f"{p.code}.TW"
            if ticker in STRATEGIC_POOL['STOCKS']:
                tw_holdings[ticker] = {
                    "qty": p.quantity,
                    "cost": float(p.price)
                }
        
        new_assets = state['held_assets'].copy()
        
        # A. 檢查賣出 (帳本有，但 API 沒有)
        for t in list(new_assets.keys()):
            if ".TW" in t and t not in tw_holdings:
                del new_assets[t]
                log += f"➖ 台股清倉: {t}\n"
        
        # B. 檢查買入 (API 有，更新帳本)
        for t, data in tw_holdings.items():
            cost = float(data['cost'])
            if t not in new_assets:
                new_assets[t] = {"entry": cost, "high": cost}
                log += f"➕ 台股偵測新增: {t} (均價 {cost})\n"
            else:
                # 更新成本 (如果加碼)
                new_assets[t]['entry'] = cost
                # high 保持不變，除非現在價格更高 (由後續 main 邏輯更新)

        state['held_assets'] = new_assets
        
        # 4. 安全登出與清理
        api.logout()
        if os.path.exists(pfx_path): os.remove(pfx_path)
        
        return state, log if log else "✅ 台股對帳完成\n"

    except Exception as e:
        if os.path.exists(pfx_path): os.remove(pfx_path)
        return state, f"❌ 台股同步失敗: {str(e)[:50]}...\n"

# ==========================================
# 4. 主決策引擎 (倉位建議優化版)
# ==========================================
def main():
    tz = pytz.timezone('Asia/Taipei')
    now = datetime.now(tz)
    print(f"🚀 {now} 啟動 V157 Omega 實戰掃描...")

    # A. 數據獲取
    try:
        data = yf.download(ALL_TICKERS, period='300d', progress=False, auto_adjust=True)
        prices = data['Close'].ffill()
        ma20 = prices.rolling(20).mean()
        ma50 = prices.rolling(50).mean()
        ma200_spy = prices['^GSPC'].rolling(200).mean()
        
        btc_ma100 = prices['BTC-USD'].rolling(100).mean() if 'BTC-USD' in prices else ma200_spy
        mom_20 = prices.pct_change(20, fill_method=None)
    except Exception as e:
        send_line_push(f"❌ 數據抓取失敗: {e}")
        return

    # B. 狀態載入
    state_file = 'state.json'
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r') as f: state = json.load(f)
        except: state = {"held_assets": {}}
    else: state = {"held_assets": {}}
    
    # C. 執行雙軌同步 (Bitget + 永豐金)
    state, bitget_log = sync_holdings_with_bitget(state)
    state, tw_log = sync_tw_stock(state)
    
    today_p = prices.iloc[-1]
    
    # 環境判定
    spy_p = today_p['^GSPC']
    spy_ma = ma200_spy.iloc[-1]
    spy_bull = spy_p > spy_ma
    
    btc_p = today_p['BTC-USD'] if 'BTC-USD' in today_p else 0
    btc_ma = btc_ma100.iloc[-1]
    btc_bull = btc_p > btc_ma
    
    # --- 報告表頭 ---
    report =  "【🔱 V157 Omega 戰情室】\n"
    report += f"📅 {now.strftime('%Y-%m-%d %H:%M')}\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    report += f"{bitget_log}{tw_log}"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    
    # 市場氣象站
    spy_icon = "🟢" if spy_bull else "🔴"
    btc_icon = "🟢" if btc_bull else "🔴"
    report += "📡 市場氣象站\n"
    report += f"🇺🇸 美股: {spy_icon} (SPY > 200MA)\n"
    if 'BTC-USD' in prices:
        report += f"₿  幣圈: {btc_icon} (BTC: {btc_p:.0f}/{btc_ma:.0f})\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"

    # D. 持倉監控
    sell_alerts = []
    current_positions_count = 0
    if state['held_assets']:
        report += "💼 持倉監控：\n"
        for sym, info in list(state['held_assets'].items()):
            if sym not in today_p.index or pd.isna(today_p[sym]): continue
            current_positions_count += 1

            curr_p = today_p[sym]
            m50_line = ma50[sym].iloc[-1]
            entry_p = info.get('entry', 0)
            
            # 更新歷史最高
            info['high'] = max(info.get('high', curr_p), curr_p)
            
            # 計算防線
            trailing_stop = info['high'] * 0.75 
            hard_stop = entry_p * 0.85 if entry_p > 0 else 0
            final_stop = max(trailing_stop, hard_stop)
            
            # 計算損益 %
            pnl_str = ""
            if entry_p > 0:
                pnl = (curr_p - entry_p) / entry_p * 100
                icon = "🔥" if pnl > 0 else "❄️"
                pnl_str = f"({icon}{pnl:+.1f}%)"

            ma50_str = f"{m50_line:.1f}" if not pd.isna(m50_line) else "N/A"
            report += f"🔸 {sym} {pnl_str}\n"
            report += f"   現價: {curr_p:.2f} (MA50:{ma50_str})\n"
            report += f"   止損: {final_stop:.2f}\n"
            
            if not pd.isna(m50_line) and curr_p < m50_line:
                sell_alerts.append(f"❌ 賣出 {sym}: 跌破季線")
            elif curr_p < trailing_stop:
                sell_alerts.append(f"🟠 賣出 {sym}: 獲利回吐 25%")
            elif entry_p > 0 and curr_p < hard_stop:
                sell_alerts.append(f"🔴 賣出 {sym}: 硬止損觸發 (-15%)")

    if sell_alerts:
        report += "\n⚠️ 【緊急行動建議】\n" + "\n".join(sell_alerts) + "\n"

    # E. 買入掃描
    candidates = []
    slots_left = 3 - current_positions_count
    
    if slots_left > 0 and (spy_bull or btc_bull):
        for t in [x for x in prices.columns if x != '^GSPC']:
            if t in state['held_assets']: continue
            
            # 分市場過濾
            is_crypto = "-USD" in t
            if is_crypto and not btc_bull: continue
            if not is_crypto and not spy_bull: continue
            
            p = today_p[t]
            if pd.isna(p) or pd.isna(ma20[t].iloc[-1]) or pd.isna(ma50[t].iloc[-1]): continue
            
            if p > ma20[t].iloc[-1] and p > ma50[t].iloc[-1]:
                score = mom_20[t].iloc[-1]
                if pd.isna(score): continue
                if any(lev in t for lev in STRATEGIC_POOL['LEVERAGE']): score *= 1.4
                if score > 0: candidates.append((t, score, p))
    
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        if candidates:
            report += "➖➖➖➖➖➖➖➖➖➖\n"
            report += f"🚀 【強勢進場建議】(剩 {slots_left} 席)\n"
            pos_size_pct = 33.3 
            for i, (sym, sc, p) in enumerate(candidates[:slots_left]):
                report += f"💎 {sym}\n"
                report += f"   建議權重: 總資金 {pos_size_pct}%\n"
                report += f"   建議價: {p:.2f} | 止損: {p*0.85:.1f}\n"

    # F. 存檔與發送
    send_line_push(report)
    with open('state.json', 'w') as f: json.dump(state, f, indent=4)
    print("✅ 任務完成。")

if __name__ == "__main__":
    main()
