# ==========================================
# Gemini V44 Hyper: Accumulation Engine (Messaging API Edition)
# ------------------------------------------
# [修正說明]
# 1. 訊息開頭新增「📋 今日操作懶人包」。
# 2. 增加詳細的 LINE 金鑰診斷功能。
# 3. 專為 GitHub Actions 優化：優先讀取 Secrets，無需在程式碼填寫金鑰。
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
# 0. 環境檢查與 LINE 設定 (診斷模式)
# ==========================================
print("="*50)
print("🔍 V44 系統啟動自我診斷...")

# 1. 嘗試從 GitHub Secrets (環境變數) 讀取
# 只要您在 GitHub 設定好 Secrets，程式就會自動抓到這裡，不需要手動填寫
env_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
env_userid = os.environ.get('LINE_USER_ID')

# 2. 本地測試備用 (僅限在自己電腦執行時使用)
# ⚠️ 注意：上傳到 GitHub 時，請保持以下兩行為空字串 ''，不要填寫！
LOCAL_TOKEN = ''
LOCAL_USER_ID = ''

# 決定最終使用的金鑰 (優先使用 GitHub Secrets)
FINAL_TOKEN = env_token if env_token else LOCAL_TOKEN
FINAL_USER_ID = env_userid if env_userid else LOCAL_USER_ID

# --- 診斷報告 ---
print(f"1. 檢查 Channel Access Token...")
if FINAL_TOKEN:
    # 隱藏中間部分，只顯示前後碼以供確認
    masked = FINAL_TOKEN[:4] + "..." + FINAL_TOKEN[-4:] if len(FINAL_TOKEN) > 8 else "***"
    print(f"   ✅ Token 已載入 ({masked})")
    if env_token:
        print("      (來源: GitHub Secrets)")
    else:
        print("      (來源: 本地設定)")
else:
    print(f"   ❌ Token 未找到！")
    print("      請確認 GitHub Secrets 名稱是否為 'LINE_CHANNEL_ACCESS_TOKEN'")

print(f"2. 檢查 User ID...")
if FINAL_USER_ID:
    masked_uid = FINAL_USER_ID[:4] + "..." + FINAL_USER_ID[-4:] if len(FINAL_USER_ID) > 8 else "***"
    print(f"   ✅ User ID 已載入 ({masked_uid})")
    if env_userid:
        print("      (來源: GitHub Secrets)")
    else:
        print("      (來源: 本地設定)")
else:
    print(f"   ❌ User ID 未找到！")
    print("      請確認 GitHub Secrets 名稱是否為 'LINE_USER_ID'")

def send_line_push(msg):
    if not FINAL_TOKEN or not FINAL_USER_ID:
        print("\n⚠️ [取消發送] 金鑰不完整，無法發送 LINE 通知。")
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
        print("\n📤 正在推送 LINE 訊息...")
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("✅ 發送成功！請檢查手機。")
        else:
            print(f"❌ 發送失敗！狀態碼: {response.status_code}")
            print(f"   回應: {response.text}")
            print("   (可能是 Token 過期或 User ID 錯誤)")
    except Exception as e:
        print(f"❌ 網絡錯誤: {e}")

# 自動安裝依賴
try:
    import yfinance as yf
except ImportError:
    print("📦 正在安裝必要套件 (yfinance)...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance"])
    import yfinance as yf

try:
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)
except ImportError:
    class Fore: RED=GREEN=YELLOW=CYAN=MAGENTA=WHITE=RESET=""
    class Style: BRIGHT=RESET=""

# ==========================================
# ⚙️ 用戶資產設定
# ==========================================
USER_CONFIG = {
    'CURRENT_ASSETS': 3000000,  
    'TARGET_WEALTH': 20000000,  
    'PENDLE_INTEREST_ACC': 5000 
}

STRATEGY_PARAMS = {
    'SMA_TREND': 140,
    'SMA_MAYER': 200,
    'VIX_PANIC': 30,
    'MAYER_GREED': 2.4,
    'RSI_SNIPER': 45
}

