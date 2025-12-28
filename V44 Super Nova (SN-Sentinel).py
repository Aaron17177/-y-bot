# ==========================================
# Gemini V44 Super Nova (SN-Sentinel): Master Baseline Bot
# ------------------------------------------
# [戰略核心：最終確立基準版]
# 1. 核心 (80%): BTC/ETH 動態權重 (60/20 或 40/40)。
# 2. 衛星 (20%): Hyper Attack 雙星輪動 (10% + 10%)。
# 3. 裝甲 (Threshold): 5% 調倉門檻，對抗 0.2% 摩擦。
# 4. 執行 (Execution): T+1 延遲邏輯之實戰信號。
# 5. 提醒 (Maintenance): 半年度系統更新提醒 (半年後)。
# ==========================================

import os
import sys
import requests
import warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from scipy import stats

warnings.filterwarnings("ignore")

# ==========================================
# 0. 環境檢查與 LINE 設定 (Messaging API)
# ==========================================
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_UID = os.environ.get('LINE_USER_ID')

def send_line_push(msg):
    if not LINE_TOKEN or not LINE_UID:
        print("⚠️ 未檢測到 LINE 金鑰，僅在終端機輸出結果。")
        print(msg)
        return

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_TOKEN}'}
    payload = {"to": LINE_UID, "messages": [{"type": "text", "text": msg}]}
    
    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200: print("✅ LINE 訊息推播成功！")
        else: print(f"❌ LINE 推播失敗: {res.text}")
    except Exception as e: print(f"❌ 網絡錯誤: {e}")

# 自動安裝 yfinance
try:
    import yfinance as yf
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance"])
    import yfinance as yf

# ==========================================
# ⚙️ 用戶與標的名單 (確立版)
# ==========================================
USER_ACCOUNT = {
    'TOTAL_EQUITY_USDT': 93750.0,    # 👈 [總資產]：請手動更新或維持基準 300 萬台幣水位
    'CURRENT_BTC_W': 0.0,           # 目前 BTC 佔比 (0.0~1.0)
    'CURRENT_ETH_W': 0.0,           
    'CURRENT_SAT_1_SYM': 'NONE',    # 目前持有衛星 1
    'CURRENT_SAT_1_W': 0.0,
    'CURRENT_SAT_2_SYM': 'NONE',    # 目前持有衛星 2
    'CURRENT_SAT_2_W': 0.0
}

# 基準 15 支精英候選池 (Lean 15)
SATELLITE_POOL = {
    'L1': ['SOL-USD', 'AVAX-USD', 'BNB-USD', 'SUI-USD', 'ADA-USD'],
    'MEME': ['DOGE-USD', 'SHIB-USD', 'PEPE24478-USD'],
    'AI_DEFI': ['RENDER-USD', 'INJ-USD'],
    'LEGACY': ['TRX-USD', 'XLM-USD', 'BCH-USD', 'LTC-USD', 'ZEC-USD']
}

REBALANCE_THRESHOLD = 0.05  # 5% 門檻
VIX_LIMIT = 30
MAYER_LIMIT = 2.4
UPDATE_DEADLINE = datetime(2026, 6, 28) # 👈 設定半年後更新日期

