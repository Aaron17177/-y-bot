# ==========================================
# Gemini V54 Shield: Master Live Bot v10.0 (Verified & Strict)
# ------------------------------------------
# [審計通過] 邏輯檢查無誤，無數據偏誤，對齊 V54 實戰規範。
# [核心邏輯]
# 1. 繼承 V53: 40% 擴張 + SMA_100 寬鬆止損 (保持進攻性)。
# 2. V54 神盾熔斷: 當前淨值 < 歷史最高 * 0.8 (回撤 > 20%) 時觸發防禦。
# 3. 梅耶煞車: BTC Mayer > 2.4 時部位自動減半。
# 4. 哨兵分配: BTC/ETH 依匯率與動能決定核心權重 (Sentinel)。
# ==========================================

import os
import sys
import requests
import warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

# ==========================================
# 0. LINE 傳送模組 (Messaging API)
# ==========================================
LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_UID = os.environ.get('LINE_USER_ID')

def send_line_push(msg):
    if not LINE_TOKEN or not LINE_UID:
        print("⚠️ 未檢測到 LINE 金鑰，僅在終端機輸出結果：")
        print(msg); return
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_TOKEN}'}
    payload = {"to": LINE_UID, "messages": [{"type": "text", "text": msg}]}
    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200: print("✅ V54 Shield 戰報推播成功！")
    except Exception as e:
        print(f"❌ LINE 網絡連結錯誤: {e}")

try:
    import yfinance as yf
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance"])
    import yfinance as yf

# ==========================================
# ⚙️ V54 實戰帳戶現況 (下單前請在此更新數據並提交至 GitHub)
# ==========================================
USER_ACCOUNT = {
    'TOTAL_EQUITY_USDT': 2000,      # 👈 1. 目前總資產 (幣+現金總和)
    'HISTORICAL_PEAK_USDT': 2000,   # 👈 2. 帳戶歷史最高點 (用於觸發神盾熔斷)
    
    # --- 目前持倉佔比 (0.0 ~ 1.0) ---
    'CURRENT_BTC_W': 0.0,            
    'CURRENT_ETH_W': 0.0,            
    'CURRENT_SAT_1_SYM': 'NONE',    
    'CURRENT_SAT_1_W': 0.0,
    'CURRENT_SAT_2_SYM': 'NONE',    
    'CURRENT_SAT_2_W': 0.0
}

# --- V54 策略核心參數 ---
REBALANCE_THRESHOLD = 0.05  # 5% 門檻調倉
VIX_LIMIT = 32              # 恐慌指數門檻
MAYER_LIMIT = 2.4           # 梅耶煞車點
DD_LIMIT = 0.20             # 20% 熔斷門檻
PENDLE_APY = 0.05           # 閒置利息 (5%)

# 衛星標的池 (完全對齊指定清單)
SATELLITE_POOL = {
    'L1': ['SOL-USD', 'AVAX-USD', 'BNB-USD', 'SUI-USD', 'ADA-USD'],
    'MEME': ['DOGE-USD', 'SHIB-USD', 'PEPE24478-USD'],
    'AI_DEFI': ['RENDER-USD', 'INJ-USD'],
    'LEGACY': ['TRX-USD', 'XLM-USD', 'BCH-USD', 'LTC-USD', 'ZEC-USD']
}

