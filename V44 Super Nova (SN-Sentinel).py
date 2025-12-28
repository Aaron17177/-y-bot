# ==========================================
# Gemini V44 Super Nova (SN-Sentinel): Master Baseline Bot
# ------------------------------------------
# [修復日誌] 
# 1. 徹底解決 NaN 問題：過濾動能排行榜中的非數值 (NaN) 數據，防止 LINE 顯示 +nan%。
# 2. 數據強化：優化單幣下載補救流程，增加 SUI 等高頻失效幣種的容錯。
# 3. 穩定邏輯：堅持 v4.0 基準版 (80/20 分配, 5% 門檻, T+1 延遲)。
# 4. 提醒機制：維持 2026-06-28 系統大檢修提醒。
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
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_TOKEN}'}
    payload = {"to": LINE_UID, "messages": [{"type": "text", "text": msg}]}
    
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
# ⚙️ 實戰帳戶現況 (請每日或交易後更新此區)
# ==========================================
USER_ACCOUNT = {
    'TOTAL_EQUITY_USDT': 93750.0,    # 👈 目前總資產 (USDT)
    
    'CURRENT_BTC_W': 0.0,           # 目前 BTC 佔比 (0.0~1.0)
    'CURRENT_ETH_W': 0.0,           
    
    'CURRENT_SAT_1_SYM': 'NONE',    # 目前持有的衛星 1 代號
    'CURRENT_SAT_1_W': 0.0,         
    
    'CURRENT_SAT_2_SYM': 'NONE',    # 目前持有的衛星 2 代號
    'CURRENT_SAT_2_W': 0.0          
}

# 基準 15 支精英候選池 (Lean 15)
SATELLITE_POOL = {
    'L1': ['SOL-USD', 'AVAX-USD', 'BNB-USD', 'SUI-USD', 'ADA-USD'],
    'MEME': ['DOGE-USD', 'SHIB-USD', 'PEPE24478-USD'],
    'AI_DEFI': ['RENDER-USD', 'INJ-USD'],
    'LEGACY': ['TRX-USD', 'XLM-USD', 'BCH-USD', 'LTC-USD', 'ZEC-USD']
}

REBALANCE_THRESHOLD = 0.05  # 5% 調倉門檻
UPDATE_DEADLINE = datetime(2026, 6, 28) # 半年後提醒日期

# ==========================================
# 1. 策略分析引擎 (Master Baseline Logic)
# ==========================================
def analyze_market():
    all_sats = [t for sub in SATELLITE_POOL.values() for t in sub]
    tickers = ['BTC-USD', 'ETH-USD', '^VIX'] + all_sats
    
    print(f"📥 正在執行批次數據抓取...")
    start_str = (datetime.now() - timedelta(days=310)).strftime('%Y-%m-%d')
    data = yf.download(tickers, start=start_str, group_by='ticker', progress=False, auto_adjust=True)
    
    data_map = {}
    missing_coins = []
    ticker_to_sector = {t.split('-')[0]: s for s, ts in SATELLITE_POOL.items() for t in ts}
    ticker_to_sector['PEPE24478'] = 'MEME'

    for symbol_raw in tickers:
        symbol = symbol_raw.split('-')[0] if symbol_raw != '^VIX' else 'VIX'
        df = pd.DataFrame()
        
        try:
            if isinstance(data.columns, pd.MultiIndex) and symbol_raw in data.columns.levels[0]:
                df = data[symbol_raw].copy().ffill().bfill()
            elif symbol_raw == 'BTC-USD' and 'Close' in data.columns:
                df = data.copy().ffill().bfill()
        except: pass
            
        # [補救機制] 若下載失敗或數據過短
        if df.empty or len(df) < 50:
            print(f"⚠️ {symbol_raw} 數據異常，啟動二次抓取...")
            try:
                df = yf.download(symbol_raw, start=start_str, progress=False, auto_adjust=True).ffill().bfill()
            except: pass
        
        if not df.empty and len(df) >= 20:
            df['SMA_60'] = df['Close'].rolling(60).mean()
            df['SMA_140'] = df['Close'].rolling(140).mean()
            df['Ret_20'] = df['Close'].pct_change(20)
            data_map[symbol] = df
        elif symbol != 'VIX':
            missing_coins.append(symbol)

    if 'BTC' not in data_map:
        raise Exception("❌ 無法獲取 BTC 數據，無法繼續分析。")

    today = data_map['BTC'].index[-1]
    vix = data_map['VIX'].loc[today]['Close'] if 'VIX' in data_map else 20
    row_btc = data_map['BTC'].loc[today]
    row_eth = data_map['ETH'].loc[today]
    bull_btc = row_btc['Close'] > row_btc['SMA_140']
    
    # 衛星掃描
    candidates = []
    for sym, sec in ticker_to_sector.items():
        if sym not in data_map: continue
        r = data_map[sym].loc[today]
        
        # [核心修復] 嚴格檢查數據有效性，排除 NaN
        if pd.isna(r['Ret_20']):
            if sym not in missing_coins: missing_coins.append(sym)
            continue
            
        is_valid = r['Close'] > r['SMA_60'] and r['Ret_20'] > row_btc['Ret_20']
        candidates.append({'sym': sym, 'score': r['Ret_20'], 'sector': sec, 'valid': is_valid})
    
    # 排序動能
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    # 挑選雙星 (軟性板塊懲罰)
    top_targets = []
    valid_cands = [c for c in candidates if c['valid']]
    if valid_cands:
        top_targets.append(valid_cands[0])
        if len(valid_cands) > 1:
            f_sec = valid_cands[0]['sector']
            challengers = sorted([{**c, 'adj': c['score']*0.8 if c['sector']==f_sec else c['score']} for c in valid_cands[1:]], key=lambda x: x['adj'], reverse=True)
            top_targets.append(challengers[0])

    # 計算分配
    tw = {'BTC': 0.0, 'ETH': 0.0, 'SAT1': 0.0, 'SAT2': 0.0}
    ss = {'SAT1': 'NONE', 'SAT2': 'NONE'}

    if vix < 30 and bull_btc:
        sat_alloc = 0.20
        core_alloc = 0.80
        # Sentinel 核心切換
        if row_eth['Ret_20'] > row_btc['Ret_20'] and row_eth['Close'] > row_eth['SMA_140']:
            tw['BTC'], tw['ETH'] = core_alloc * 0.5, core_alloc * 0.5
        else:
            tw['BTC'], tw['ETH'] = core_alloc * 0.75, core_alloc * 0.25
        
        for i, t in enumerate(top_targets):
            key = f'SAT{i+1}'
            tw[key] = sat_alloc / 2
            ss[key] = t['sym']

    return tw, ss, vix, bull_btc, candidates[:5], missing_coins, today

