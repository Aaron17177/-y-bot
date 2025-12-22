# ==========================================
# Gemini V44 Hyper: Accumulation Engine (Platinum Edition)
# ------------------------------------------
# [戰略目標]
# 鎖定回測績效最高 (+14490%) 的「鉑金 16 支候選池」。
#
# [核心配置]
# 1. 核心 (80%): BTC + ETH (SMA 140)
# 2. 衛星 (20%): 冠軍輪動 (Platinum 16)
#    - 名單: SOL, AVAX, BNB, DOGE, SHIB, RNDR, INJ, SUI, ADA, 
#           TRX, XLM, BCH, ZEC, LTC, ETC, MATIC
#    - 邏輯: 站上 SMA 60 + 20日漲幅最強
#    - 換倉: 挑戰者動能 > 現任 + 15% (防抖動)
#
# [系統功能]
# 1. LINE Messaging API 推播 (API Push)
# 2. 支援 GitHub Secrets
# 3. 修正: Colorama Style.RESET 錯誤
# ==========================================

import os
import sys
import requests
import json
import warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

# ==========================================
# 0. 環境檢查與 LINE 設定 (Messaging API)
# ==========================================
print("="*50)
print("🔍 V44 鉑金系統啟動...")

# 讀取 GitHub Secrets
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

# 本地測試用 (上傳 GitHub 前請保持為空)
LOCAL_TOKEN = ''
LOCAL_USER_ID = ''

FINAL_TOKEN = LINE_CHANNEL_ACCESS_TOKEN if LINE_CHANNEL_ACCESS_TOKEN else LOCAL_TOKEN
FINAL_USER_ID = LINE_USER_ID if LINE_USER_ID else LOCAL_USER_ID

if FINAL_TOKEN and FINAL_USER_ID:
    print(f"✅ LINE 金鑰讀取成功")
else:
    print("❌ 警告：未檢測到 LINE 金鑰！(請檢查 GitHub Secrets)")

def send_line_push(msg):
    if not FINAL_TOKEN or not FINAL_USER_ID:
        print("⚠️ 跳過發送：金鑰不完整")
        return

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {FINAL_TOKEN}'
    }
    payload = {
        "to": FINAL_USER_ID,
        "messages": [{"type": "text", "text": msg}]
    }
    
    try:
        print("📤 正在推送 LINE 訊息...")
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("✅ 發送成功！")
        else:
            print(f"❌ 發送失敗: {response.status_code} {response.text}")
    except Exception as e:
        print(f"❌ 網絡錯誤: {e}")

# 自動安裝依賴
try:
    import yfinance as yf
except ImportError:
    print("📦 安裝 yfinance...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance"])
    import yfinance as yf

try:
    from colorama import Fore, Style, init
    init(autoreset=True)
except:
    # 兼容模式：若無 colorama 則定義空類別
    class Fore: RED=GREEN=YELLOW=CYAN=MAGENTA=WHITE=RESET=""
    class Style: BRIGHT=RESET_ALL=""

# ==========================================
# ⚙️ 用戶設定
# ==========================================
USER_CONFIG = {
    'CURRENT_ASSETS': 3000000,  # 目前總資產 (TWD)
    'TARGET_WEALTH': 20000000,  # 目標金額 (TWD)
    
    # [重要] 請填寫您「目前持有」的衛星幣種代號
    # 範例: 'SOL', 'SHIB' 或 'NONE' (若空倉)
    'CURRENT_HOLDING_SAT': 'NONE',

    'PENDLE_INTEREST_ACC': 5000 # 累積利息
}

# 衛星候選池 (Platinum 16 - 創造 +14490% 的組合)
SATELLITE_POOL = {
    # --- 攻擊型公鏈 ---
    'SOL': 'SOL-USD', 'AVAX': 'AVAX-USD', 'BNB': 'BNB-USD',
    'SUI': 'SUI-USD', 'ADA': 'ADA-USD',
    
    # --- 迷因雙雄 ---
    'DOGE': 'DOGE-USD', 'SHIB': 'SHIB-USD',
    
    # --- AI / RWA / DeFi ---
    'RNDR': 'RNDR-USD', 'INJ': 'INJ-USD',
    
    # --- 補漲型老幣 & L2 ---
    'TRX': 'TRX-USD', 'XLM': 'XLM-USD', 'BCH': 'BCH-USD', 'ZEC': 'ZEC-USD',
    'LTC': 'LTC-USD', 'ETC': 'ETC-USD', 'MATIC': 'MATIC-USD'
}

STRATEGY_PARAMS = {
    'SMA_CORE': 140,     # 核心 (BTC/ETH)
    'SMA_SATELLITE': 60, # 衛星 (輪動)
    'VIX_PANIC': 30,
    'MAYER_GREED': 2.4,
    'RSI_SNIPER': 45,
    'SWITCH_THRESHOLD': 0.15 # 換倉門檻 15%
}

