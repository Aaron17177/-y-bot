# ==========================================
# Gemini V44 Super Nova (SN-Sentinel): Master Baseline Bot
# ------------------------------------------
# [確立邏輯] 遵循 v4.0 審計版核心規範
# 1. 核心 (80%): BTC/ETH 動態權重 (60/20 或 40/40)。
# 2. 衛星 (20%): Hyper Attack 雙星輪動 (10% + 10%)。
# 3. 裝甲 (Threshold): 5% 調倉門檻，對抗 0.2% 摩擦成本。
# 4. 執行 (Execution): T+1 延遲邏輯之實戰信號。
# 5. 通知 (Messaging): LINE Messaging API 自動推播。
# 6. 提醒 (Maintenance): 半年更新提醒 (預設 2026-06-28)。
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
# 0. LINE 傳送模組 (Messaging API)
# ==========================================
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_UID = os.environ.get('LINE_USER_ID')

def send_line_push(msg):
    if not LINE_TOKEN or not LINE_UID:
        print("⚠️ 未檢測到 LINE 金鑰，僅在終端機輸出結果：")
        print(msg)
        return

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_TOKEN}'
    }
    payload = {
        "to": LINE_UID,
        "messages": [{"type": "text", "text": msg}]
    }
    
    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200:
            print("✅ LINE 訊息推播成功！")
        else:
            print(f"❌ LINE 推播失敗: {res.text}")
    except Exception as e:
        print(f"❌ 網絡錯誤: {e}")

# 自動安裝與引入 yfinance
try:
    import yfinance as yf
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance"])
    import yfinance as yf

# ==========================================
# ⚙️ 實戰帳戶現況 (請在 GitHub 每日或交易後更新此區)
# ==========================================
USER_ACCOUNT = {
    'TOTAL_EQUITY_USDT': 93750.0,    # 👈 1. 目前總資產 (USDT 估值)
    
    'CURRENT_BTC_W': 0.0,           # 2. 目前 BTC 佔比 (0.0 ~ 1.0)
    'CURRENT_ETH_W': 0.0,           # 3. 目前 ETH 佔比
    
    'CURRENT_SAT_1_SYM': 'NONE',    # 4. 目前持有的衛星 1 代號 (如 'SOL')
    'CURRENT_SAT_1_W': 0.0,         # 5. 目前衛星 1 佔比
    
    'CURRENT_SAT_2_SYM': 'NONE',    # 6. 目前持有的衛星 2 代號
    'CURRENT_SAT_2_W': 0.0          # 7. 目前衛星 2 佔比
}

# 基準 15 支精英候選池 (Lean 15)
SATELLITE_POOL = {
    'L1': ['SOL-USD', 'AVAX-USD', 'BNB-USD', 'SUI-USD', 'ADA-USD'],
    'MEME': ['DOGE-USD', 'SHIB-USD', 'PEPE24478-USD'],
    'AI_DEFI': ['RENDER-USD', 'INJ-USD'],
    'LEGACY': ['TRX-USD', 'XLM-USD', 'BCH-USD', 'LTC-USD', 'ZEC-USD']
}

# 參數設定
REBALANCE_THRESHOLD = 0.05  # 5% 調倉門檻 (確立版參數)
UPDATE_DEADLINE = datetime(2026, 6, 28) # 半年後提醒日期

# ==========================================
# 1. 策略分析引擎 (Master Baseline Logic)
# ==========================================
def analyze_market():
    all_sats = [t for sub in SATELLITE_POOL.values() for t in sub]
    tickers = ['BTC-USD', 'ETH-USD', '^VIX'] + all_sats
    
    print(f"📥 正在從全球數據伺服器抓取基準版全明星數據...")
    # 下載數據
    data = yf.download(tickers, start=(datetime.now() - timedelta(days=300)).strftime('%Y-%m-%d'), group_by='ticker', progress=False, auto_adjust=True)
    
    data_map = {}
    ticker_to_sector = {t.split('-')[0]: s for s, ts in SATELLITE_POOL.items() for t in ts}
    ticker_to_sector['PEPE24478'] = 'MEME'

    for ticker in data.columns.levels[0]:
        symbol = ticker.split('-')[0] if ticker != '^VIX' else 'VIX'
        try:
            df = data[ticker].copy().ffill()
            if df.empty or len(df) < 100: continue
            df['SMA_140'] = df['Close'].rolling(140).mean()
            df['SMA_200'] = df['Close'].rolling(200).mean()
            df['Mayer'] = df['Close'] / df['SMA_200']
            df['Ret_20'] = df['Close'].pct_change(20)
            data_map[symbol] = df
        except: continue

    if 'BTC' not in data_map:
        raise Exception("❌ 無法獲取 BTC 數據，請檢查網絡環境。")

    today = data_map['BTC'].index[-1]
    vix = data_map['VIX'].loc[today]['Close'] if 'VIX' in data_map else 20
    row_btc = data_map['BTC'].loc[today]
    row_eth = data_map['ETH'].loc[today]
    
    bull_btc = row_btc['Close'] > row_btc['SMA_140']
    
    # 衛星選幣 (Momentum + Soft Sector Penalty)
    candidates = []
    for sym, sec in ticker_to_sector.items():
        if sym not in data_map: continue
        r = data_map[sym].loc[today]
        # 基礎過濾：需站上 SMA140 的 80%
        if r['Close'] > r['SMA_140'] * 0.8:
            candidates.append({'sym': sym, 'score': r['Ret_20'], 'sector': sec})
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    top_targets = []
    if candidates:
        top_targets.append(candidates[0])
        if len(candidates) > 1:
            f_sec = candidates[0]['sector']
            # 軟性懲罰機制：同板塊分數打 8 折
            challenger = sorted([{**c, 'adj': c['score']*0.8 if c['sector']==f_sec else c['score']} for c in candidates[1:]], key=lambda x: x['adj'], reverse=True)[0]
            top_targets.append(challenger)

    # 目標配比計算
    tw = {'BTC': 0.0, 'ETH': 0.0, 'SAT1': 0.0, 'SAT2': 0.0}
    ss = {'SAT1': 'NONE', 'SAT2': 'NONE'}

    if vix < 30 and bull_btc:
        sat_alloc = 0.20
        core_alloc = 0.80
        # Sentinel 核心切換
        if row_eth['Ret_20'] > row_btc['Ret_20']:
            tw['BTC'], tw['ETH'] = core_alloc * 0.5, core_alloc * 0.5
        else:
            tw['BTC'], tw['ETH'] = core_alloc * 0.75, core_alloc * 0.25
        
        for i, t in enumerate(top_targets):
            key = f'SAT{i+1}'
            tw[key] = sat_alloc / 2
            ss[key] = t['sym']

    return tw, ss, vix, row_btc['Mayer'], bull_btc, today