# ==========================================
# 1. 數據引擎
# ==========================================
def fetch_data():
    print(f"\n{Fore.CYAN}📥 正在連線全球數據庫...{Style.RESET}")
    tickers = ['BTC-USD', 'ETH-USD', 'SOL-USD', '^VIX']
    start_date = (datetime.now() - timedelta(days=500)).strftime('%Y-%m-%d')
    try:
        data = yf.download(tickers, start=start_date, group_by='ticker', progress=False)
    except Exception as e:
        print(f"{Fore.RED}❌ 數據下載失敗: {e}{Style.RESET}")
        sys.exit()
    return data

def process_data(raw_data):
    data_map = {}
    tickers_map = {'BTC': 'BTC-USD', 'ETH': 'ETH-USD', 'SOL': 'SOL-USD', 'VIX': '^VIX'}
    
    for symbol, ticker in tickers_map.items():
        df = pd.DataFrame()
        try:
            if ticker in raw_data.columns.levels[0]:
                df['Close'] = raw_data[ticker]['Close']
            elif ticker == 'BTC-USD': 
                 if 'Close' in raw_data.columns: df['Close'] = raw_data['Close']
        except: pass
            
        if df.empty: continue
        df.ffill(inplace=True)
        
        df['SMA_140'] = df['Close'].rolling(window=140).mean()
        df['SMA_200'] = df['Close'].rolling(window=200).mean()
        df['Mayer'] = df['Close'] / df['SMA_200']
        
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        data_map[symbol] = df
    return data_map

# ==========================================
# 2. 核心策略邏輯
# ==========================================
def analyze_market(data_map):
    status = {}
    today = data_map['BTC'].index[-1]
    
    try: vix = data_map['VIX'].loc[today]['Close']
    except: vix = 20.0
    status['VIX'] = vix
    status['IS_PANIC'] = vix > STRATEGY_PARAMS['VIX_PANIC']
    
    btc_row = data_map['BTC'].loc[today]
    is_btc_bull = btc_row['Close'] > btc_row['SMA_140']
    
    coins_config = {
        'BTC': {'name': 'Bitcoin', 'weight': 0.40, 'role': '核心'},
        'ETH': {'name': 'Ethereum', 'weight': 0.40, 'role': '核心'},
        'SOL': {'name': 'Solana', 'weight': 0.20, 'role': '衛星'}
    }

    for coin in ['BTC', 'ETH', 'SOL']:
        row = data_map[coin].loc[today]
        price = row['Close']
        sma = row['SMA_140']
        mayer = row['Mayer']
        rsi = row['RSI']
        
        signal_text = "HOLD"
        target_pct = 0.0
        reason = ""
        action_short = "持有"
        
        if status['IS_PANIC']:
            signal_text = "🌪️ 恐慌避險 (0%)"
            action_short = "清倉"
            target_pct = 0.0
            reason = f"VIX ({vix:.2f}) > 30，系統性風險"
            
        elif coin == 'SOL' and not is_btc_bull:
            signal_text = "🛑 聯動避險 (0%)"
            action_short = "清倉"
            target_pct = 0.0
            reason = "BTC 轉入熊市，強制空倉保護"
            
        elif mayer > STRATEGY_PARAMS['MAYER_GREED']:
            signal_text = "⚠️ 過熱減碼 (50%)"
            action_short = "減倉"
            target_pct = 0.5
            reason = f"Mayer ({mayer:.2f}) > 2.4，鎖定利潤"
            
        elif price > sma:
            signal_text = "🚀 趨勢持有 (100%)"
            action_short = "滿倉"
            target_pct = 1.0
            reason = "Price > SMA140"
            
        else: 
            if rsi < STRATEGY_PARAMS['RSI_SNIPER']: 
                signal_text = "🛑 空倉觀望 (0%)"
                action_short = "空倉"
                target_pct = 0.0
                reason = f"Price < SMA140 (RSI {rsi:.1f} 超賣)"
            else:
                signal_text = "🛑 空倉觀望 (0%)"
                action_short = "空倉"
                target_pct = 0.0
                reason = "Price < SMA140"
            
        status[coin] = {
            'Name': coins_config[coin]['name'],
            'Role': coins_config[coin]['role'],
            'BaseWeight': coins_config[coin]['weight'],
            'Price': price, 
            'SMA_140': sma, 
            'Mayer': mayer,
            'RSI': rsi, 
            'SignalText': signal_text, 
            'ActionShort': action_short,
            'TargetPct': target_pct,
            'Reason': reason
        }
        
    return status, today

