# ==========================================
# Gemini V44 Super Nova (SN-Sentinel): Master Live Bot v9.9.1
# ------------------------------------------
# [戰略確立：積累期終極邏輯]
# 1. 核心 (80%): BTC/ETH 動態哨兵，依匯率強弱決定 (60/20) 或 (40/40)。
# 2. 衛星 (20%): Lean 15 雙星輪動 (10% + 10%)。
# 3. 梅耶煞車: 若 BTC Mayer Multiple > 2.4，全體部位減半，獲利落袋為安。
# 4. 複利導向: 利息全數回流現金池，存放於 Pendle (10% APY)。
# 5. 鋼鐵門檻: 5% 調倉門檻，極小化交易磨損。
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
        print(msg); return
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_TOKEN}'}
    payload = {"to": LINE_UID, "messages": [{"type": "text", "text": msg}]}
    try:
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code == 200: print("✅ LINE 戰報推播成功！")
    except: print("❌ 網絡錯誤")

try:
    import yfinance as yf
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance"])
    import yfinance as yf

# ==========================================
# ⚙️ 每日實戰帳戶現況 (下單前請在此更新數據)
# ==========================================
USER_ACCOUNT = {
    'TOTAL_EQUITY_USDT': 93750.0,    # 👈 1. 目前交易所看到的 USDT 總資產 (幣+現金)
    
    # --- 目前持倉佔比 (交易所看到多少就填多少，範圍 0.0 ~ 1.0) ---
    'CURRENT_BTC_W': 0.0,           
    'CURRENT_ETH_W': 0.0,           
    'CURRENT_SAT_1_SYM': 'NONE',    
    'CURRENT_SAT_1_W': 0.0,
    'CURRENT_SAT_2_SYM': 'NONE',    
    'CURRENT_SAT_2_W': 0.0
}

# --- 核心策略參數 ---
REBALANCE_THRESHOLD = 0.05  
SWITCH_THRESHOLD = 0.15     
VIX_LIMIT = 30              
MAYER_LIMIT = 2.4           
PENDLE_APY = 0.10           

SATELLITE_POOL = {
    'L1': ['SOL-USD', 'AVAX-USD', 'BNB-USD', 'SUI-USD', 'ADA-USD'],
    'MEME': ['DOGE-USD', 'SHIB-USD', 'PEPE24478-USD'],
    'AI_DEFI': ['RENDER-USD', 'INJ-USD'],
    'LEGACY': ['TRX-USD', 'XLM-USD', 'BCH-USD', 'LTC-USD', 'ZEC-USD']
}

# ==========================================
# 1. 指標分析引擎 (Mayer Brake + Sentinel)
# ==========================================
def analyze_market_v991():
    all_sats = [t for sub in SATELLITE_POOL.values() for t in sub]
    tickers = ['BTC-USD', 'ETH-USD', '^VIX'] + all_sats
    
    print(f"📥 正在執行全明星數據抓取與動能排名...")
    start_str = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    data = yf.download(tickers, start=start_str, group_by='ticker', progress=False, auto_adjust=True)
    
    data_map = {}
    ticker_to_sector = {t.split('-')[0]: s for s, ts in SATELLITE_POOL.items() for t in ts}
    ticker_to_sector['PEPE24478'] = 'MEME'

    for ticker in tickers:
        symbol = ticker.split('-')[0] if ticker != '^VIX' else 'VIX'
        try:
            if isinstance(data.columns, pd.MultiIndex) and ticker in data.columns.levels[0]:
                df = data[ticker].copy().ffill().bfill()
            elif ticker == 'BTC-USD': df = data.copy().ffill().bfill()
            else: continue
            
            if df.empty or len(df) < 50:
                df = yf.download(ticker, start=start_str, progress=False, auto_adjust=True).ffill().bfill()
            
            df['SMA_60'] = df['Close'].rolling(60).mean()
            df['SMA_140'] = df['Close'].rolling(140).mean()
            df['SMA_200'] = df['Close'].rolling(200).mean()
            df['Ret_20'] = df['Close'].pct_change(20)
            if symbol == 'BTC': df['Mayer'] = df['Close'] / df['SMA_200']
            data_map[symbol] = df
        except: continue

    today = data_map['BTC'].index[-1]
    vix = data_map['VIX'].loc[today]['Close'] if 'VIX' in data_map else 20
    row_btc = data_map['BTC'].loc[today]; row_eth = data_map['ETH'].loc[today]
    bull_btc = row_btc['Close'] > row_btc['SMA_140']
    
    # 衛星選幣排名
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
            challenger = sorted([{**c, 'adj': c['score']*0.8 if c['sector']==f_sec else c['score']} for c in candidates[1:]], key=lambda x: x['adj'], reverse=True)[0]
            top_targets.append(challenger)

    # 權重分配
    tw = {'BTC': 0.0, 'ETH': 0.0, 'SAT1': 0.0, 'SAT2': 0.0}
    ss = {'SAT1': 'NONE', 'SAT2': 'NONE'}

    if vix < VIX_LIMIT and bull_btc:
        sat_alloc = 0.20; core_alloc = 0.80
        exposure_mult = 0.5 if row_btc['Mayer'] > MAYER_LIMIT else 1.0
        
        eth_btc_series = data_map['ETH']['Close'] / data_map['BTC']['Close']
        is_eth_strong = (row_eth['Close']/row_btc['Close']) > eth_btc_series.rolling(50).mean().iloc[-1]

        if is_eth_strong and row_eth['Close'] > row_eth['SMA_140']:
            w_b, w_e = core_alloc * 0.5, core_alloc * 0.5
        else:
            w_b, w_e = core_alloc * 0.75, core_alloc * 0.25
            
        tw['BTC'], tw['ETH'] = w_b * exposure_mult, w_e * exposure_mult
        for i, t in enumerate(top_targets):
            key = f'SAT{i+1}'; tw[key] = (sat_alloc / 2) * exposure_mult; ss[key] = t['sym']

    return tw, ss, vix, row_btc['Mayer'], bull_btc, today, candidates

