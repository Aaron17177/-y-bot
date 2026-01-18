import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import requests
import ccxt
from datetime import datetime
import pytz

# ==========================================
# 1. 核心配置 (從 GitHub Secrets 讀取)
# ==========================================
LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')

# 幣安 (Binance) API
BN_KEY = os.getenv('BINANCE_API_KEY')
BN_SECRET = os.getenv('BINANCE_SECRET_KEY')

# 台股 (TW Stocks) API [新增]
TW_KEY = os.getenv('TWSTOCKS_API_KEY')
TW_SECRET = os.getenv('TWSTOCKS_SECRET_KEY')

# 初始化幣安客戶端 (只讀權限)
exchange = None
if BN_KEY and BN_SECRET:
    try:
        exchange = ccxt.binance({
            'apiKey': BN_KEY,
            'secret': BN_SECRET,
            'enableRateLimit': True,
        })
    except Exception as e:
        print(f"⚠️ 幣安連線初始化失敗: {e}")

# --- 幣種代號對照表 ---
BINANCE_TO_YF = {
    'PEPE': 'PEPE24478-USD', 'RNDR': 'RENDER-USD', 'RENDER': 'RENDER-USD',
    'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'FLOKI': 'FLOKI-USD', 'SHIB': 'SHIB-USD'
}
YF_TO_BINANCE = {v: k for k, v in BINANCE_TO_YF.items()}

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
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("❌ LINE 配置缺失，訊息內容：\n", message)
        return
    
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    payload = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"❌ LINE 發送失敗: {response.text}")
    except Exception as e:
        print(f"❌ LINE 連線異常: {e}")

def get_binance_symbol(yf_ticker):
    if yf_ticker in YF_TO_BINANCE: base = YF_TO_BINANCE[yf_ticker]
    else: base = yf_ticker.replace('-USD', '')
    return f"{base}/USDT"

def sync_holdings_with_binance(state):
    """自動偵測幣安持倉並更新追蹤帳本"""
    # 這裡未來可以加入 if TW_KEY: sync_with_tw_broker()... 的邏輯
    
    if not exchange: return state, "⚠️ 幣安 API 未設定，僅能手動同步持倉\n"
    try:
        balance = exchange.fetch_balance()
        api_holdings = {}
        for coin, total in balance['total'].items():
            if total > 0:
                ticker = BINANCE_TO_YF.get(coin, f"{coin}-USD")
                if ticker in STRATEGIC_POOL['CRYPTO']: api_holdings[ticker] = total
        
        sync_log = ""
        new_assets = {}
        # A. 更新/新增 API 偵測到的幣種
        for ticker, amount in api_holdings.items():
            if ticker in state['held_assets']:
                new_assets[ticker] = state['held_assets'][ticker]
            else:
                try:
                    symbol_ccxt = get_binance_symbol(ticker)
                    trades = exchange.fetch_my_trades(symbol_ccxt, limit=1)
                    entry_p = trades[0]['price'] if trades else 0
                except: entry_p = 0 
                new_assets[ticker] = {"entry": entry_p, "high": entry_p}
                sync_log += f"➕ 新增持倉: {ticker}\n"

        # B. 檢查已賣出
        for ticker in list(state['held_assets'].keys()):
            if "-USD" in ticker and ticker not in api_holdings:
                sync_log += f"➖ 偵測清倉: {ticker}\n"
        
        # C. 保留非 Crypto 標的 (美股/台股)
        for ticker, info in state['held_assets'].items():
            if "-USD" not in ticker: new_assets[ticker] = info
        
        state['held_assets'] = new_assets
        if not sync_log: sync_log = "✅ 帳戶同步完成 (無變動)\n"
        return state, sync_log
    except Exception as e: return state, f"❌ 同步異常: {str(e)}\n"

# ==========================================
# 4. 主決策引擎
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
        mom_20 = prices.pct_change(20)
    except Exception as e:
        send_line_push(f"❌ 數據抓取失敗: {e}")
        return

    # B. 狀態與同步
    state_file = 'state.json'
    state = json.load(open(state_file)) if os.path.exists(state_file) else {"held_assets": {}}
    state, sync_info = sync_holdings_with_binance(state)
    
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
    report += f"{sync_info}"
    report += "➖➖➖➖➖➖➖➖➖➖\n"
    
    # 市場氣象站
    spy_icon = "🟢" if spy_bull else "🔴"
    btc_icon = "🟢" if btc_bull else "🔴"
    report += "📡 市場氣象站\n"
    report += f"🇺🇸 美股: {spy_icon} (SPY: {spy_p:.0f}/{spy_ma:.0f})\n"
    if 'BTC-USD' in prices:
        report += f"₿  幣圈: {btc_icon} (BTC: {btc_p:.0f}/{btc_ma:.0f})\n"
    report += "➖➖➖➖➖➖➖➖➖➖\n"

    # C. 持倉監控 (包含損益與安全距離)
    sell_alerts = []
    current_positions_count = 0
    
    if state['held_assets']:
        report += "💼 持倉監控\n"
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
            
            # 計算距離止損 %
            dist_to_stop = (curr_p - final_stop) / curr_p * 100
            
            report += f"🔸 {sym} {pnl_str}\n"
            report += f"   現價: {curr_p:.2f} | 止損: {final_stop:.2f}\n"
            report += f"   安全空間: {dist_to_stop:.1f}%\n"

            # 觸發檢查
            if curr_p < m50_line:
                sell_alerts.append(f"❌ 賣出 {sym}: 跌破季線 MA50")
            elif curr_p < trailing_stop:
                sell_alerts.append(f"🟠 賣出 {sym}: 移動停利 (-25%)")
            elif entry_p > 0 and curr_p < hard_stop:
                sell_alerts.append(f"🔴 賣出 {sym}: 硬止損觸發 (-15%)")
    else:
        report += "💼 目前無持倉 (空手觀望)\n"

    if sell_alerts:
        report += "➖➖➖➖➖➖➖➖➖➖\n"
        report += "🚨 【緊急賣出指令】\n" + "\n".join(sell_alerts) + "\n"

    # D. 買入掃描 (Top 3)
    candidates = []
    
    # 策略限制：最多持有 3 檔
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
                if any(lev in t for lev in STRATEGIC_POOL['LEVERAGE']): score *= 1.4
                if score > 0: candidates.append((t, score, p))
    
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        if candidates:
            report += "➖➖➖➖➖➖➖➖➖➖\n"
            report += f"🚀 【強勢進場建議】(剩 {slots_left} 席)\n"
            pos_size_pct = 33.3 
            
            for i, (sym, sc, p) in enumerate(candidates[:slots_left]):
                stop_loss = p * 0.85
                report += f"💎 {sym}\n"
                report += f"   建議權重: 總資金 {pos_size_pct}%\n"
                report += f"   建議價: {p:.2f}\n   初始止損: {stop_loss:.2f}\n"

    # E. 發送
    send_line_push(report)
    with open('state.json', 'w') as f: json.dump(state, f, indent=4)
    print("✅ 戰情室日報發送完成。")

if __name__ == "__main__":
    main()