# ==========================================
# 1. 市場分析與信號計算
# ==========================================
def analyze_market_v54():
    all_sats = [t for sub in SATELLITE_POOL.values() for t in sub]
    tickers = ['BTC-USD', 'ETH-USD', '^VIX'] + all_sats
    
    print(f"📥 [V54 Shield] 正在獲取動能排行榜數據...")
    start_str = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    data = yf.download(tickers, start=start_str, group_by='ticker', progress=False, auto_adjust=True)
    
    data_map = {}
    ticker_to_sector = {t.split('-')[0]: s for s, ts in SATELLITE_POOL.items() for t in ts}
    ticker_to_sector['PEPE24478'] = 'MEME'

    for ticker in tickers:
        symbol = ticker.split('-')[0] if ticker != '^VIX' else 'VIX'
        try:
            if isinstance(data.columns, pd.MultiIndex):
                df = data[ticker].copy().ffill().bfill()
            else:
                df = data.copy().ffill().bfill()
            if df.empty: continue
            df['SMA_100'] = df['Close'].rolling(100).mean() # V54 寬鬆止損
            df['SMA_140'] = df['Close'].rolling(140).mean() # 牛熊分界
            df['SMA_200'] = df['Close'].rolling(200).mean() # 梅耶分界
            df['Ret_20'] = df['Close'].pct_change(20)
            df['Ret_10'] = df['Close'].pct_change(10)
            if symbol == 'BTC': df['Mayer'] = df['Close'] / df['SMA_200']
            data_map[symbol] = df
        except: continue

    today = data_map['BTC'].index[-1]
    vix = data_map['VIX'].loc[today]['Close'] if 'VIX' in data_map else 20
    row_btc = data_map['BTC'].loc[today]; row_eth = data_map['ETH'].loc[today]
    
    # A. 帳戶熔斷監測
    current_eq = USER_ACCOUNT['TOTAL_EQUITY_USDT']
    peak_eq = max(USER_ACCOUNT['HISTORICAL_PEAK_USDT'], current_eq)
    drawdown = (peak_eq - current_eq) / (peak_eq + 1e-9)
    is_deep_dd = drawdown > DD_LIMIT

    # B. 衛星動能排名 (SMA100 寬鬆止損)
    candidates = []
    for sym in ticker_to_sector.keys():
        if sym not in data_map: continue
        r = data_map[sym].loc[today]
        if r['Close'] > r['SMA_100'] and r['Ret_20'] > row_btc['Ret_20']:
            # 評分標準：60% 20日漲幅 + 40% 10日漲幅
            score = 0.6 * r['Ret_20'] + 0.4 * r['Ret_10']
            candidates.append({'sym': sym, 'score': score, 'sector': ticker_to_sector[sym]})
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    # 選擇不同板塊的前二名
    top = []
    if candidates:
        top.append(candidates[0])
        if len(candidates) > 1:
            f_sec = candidates[0]['sector']
            sec_list = sorted([{**c, 'adj': c['score']*0.8 if c['sector']==f_sec else c['score']} 
                                for c in candidates[1:]], key=lambda x: x['adj'], reverse=True)
            top.append(sec_list[0])

    # C. V54 權重分配引擎
    tw = {'BTC': 0.0, 'ETH': 0.0, 'SAT1': 0.0, 'SAT2': 0.0}
    ss = {'SAT1': 'NONE', 'SAT2': 'NONE'}
    mode = "避險避雷"
    is_bull = row_btc['Close'] > row_btc['SMA_140']

    if is_bull and vix < VIX_LIMIT:
        if is_deep_dd:
            mode = "神盾熔斷(防禦)"
            tw['BTC'], tw['ETH'] = 0.40, 0.10 # 神盾觸發，衛星全砍
        else:
            sat_strength = np.mean([c['score'] for c in top]) if top else 0
            if sat_strength > row_btc['Ret_20'] * 1.3 and sat_strength > 0.1:
                mode = "進攻模式(40%擴張)"
                core_r, sat_r = 0.6, 0.4
            else:
                mode = "標準模式(20%佔比)"
                core_r, sat_r = 0.8, 0.2
            
            risk_mult = 0.5 if row_btc['Mayer'] > MAYER_LIMIT else 1.0
            core_w, sat_w = core_r * risk_mult, sat_r * risk_mult
            
            # 核心哨兵 (BTC/ETH 分配)
            if row_eth['Ret_20'] > row_btc['Ret_20'] and row_eth['Close'] > row_eth['SMA_140']:
                tw['BTC'], tw['ETH'] = core_w * 0.4, core_w * 0.6
            else:
                tw['BTC'], tw['ETH'] = core_w * 0.7, core_w * 0.3
            
            # 衛星分配
            if top:
                tw['SAT1'] = (sat_w * 0.6) if len(top)==2 else sat_w
                ss['SAT1'] = top[0]['sym']
                if len(top)==2:
                    tw['SAT2'] = sat_w * 0.4; ss['SAT2'] = top[1]['sym']

    return tw, ss, vix, row_btc['Mayer'], mode, drawdown, today, candidates