# ==========================================
# 2. 戰報生成 (對齊台幣本位與 5% 門檻)
# ==========================================
def generate_report():
    tw, ss, vix, mayer, is_bull, dt = analyze_market()
    total_eq = USER_ACCOUNT['TOTAL_EQUITY_USDT']
    
    msg = f"🛡️ V44 Master Baseline 戰報\n"
    msg += f"📅 日期: {dt.strftime('%Y-%m-%d')}\n"
    msg += f"🌍 環境: {'🟢牛市進攻' if is_bull else '🛡️清倉避險'} | VIX: {vix:.1f}\n"
    msg += f"📈 Mayer: {mayer:.2f}\n"
    msg += "-" * 22 + "\n"

    # 資產清單循環判定
    items = [
        ('BTC', USER_ACCOUNT['CURRENT_BTC_W'], tw['BTC'], 'NONE'),
        ('ETH', USER_ACCOUNT['CURRENT_ETH_W'], tw['ETH'], 'NONE'),
        ('衛星1', USER_ACCOUNT['CURRENT_SAT_1_W'], tw['SAT1'], USER_ACCOUNT['CURRENT_SAT_1_SYM']),
        ('衛星2', USER_ACCOUNT['CURRENT_SAT_2_W'], tw['SAT2'], USER_ACCOUNT['CURRENT_SAT_2_SYM'])
    ]

    for name, curr, target, held_sym in items:
        display_name = name
        target_sym = 'NONE'
        if '衛星' in name:
            slot_key = 'SAT1' if '1' in name else 'SAT2'
            target_sym = ss[slot_key]
            display_name = f"衛星: {target_sym}"
        
        diff = target - curr
        action = "✅ 續抱"
        
        # 1. 清倉判定
        if target == 0 and curr > 0.01:
            action = "🚨 立即清倉"
        # 2. 換幣判定 (僅限衛星)
        elif "衛星" in display_name:
            if target_sym != "NONE" and target_sym != held_sym:
                action = f"🔄 換至 {target_sym}"
            elif abs(diff) > REBALANCE_THRESHOLD:
                action = f"🔔 建議調整"
        # 3. 權重門檻判定
        elif abs(diff) > REBALANCE_THRESHOLD:
            action = f"🔔 建議調整"
            
        msg += f"{display_name}\n"
        msg += f"   目標: {target*100:.1f}% | 動作: {action}\n"
        if action != "✅ 續抱":
            msg += f"   👉 預計變動: ${diff * total_eq:>+8.1f} USDT\n"

    msg += "-" * 22 + "\n"
    
    # 半年度更新倒數提醒
    days_to_update = (UPDATE_DEADLINE - dt.to_pydatetime().replace(tzinfo=None)).days
    if days_to_update <= 30:
        msg += f"⏳ [重要提醒] 距離系統半年檢修期僅剩 {days_to_update} 天！\n"
    else:
        msg += f"💡 下次系統更新建議日期: {UPDATE_DEADLINE.strftime('%Y-%m-%d')}\n"

    msg += f"👉 叮嚀: 目前門檻為 5%，顯示『續抱』請不要交易。領取 Pendle 10% 利息等待訊號。"
    
    return msg

# ==========================================
# 3. 主程式執行
# ==========================================
if __name__ == "__main__":
    try:
        report_text = generate_report()
        send_line_push(report_text)
    except Exception as e:
        err_msg = f"❌ V44 執行錯誤: {str(e)}"
        print(err_msg)
        send_line_push(err_msg)