# ==========================================
# 2. 戰報生成 (視覺優化版)
# ==========================================
def generate_optimized_report():
    tw, ss, vix, mayer, is_bull, dt, candidates = analyze_market_v991()
    total_eq = USER_ACCOUNT['TOTAL_EQUITY_USDT']
    
    # 建立戰報
    msg = f"🚀 V44 Sentinel 財富積累戰報\n"
    msg += f"📅 日期: {dt.strftime('%Y-%m-%d')}\n"
    msg += f"💰 總資產: ${total_eq:,.0f} USDT\n"
    msg += f"----------------------------\n"

    # 第一區：市場環境
    env_icon = "🟢" if is_bull else "🛡️"
    mayer_warn = " 🔥(過熱)" if mayer > 2.4 else " ✅(正常)"
    msg += f"🌍 環境: {env_icon}{'牛市進攻' if is_bull else '避險清倉'}\n"
    msg += f"📈 恐慌 VIX: {vix:.1f}\n"
    msg += f"📊 梅耶指數: {mayer:.2f}{mayer_warn}\n"
    msg += f"----------------------------\n"

    # 第二區：交易指令
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
        
        # 動作判定
        action = "[✅ 續抱]"
        if target == 0 and curr > 0.01: action = "[🚨 立即清倉]"
        elif "衛星" in name and target_sym != "NONE" and target_sym != held_sym:
            action = f"[🔄 換至 {target_sym}]"
        elif abs(diff) > REBALANCE_THRESHOLD:
            action = f"[🔔 建議調倉]"
            
        msg += f"• {name}\n"
        msg += f"  目標: {target*100:>4.1f}% | {action}\n"
        if "續抱" not in action:
            msg += f"  👉 變動: {diff*total_eq:>+7.0f} USDT\n"

    msg += f"----------------------------\n"

    # 第三區：動能排行榜 (新加入)
    msg += f"📊 [全市場動能排行榜]\n"
    if candidates:
        for i, c in enumerate(candidates[:5]):
            rank_icon = "👑" if c['sym'] in [ss['SAT1'], ss['SAT2']] else "🔹"
            msg += f"{i+1}. {rank_icon}{c['sym']}: {c['score']*100:+.1f}%\n"
    else:
        msg += "💤 目前無標的站上 60日均線\n"
    msg += f"----------------------------\n"

    # 第四區：複利調度
    target_cash_w = 1.0 - sum(tw.values())
    daily_int = (total_eq * target_cash_w) * (PENDLE_APY / 365)
    msg += f"💰 [複利調度指南]\n"
    msg += f"• 閒置現金: ${total_eq * target_cash_w:,.0f} USDT\n"
    msg += f"• 存入 Pendle (USD0++)\n"
    msg += f"• 每日利息: ${daily_int:,.2f} USDT\n"
    msg += f"----------------------------\n"

    # 第五區：衝刺進度
    progress = (total_eq * 32 / 30000000) * 100
    msg += f"🚩 衝刺 3000 萬進度: {progress:.1f}%\n"
    msg += f"👉 5% 門檻護航中，省下就是賺到。"
    
    return msg

if __name__ == "__main__":
    try: send_line_push(generate_optimized_report())
    except Exception as e: print(f"❌ 執行錯誤: {e}")