# ==========================================
# 3. 訊息生成 (Report Generator)
# ==========================================
def generate_report(status, today_date):
    assets = USER_CONFIG['CURRENT_ASSETS']
    target = USER_CONFIG['TARGET_WEALTH']
    date_str = today_date.strftime('%Y-%m-%d')
    
    # 懶人包區塊
    interest_action = "無"
    is_bear_btc = status['BTC']['TargetPct'] == 0
    btc_rsi = status['BTC']['RSI']
    
    if is_bear_btc:
        trigger = STRATEGY_PARAMS['RSI_SNIPER']
        if btc_rsi < trigger:
            interest_action = "🔥 買入 BTC+ETH"
        else:
            interest_action = "💤 滾存利息"
    else:
        interest_action = "💪 專注本金"

    msg = f"📋 {date_str} 操作懶人包\n"
    msg += f"-------------------------\n"
    msg += f"🟠 BTC: {status['BTC']['ActionShort']}\n"
    msg += f"🔵 ETH: {status['ETH']['ActionShort']}\n"
    msg += f"🟣 SOL: {status['SOL']['ActionShort']}\n"
    msg += f"💵 利息: {interest_action}\n"
    msg += f"-------------------------\n\n"
    
    msg += f"🏆 V44 三核戰情室詳情\n"
    msg += f"=========================\n"
    
    total_allocation = 0.0
    
    # 幣種詳情
    icons = {'BTC': '🟠', 'ETH': '🔵', 'SOL': '🟣'}
    
    for coin in ['BTC', 'ETH', 'SOL']:
        s = status[coin]
        icon = icons[coin]
        weight_display = int(s['BaseWeight'] * 100)
        actual_alloc = s['BaseWeight'] * s['TargetPct']
        total_allocation += actual_alloc
        
        msg += f"{icon} [{s['Name']}] ({s['Role']} {weight_display}%)\n"
        msg += f"   ${s['Price']:,.0f} (均線 ${s['SMA_140']:,.0f})\n"
        msg += f"   指令: {s['SignalText']}\n"
        msg += f"   理由: {s['Reason']}\n\n"
        
    cash_allocation = 1.0 - total_allocation
    
    # 資產配置
    msg += f"-------------------------\n"
    msg += f"💼 [總資產建議配置]\n"
    msg += f"   🟠 BTC : {status['BTC']['BaseWeight']*status['BTC']['TargetPct']*100:>4.1f}%\n"
    msg += f"   🔵 ETH : {status['ETH']['BaseWeight']*status['ETH']['TargetPct']*100:>4.1f}%\n"
    msg += f"   🟣 SOL : {status['SOL']['BaseWeight']*status['SOL']['TargetPct']*100:>4.1f}%\n"
    msg += f"   🟢 Cash: {cash_allocation*100:>4.1f}%\n"
    msg += f"-------------------------\n\n"
    
    # 利息操作提醒
    msg += f"💡 利息 Smart DCA:\n"
    if is_bear_btc:
        trigger = STRATEGY_PARAMS['RSI_SNIPER']
        if btc_rsi < trigger:
            msg += f"🔥 [觸發!] BTC RSI {btc_rsi:.1f} < {trigger}\n"
            msg += f"👉 提領 Pendle 利息買入 BTC/ETH (各半)！累積便宜籌碼。\n"
        else:
            msg += f"💤 [等待] BTC RSI {btc_rsi:.1f} (> {trigger})\n"
            msg += f"👉 價格不夠甜，利息繼續滾存。\n"
    else:
        msg += f"💪 牛市中，利息暫無操作。\n"

    # 紀律提醒
    msg += f"\n💡 紀律提醒:\n"
    if status['IS_PANIC']:
        msg += "⚠️ 市場恐慌，請嚴格執行空倉，勿接刀！\n"
    elif any(s['ActionShort'] == "減倉" for s in status.values()):
        msg += "🤑 市場過熱，分批止盈是為了走更長的路。\n"
    else:
        msg += "1. SOL 波動大，嚴格遵守 20% 上限。\n"
        msg += "2. 熊市紀律：BTC 轉空時，SOL 必須清倉。\n"
    
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