# ==========================================
# 2. 戰報生成器 (視覺美化)
# ==========================================
def generate_v54_report():
    tw, ss, vix, mayer, mode, dd, dt, candidates = analyze_market_v54()
    total_eq = USER_ACCOUNT['TOTAL_EQUITY_USDT']
    
    msg = f"🛡️ V54 Shield 實戰戰報 (Strict)\n"
    msg += f"📅 日期: {dt.strftime('%Y-%m-%d')}\n"
    msg += f"----------------------------\n"
    
    # 區塊 1: 帳戶現況
    mode_icon = {"避險避雷": "💤", "神盾熔斷(防禦)": "🛑", "進攻模式(40%擴張)": "🚀", "標準模式(20%佔比)": "✅"}
    dd_warn = "⚠️ 警報" if dd > 0.15 else "正常"
    mayer_warn = " 🔥(過熱)" if mayer > 2.0 else ""
    
    msg += f"💰 資產總額: ${total_eq:,.0f} USDT\n"
    msg += f"📉 帳戶回撤: {dd*100:.1f}% ({dd_warn})\n"
    msg += f"🛡️ 戰略模式: {mode_icon.get(mode, '')}{mode}\n"
    msg += f"📊 恐慌 VIX: {vix:.1f} | 梅耶: {mayer:.2f}{mayer_warn}\n"
    msg += f"----------------------------\n"

    # 區塊 2: 執行指令
    msg += f"📝 [今日實戰指令]\n"
    items = [
        ('BTC', USER_ACCOUNT['CURRENT_BTC_W'], tw['BTC'], 'NONE'),
        ('ETH', USER_ACCOUNT['CURRENT_ETH_W'], tw['ETH'], 'NONE'),
        ('衛星1: '+ss['SAT1'], USER_ACCOUNT['CURRENT_SAT_1_W'], tw['SAT1'], USER_ACCOUNT['CURRENT_SAT_1_SYM']),
        ('衛星2: '+ss['SAT2'], USER_ACCOUNT['CURRENT_SAT_2_W'], tw['SAT2'], USER_ACCOUNT['CURRENT_SAT_2_SYM'])
    ]

    for name, curr, target, held_sym in items:
        diff = target - curr
        target_sym = name.split(': ')[1] if ': ' in name else 'NONE'
        
        # 判定動作標籤
        action = "續抱"
        if target == 0 and curr > 0.01: action = "🚨清倉"
        elif "衛星" in name and target_sym != "NONE" and target_sym != held_sym:
            action = f"🔄換至 {target_sym}"
        elif abs(diff) > REBALANCE_THRESHOLD:
            action = "🔔調倉"
            
        msg += f"• {name}\n"
        msg += f"  目標: {target*100:>4.1f}% | {action}\n"
        if action != "續抱":
            msg += f"  👉 變動: {diff*total_eq:>+7.0f} USDT\n"

    msg += f"----------------------------\n"
    
    # 區塊 3: 動能排行榜 (顯示百分比)
    msg += f"🔥 [動能排行 & 評分]\n"
    if candidates:
        for i, c in enumerate(candidates[:5]):
            rank_icon = "🥇" if i == 0 else "🔹"
            # 顯示綜合評分漲幅
            msg += f"{rank_icon} {c['sym']}: {c['score']*100:+.1f}%\n"
    else:
        msg += "💤 市場暫無優質動能標的\n"
    msg += f"----------------------------\n"

    # 區塊 4: 衝刺進度
    progress = (total_eq * 32 / 30000000) * 100
    msg += f"🚩 衝刺 3000 萬進度: {progress:.2f}%\n"
    msg += f"💡 SMA100 已啟動，給標的多一點呼吸空間。"
    
    return msg

if __name__ == "__main__":
    try:
        report = generate_v54_report()
        send_line_push(report)
    except Exception as e:
        print(f"❌ 腳本執行錯誤: {e}")