# ==========================================
# 1. 數據引擎
# ==========================================
def fetch_data():
    print(f"\n{Fore.CYAN}📥 正在掃描鉑金候選池 (Top 16)...{Style.RESET_ALL}")
    tickers = ['BTC-USD', 'ETH-USD', '^VIX'] + list(SATELLITE_POOL.values())
    start_date = (datetime.now() - timedelta(days=500)).strftime('%Y-%m-%d')
    try:
        data = yf.download(tickers, start=start_date, group_by='ticker', progress=False)
    except:
        sys.exit()
    return data

def process_data(raw_data):
    data_map = {}
    ticker_to_symbol = {'BTC-USD': 'BTC', 'ETH-USD': 'ETH', '^VIX': 'VIX'}
    for k, v in SATELLITE_POOL.items(): ticker_to_symbol[v] = k
    
    # 處理 MultiIndex
    if isinstance(raw_data.columns, pd.MultiIndex):
        level_0_cols = raw_data.columns.levels[0]
    else:
        return {} # 格式不符

    for ticker in level_0_cols:
        symbol = ticker_to_symbol.get(ticker)
        if not symbol: continue
        
        df = pd.DataFrame()
        try: df['Close'] = raw_data[ticker]['Close']
        except: continue
        
        if df['Close'].isnull().all(): continue
        df.ffill(inplace=True)
        
        df['SMA_140'] = df['Close'].rolling(window=140).mean()
        df['SMA_60'] = df['Close'].rolling(window=60).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df['Mayer'] = df['Close'] / df['SMA_200']
        df['Ret_20'] = df['Close'].pct_change(20)
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))

        data_map[symbol] = df
        
    return data_map

# ==========================================
# 2. 策略邏輯 (含輪動機制)
# ==========================================
def analyze_market(data_map):
    status = {}
    if 'BTC' not in data_map: return {}, None
    today = data_map['BTC'].index[-1]
    
    try: vix = data_map['VIX'].loc[today]['Close']
    except: vix = 20.0
    status['VIX'] = vix
    status['IS_PANIC'] = vix > STRATEGY_PARAMS['VIX_PANIC']
    
    # 核心部位
    btc_row = data_map['BTC'].loc[today]
    is_btc_bull = btc_row['Close'] > btc_row['SMA_140']
    
    for coin in ['BTC', 'ETH']:
        row = data_map[coin].loc[today]
        price = row['Close']
        sma = row['SMA_140']
        mayer = row['Mayer']
        rsi = row['RSI']
        
        signal = "HOLD"
        action_short = "持有"
        target_pct = 0.0
        
        if status['IS_PANIC']:
            signal = "ESCAPE (0%)"
            action_short = "清倉"
        elif mayer > STRATEGY_PARAMS['MAYER_GREED']:
            signal = "TRIM (50%)"
            action_short = "減倉"
            target_pct = 0.5
        elif price > sma:
            signal = "BUY (100%)"
            action_short = "滿倉"
            target_pct = 1.0
        else:
            signal = "SELL (0%)"
            action_short = "空倉"
            
        status[coin] = {'Price': price, 'SMA': sma, 'Signal': signal, 'ActionShort': action_short, 'TargetPct': target_pct, 'RSI': rsi}

    # --- 衛星部位 (Rotator) ---
    current_holding = USER_CONFIG['CURRENT_HOLDING_SAT']
    candidates = []
    
    for coin in SATELLITE_POOL.keys():
        if coin not in data_map: continue
        try:
            row = data_map[coin].loc[today]
            score = row['Ret_20']
            price = row['Close']
            sma60 = row['SMA_60']
            
            is_valid = price > sma60
            candidates.append({'Coin': coin, 'Score': score, 'Valid': is_valid, 'Price': price})
        except: pass
    
    candidates.sort(key=lambda x: x['Score'], reverse=True)
    
    final_choice = "NONE"
    reason = ""
    action = "EMPTY"
    action_short = "空倉"
    
    current_status = next((c for c in candidates if c['Coin'] == current_holding), None)
    challenger = candidates[0] if candidates else None
    
    if status['IS_PANIC']:
        reason = "VIX 恐慌，衛星清倉"
        action = "CLEAR"
        action_short = "清倉"
    elif not is_btc_bull:
        reason = "BTC 熊市，衛星清倉"
        action = "CLEAR"
        action_short = "清倉"
    elif not challenger or not challenger['Valid']:
        reason = "無幣種站上 SMA60 (全體弱勢)"
        action = "CLEAR"
        action_short = "空倉"
    else:
        threshold = STRATEGY_PARAMS['SWITCH_THRESHOLD']
        
        if current_holding == 'NONE' or current_holding not in SATELLITE_POOL:
            final_choice = challenger['Coin']
            reason = f"空手進場，買入最強: {challenger['Coin']}"
            action = f"BUY {challenger['Coin']}"
            action_short = f"買入 {challenger['Coin']}"
        elif not current_status or not current_status['Valid']:
            final_choice = challenger['Coin']
            reason = f"現任 {current_holding} 失效，換至 {challenger['Coin']}"
            action = f"SWITCH -> {challenger['Coin']}"
            action_short = f"換倉 {challenger['Coin']}"
        else:
            score_diff = challenger['Score'] - current_status['Score']
            if score_diff > threshold:
                final_choice = challenger['Coin']
                reason = f"挑戰者 {challenger['Coin']} 強於 {current_holding} {(score_diff*100):.1f}% (>15%)"
                action = f"SWITCH -> {challenger['Coin']}"
                action_short = f"換倉 {challenger['Coin']}"
            else:
                final_choice = current_holding
                reason = f"續抱 {current_holding} (挑戰者未領先 15%)"
                action = f"HOLD {current_holding}"
                action_short = f"持有 {current_holding}"

    status['SATELLITE'] = {
        'Choice': final_choice,
        'Action': action,
        'ActionShort': action_short,
        'Reason': reason,
        'Top3': candidates[:3]
    }
    
    return status, today