# ==========================================
# 2. 戰報生成 (修正 NaN 顯示)
# ==========================================
def generate_report():
    tw, ss, vix, is_bull, ranking, missing, dt = analyze_market()
    total_eq = USER_ACCOUNT['TOTAL_EQUITY_USDT']
    
    msg = f"🛡️ V44 Master Baseline 戰報\n"
    msg += f"📅 日期: {dt.strftime('%Y-%m-%d')}\n"
    msg += f"🌍 環境: {'🟢進攻' if is_bull else '🛡️避險'} | VIX: {vix:.1f}\n"
    msg += "-" * 22 + "\n"

    items = [
        ('BTC', USER_ACCOUNT['CURRENT_BTC_W'], tw['BTC'], 'NONE'),
        ('ETH', USER_ACCOUNT['CURRENT_ETH_W'], tw['ETH'], 'NONE'),
        ('衛星1', USER_ACCOUNT['CURRENT_SAT_1_W'], tw['SAT1'], USER_ACCOUNT['CURRENT_SAT_1_SYM']),
        ('衛星2', USER_ACCOUNT['CURRENT_SAT_2_W'], tw['SAT2'], USER_ACCOUNT['CURRENT_SAT_2_SYM'])
    ]

    for name, curr, target, held_sym in items:
        display_name = name
        target_sym = ss['SAT1'] if '1' in name else ss['SAT2'] if '2' in name else 'NONE'
        if '衛星' in name: display_name = f"衛星: {target_sym}"
        
        diff = target - curr
        action = "✅ 續抱"
        if target == 0 and curr > 0.01: action = "🚨 立即清倉"
        elif "衛星" in display_name:
            if target_sym != "NONE" and target_sym != held_sym: action = f"🔄 換至 {target_sym}"
            elif abs(diff) > REBALANCE_THRESHOLD: action = f"🔔 建議調整"
        elif abs(diff) > REBALANCE_THRESHOLD: action = f"🔔 建議調整"
            
        msg += f"{display_name}\n"
        msg += f"   目標: {target*100:.1f}% | 動作: {action}\n"
        if action != "✅ 續抱":
            msg += f"   👉 預計變動: ${diff * total_eq:>+8.1f} USDT\n"

    msg += "-" * 22 + "\n"
    
    # 動能排行榜 (排除 NaN)
    msg += f"📊 [動能排行榜 (Ret20)]\n"
    for c in ranking:
        # [再次檢查] 確保不列印 NaN
        if pd.isna(c['score']): continue
        star = "👑" if c['sym'] in [ss['SAT1'], ss['SAT2']] else ""
        valid = "✅" if c['valid'] else "❌"
        msg += f"{valid} {c['sym']}: {c['score']*100:+.1f}% {star}\n"
    
    if missing:
        msg += f"\n⚠️ 注意：以下幣種數據不完整，暫不列入排名：{', '.join(missing)}\n"
    
    msg += "-" * 22 + "\n"
    
    # 半年提醒
    days_to_update = (UPDATE_DEADLINE - dt.to_pydatetime().replace(tzinfo=None)).days
    msg += f"💡 更新提醒：距離半年檢修剩 {days_to_update} 天。\n"
    msg += f"👉 叮嚀: 目前門檻 5%，領 Pendle 利息保護複利。"
    
    return msg

if __name__ == "__main__":
    try:
        report_text = generate_report()
        send_line_push(report_text)
    except Exception as e:
        err_msg = f"❌ 執行錯誤: {str(e)}"
        print(err_msg)
        send_line_push(err_msg)