# ==========================================
# 1. 策略引擎
# ==========================================
def analyze_baseline():
    all_sats = [t for sub in SATELLITE_POOL.values() for t in sub]
    tickers = ['BTC-USD', 'ETH-USD', '^VIX'] + all_sats
    
    print(f"📥 正在抓取基準版全明星數據...")
    # 下載數據
    data = yf.download(tickers, start=(datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'), group_by='ticker', progress=False, auto_adjust=True)
    
    data_map = {}
    ticker_to_sector = {t.split('-')[0]: s for s, ts in SATELLITE_POOL.items() for t in ts}
    ticker_to_sector['PEPE24478'] = 'MEME'

    for ticker in data.columns.levels[0]:
        symbol = ticker.split('-')[0] if ticker != '^VIX' else 'VIX'
        df = data[ticker].copy().ffill()
        if df.empty or len(df) < 140: continue
        df['SMA_60'] = df['Close'].rolling(60).mean()
        df['SMA_140'] = df['Close'].rolling(140).mean()
        df['SMA_200'] = df['Close'].rolling(200).mean()
        df['Mayer'] = df['Close'] / df['SMA_200']
        df['Ret_20'] = df['Close'].pct_change(20)
        data_map[symbol] = df

    today = data_map['BTC'].index[-1]
    vix = data_map['VIX'].loc[today]['Close']
    row_btc = data_map['BTC'].loc[today]
    row_eth = data_map['ETH'].loc[today]
    
    is_panic = vix > VIX_LIMIT
    bull_btc = row_btc['Close'] > row_btc['SMA_140']
    
    # 衛星選幣：純動能模式 + 軟性板塊懲罰
    candidates = []
    for sym, sector in ticker_to_sector.items():
        if sym not in data_map: continue
        r = data_map[sym].loc[today]
        if r['Close'] > r['SMA_60'] and r['Ret_20'] > row_btc['Ret_20']:
            candidates.append({'sym': sym, 'score': r['Ret_20'], 'sector': sector})
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    top_targets = []
    if candidates:
        top_targets.append(candidates[0])
        if len(candidates) > 1:
            f_sec = candidates[0]['sector']
            challengers = sorted([{**c, 'adj': c['score']*0.8 if c['sector']==f_sec else c['score']} for c in candidates[1:]], key=lambda x: x['adj'], reverse=True)
            top_targets.append(challengers[0])

    # 目標分配計算
    tw = {'BTC': 0.0, 'ETH': 0.0, 'SAT1': 0.0, 'SAT2': 0.0}
    ss = {'SAT1': 'NONE', 'SAT2': 'NONE'}

    if not is_panic and bull_btc:
        sat_alloc = 0.20 
        core_alloc = 0.80
        
        # Sentinel 核心 (60/20 vs 40/40)
        if row_eth['Ret_20'] > row_btc['Ret_20'] and row_eth['Close'] > row_eth['SMA_140']:
            tw['BTC'], tw['ETH'] = core_alloc * 0.5, core_alloc * 0.5
        else:
            tw['BTC'], tw['ETH'] = core_alloc * 0.75, core_alloc * 0.25
            
        for i, t in enumerate(top_targets):
            key = f'SAT{i+1}'
            tw[key] = sat_alloc / len(top_targets)
            ss[key] = t['sym']

    return tw, ss, vix, row_btc['Mayer'], bull_btc, today

# ==========================================
# 2. 戰報生成器
# ==========================================
def generate_report():
    tw, ss, vix, mayer, is_bull, dt = analyze_baseline()
    total_eq = USER_ACCOUNT['TOTAL_EQUITY_USDT']
    
    msg = f"🛡️ V44 Master Baseline 戰報\n"
    msg += f"📅 日期: {dt.strftime('%Y-%m-%d')}\n"
    msg += f"🌍 環境: {'🟢進攻' if is_bull else '🛡️清倉'} | VIX: {vix:.1f}\n"
    msg += f"📈 Mayer: {mayer:.2f} {'(過熱⚠️)' if mayer > 2.4 else '(正常✅)'}\n"
    msg += "-" * 20 + "\n"

    # 資產比對與動作判定
    asset_items = [
        ('BTC', USER_ACCOUNT['CURRENT_BTC_W'], tw['BTC'], "NONE"),
        ('ETH', USER_ACCOUNT['CURRENT_ETH_W'], tw['ETH'], "NONE"),
        ('SAT1', USER_ACCOUNT['CURRENT_SAT_1_W'], tw['SAT1'], USER_ACCOUNT['CURRENT_SAT_1_SYMBOL']),
        ('SAT2', USER_ACCOUNT['CURRENT_SAT_2_W'], tw['SAT2'], USER_ACCOUNT['CURRENT_SAT_2_SYMBOL'])
    ]

    for name, curr, target, held_sym in asset_items:
        display_name = name
        target_sym = "NONE"
        if 'SAT' in name:
            target_sym = ss[name]
            display_name = f"衛星: {target_sym}"
        
        diff = target - curr
        action = "✅ 續抱"
        
        if target == 0 and curr > 0.01:
            action = "🚨 立即賣出"
        elif '衛星' in display_name:
            if target_sym != "NONE" and target_sym != held_sym:
                action = f"🔄 換至 {target_sym}"
            elif abs(diff) > REBALANCE_THRESHOLD:
                action = f"🔔 建議調整"
        elif abs(diff) > REBALANCE_THRESHOLD:
            action = f"🔔 建議調整"
            
        msg += f"{display_name}\n"
        msg += f"   目標: {target*100:.1f}% | 動作: {action}\n"
        if action != "✅ 續抱":
            amt = diff * total_eq
            msg += f"   👉 增減: {amt:>+8.1f} USDT\n"

    msg += "-" * 20 + "\n"
    
    # 3. 半年度更新提醒邏輯
    days_to_update = (UPDATE_DEADLINE - dt.to_pydatetime().replace(tzinfo=None)).days
    if days_to_update <= 0:
        msg += f"🔥 [緊急提醒]：系統已到達半年維護期！請務必重新檢視 Lean 15 名單並與 Gemini 討論策略優化。\n"
    elif days_to_update <= 30:
        msg += f"⏳ [更新倒數]：距離下一次系統大檢修還有 {days_to_update} 天。請準備檢視幣種名單。\n"
    else:
        msg += f"💡 更新提醒：預計於 {UPDATE_DEADLINE.strftime('%Y-%m-%d')} 執行半年度檢查 (剩餘 {days_to_update} 天)。\n"

    msg += f"👉 叮嚀：目前調倉門檻鎖定為 5%。除非看到『🔔』或『🚨』，否則請保持耐心。"
    
    return msg

if __name__ == "__main__":
    try:
        report_msg = generate_report()
        send_line_push(report_msg)
    except Exception as e:
        print(f"❌ 錯誤: {e}")