# ==========================================
# 2. 紀律提醒模組
# ==========================================
def get_discipline_msg(status):
    msg = ""
    if status['IS_PANIC']:
        msg += "⚠️ 市場恐慌 (VIX>30)，請相信系統，持有現金，勿手動接刀！"
    elif any(status[c]['Mayer'] > STRATEGY_PARAMS['MAYER_GREED'] for c in ['BTC', 'ETH']):
        msg += "🤑 市場過熱 (Mayer>2.4)，請執行減倉鎖住利潤。"
    else:
        msg += "1. 衛星部位嚴守 20% 上限。\n"
        msg += "2. 新幣動能 > 現持倉 + 15% 才換倉。\n"
        msg += "3. 專注本業，加大本金，目標 2000 萬。"
    return msg

# ==========================================
# 3. 訊息生成
# ==========================================
def generate_report(status, today_date):
    date_str = today_date.strftime('%Y-%m-%d')
    assets = USER_CONFIG['CURRENT_ASSETS']
    sat = status['SATELLITE']
    
    # 懶人包
    interest_action = "無"
    if status['BTC']['TargetPct'] == 0 and status['BTC']['RSI'] < 45:
        interest_action = "🔥 買入 BTC+ETH"
    elif status['BTC']['TargetPct'] == 0:
        interest_action = "💤 滾存利息"
    else:
        interest_action = "💪 專注本金"

    msg = f"📋 {date_str} 鉑金輪動懶人包\n"
    msg += f"-------------------------\n"
    msg += f"🟠 BTC: {status['BTC']['ActionShort']}\n"
    msg += f"🔵 ETH: {status['ETH']['ActionShort']}\n"
    msg += f"🚀 衛星: {sat['ActionShort']}\n"
    msg += f"💵 利息: {interest_action}\n"
    msg += f"-------------------------\n\n"
    
    msg += f"🏆 V44 Platinum 戰情室\n"
    msg += f"=========================\n"
    msg += f"資產: ${assets/10000:.0f}萬\n"
    
    vix = status['VIX']
    vix_state = "🔴恐慌" if status['IS_PANIC'] else "🟢安全"
    msg += f"環境: VIX {status['VIX']:.1f} ({vix_state})\n"
    msg += "-" * 20 + "\n"
    
    for c in ['BTC', 'ETH']:
        s = status[c]
        msg += f"{c}: ${s['Price']:.0f} (MA ${s['SMA']:.0f})\n"
        msg += f"👉 {s['Signal']}\n"
    msg += "-" * 20 + "\n"
    
    msg += f"🌟 衛星冠軍: {sat['Choice']}\n"
    msg += f"👉 指令: {sat['Action']}\n"
    msg += f"👉 理由: {sat['Reason']}\n\n"
    
    msg += f"[動能排行榜 (Ret20)]\n"
    for c in sat['Top3']:
        star = "👑" if c['Coin'] == sat['Choice'] else ""
        valid = "✅" if c['Valid'] else "❌"
        msg += f"{valid} {c['Coin']}: {c['Score']*100:+.1f}% {star}\n"
        
    msg += f"\n💡 紀律:\n"
    msg += get_discipline_msg(status)
    msg += f"\n👉 目前持有設定: {USER_CONFIG['CURRENT_HOLDING_SAT']}\n"
    
    return msg

# ==========================================
# 4. 戰情儀表板 (Console Preview)
# ==========================================
def print_dashboard_preview(msg):
    print("\n" + msg)

# ==========================================
# 主程式
# ==========================================
if __name__ == "__main__":
    try:
        raw = fetch_data()
        processed = process_data(raw)
        if processed and 'BTC' in processed:
            stat, today = analyze_market(processed)
            line_msg = generate_report(stat, today)
            print_dashboard_preview(line_msg)
            send_line_push(line_msg)
        else:
            print("❌ 無法獲取數據")
    except Exception as e:
        print(f"❌ 錯誤: {e}")
