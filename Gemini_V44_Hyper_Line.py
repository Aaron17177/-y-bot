# ==========================================
# Gemini V44 Hyper: Accumulation Engine (Messaging API Edition)
# ------------------------------------------
# [修正說明]
# 1. 改用 LINE Messaging API (Push Message) 發送通知，解決收不到訊息的問題。
# 2. 透過 os.environ 讀取 GitHub Secrets (LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID)。
# 3. 保留 V44 Hyper 核心策略與 Smart DCA 邏輯。
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
print("🔍 V44 系統啟動自我診斷 (Messaging API)...")

# 讀取 GitHub Secrets
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

# 本地測試用 (如果在本地跑，請填入您的 Token/ID，上傳 GitHub 前請清空)
LOCAL_TOKEN = ''
LOCAL_USER_ID = ''

if not LINE_CHANNEL_ACCESS_TOKEN and LOCAL_TOKEN:
    LINE_CHANNEL_ACCESS_TOKEN = LOCAL_TOKEN
if not LINE_USER_ID and LOCAL_USER_ID:
    LINE_USER_ID = LOCAL_USER_ID

if LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID:
    print(f"✅ Token 讀取成功: {LINE_CHANNEL_ACCESS_TOKEN[:5]}...")
    print(f"✅ UserID 讀取成功: {LINE_USER_ID[:5]}...")
else:
    print("❌ 警告：未檢測到 LINE 金鑰！將無法發送通知。")
    print("   請確認 GitHub Secrets: 'LINE_CHANNEL_ACCESS_TOKEN' 與 'LINE_USER_ID'")

def send_line_push(msg):
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 跳過發送：金鑰不完整")
        return

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    payload = {
        "to": LINE_USER_ID,
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
    'CURRENT_ASSETS': 3000000,  # 目前總資產 (TWD)
    'TARGET_WEALTH': 20000000,  # 目標金額 (TWD)
    'PENDLE_INTEREST_ACC': 5000 # 累積未投入的利息 (TWD)
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
    print(f"\n{Fore.CYAN}📥 正在連線全球數據庫 (BTC/ETH/SOL/VIX)...{Style.RESET}")
    tickers = ['BTC-USD', 'ETH-USD', 'SOL-USD', '^VIX']
    # 抓取 500 天數據以確保 SMA 計算正確
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

def analyze_market(data_map):
    status = {}
    today = data_map['BTC'].index[-1]
    
    try: vix = data_map['VIX'].loc[today]['Close']
    except: vix = 20.0
    status['VIX'] = vix
    status['IS_PANIC'] = vix > STRATEGY_PARAMS['VIX_PANIC']
    
    for coin in ['BTC', 'ETH', 'SOL']:
        row = data_map[coin].loc[today]
        price = row['Close']
        sma = row['SMA_140']
        mayer = row['Mayer']
        rsi = row['RSI']
        
        signal = "HOLD"
        detail = ""
        action_code = 0
        
        if status['IS_PANIC']:
            signal = "ESCAPE (Cash)"
            detail = "VIX > 30 恐慌逃生"
            action_code = -1
        elif mayer > STRATEGY_PARAMS['MAYER_GREED']:
            signal = "TRIM (50%)"
            detail = "Mayer 過熱減倉"
            action_code = -1
        elif price > sma:
            signal = "BUY/HOLD (100%)"
            detail = "趨勢向上"
            action_code = 1
        else:
            signal = "SELL (0%)"
            detail = "趨勢向下"
            action_code = -1
            
        status[coin] = {
            'Price': price, 'SMA_140': sma, 'Mayer': mayer,
            'RSI': rsi, 'Signal': signal, 'Detail': detail, 'Action': action_code
        }
    return status, today

# ==========================================
# 2. 紀律提醒模組
# ==========================================
def print_discipline(status):
    print(f"\n{Fore.CYAN}🧘 V44 交易心理與紀律提醒 (Mindset Check):{Style.RESET}")
    if status['IS_PANIC']:
        print(f"   ⚠️  {Fore.RED}檢測到市場極度恐慌 (VIX > 30){Style.RESET}")
        return "\n⚠️ 市場極度恐慌 (VIX > 30)，請相信系統持有現金，勿手動接刀。"
    
    is_greed = any(status[c]['Mayer'] > STRATEGY_PARAMS['MAYER_GREED'] for c in ['BTC', 'ETH', 'SOL'])
    if is_greed:
        print(f"   🤑 {Fore.YELLOW}檢測到市場過熱 (Mayer > 2.4){Style.RESET}")
        return "\n🤑 市場過熱 (Mayer > 2.4)，請執行減倉鎖住利潤。"
        
    is_choppy = any(abs(status[c]['Price'] - status[c]['SMA_140']) / status[c]['SMA_140'] < 0.02 for c in ['BTC', 'ETH', 'SOL'])
    if is_choppy:
        print(f"   😴 {Fore.WHITE}檢測到趨勢不明確{Style.RESET}")
        return "\n😴 趨勢不明確，忍受無聊，不要亂動。"
        
    print(f"   🌱 {Fore.GREEN}市場處於正常波動範圍{Style.RESET}")
    return "\n🌱 市場正常波動，專注本業加大本金，目標 2000 萬。"

# ==========================================
# 3. 訊息生成與主程式
# ==========================================
def generate_report(status, today_date):
    assets = USER_CONFIG['CURRENT_ASSETS']
    target = USER_CONFIG['TARGET_WEALTH']
    progress = (assets / target) * 100
    date_str = today_date.strftime('%Y-%m-%d')
    
    # 組合訊息
    msg = f"🚀 V44 Hyper 累積戰報 ({date_str})\n"
    msg += f"========================\n"
    msg += f"💰 資產: ${assets/10000:.0f}萬 ({progress:.1f}%)\n"
    
    vix = status['VIX']
    vix_state = "🔴恐慌!" if status['IS_PANIC'] else "🟢安全"
    msg += f"🌍 環境: VIX {vix:.1f} ({vix_state})\n"
    msg += f"------------------------\n"
    
    # 幣種指令
    for coin in ['BTC', 'ETH', 'SOL']:
        s = status[coin]
        icon = "🟢" if s['Action'] == 1 else ("🔴" if s['Action'] == -1 else "🟡")
        trend = "及格" if s['Price'] > s['SMA_140'] else "破線"
        msg += f"{icon} {coin}: ${s['Price']:.0f} ({trend})\n"
        msg += f"   指令: {s['Signal']}\n"
    
    msg += f"------------------------\n"
    
    # 利息操作 (Smart DCA)
    is_bear = status['BTC']['Action'] == -1
    if is_bear:
        btc_rsi = status['BTC']['RSI']
        trigger = STRATEGY_PARAMS['RSI_SNIPER']
        if btc_rsi < trigger:
            msg += f"🔥 [Smart DCA 觸發!]\n"
            msg += f"BTC RSI {btc_rsi:.1f} < {trigger}\n"
            msg += "👉 快把 Pendle 利息拿來買幣！\n"
        else:
            msg += f"💤 [利息滾存中]\n"
            msg += f"BTC RSI {btc_rsi:.1f} (未達 {trigger})\n"
            msg += "👉 價格不夠甜，保留子彈。\n"
    else:
        msg += "💪 牛市衝刺中，利息操作暫停。\n"
        
    # 紀律提醒
    discipline_msg = print_discipline(status) # 同時印在 Console
    msg += f"------------------------{discipline_msg}"

    return msg

# 戰情儀表板 (Console)
def print_dashboard(status, today_date):
    assets = USER_CONFIG['CURRENT_ASSETS']
    target = USER_CONFIG['TARGET_WEALTH']
    progress = (assets / target) * 100
    
    print("\n" + "="*60)
    print(f"{Fore.YELLOW}🚀 V44 Hyper 累積版戰情室{Style.RESET}")
    print(f"📅 日期: {today_date.strftime('%Y-%m-%d')}")
    print(f"💰 資產進度: ${assets:,.0f} / ${target:,.0f} ({Fore.CYAN}{progress:.1f}%{Style.RESET})")
    
    bar_len = 30
    filled_len = min(bar_len, int(bar_len * assets // target))
    bar = '█' * filled_len + '-' * (bar_len - filled_len)
    print(f"   [{Fore.GREEN}{bar}{Style.RESET}]")
    print("="*60)
    
    vix = status['VIX']
    vix_str = f"{Fore.RED}{vix:.2f} (恐慌!){Style.RESET}" if status['IS_PANIC'] else f"{Fore.GREEN}{vix:.2f} (安全){Style.RESET}"
    print(f"🌍 市場氣象 (VIX): {vix_str}")
    print("-" * 60)
    
    print(f"{Fore.YELLOW}⚔️ 主力部隊 (本金) 操作指令:{Style.RESET}")
    for coin in ['BTC', 'ETH', 'SOL']:
        s = status[coin]
        if s['Action'] == 1: color = Fore.GREEN
        elif s['Action'] == -1: color = Fore.RED
        else: color = Fore.YELLOW
        trend_dist = ((s['Price'] - s['SMA_140']) / s['SMA_140']) * 100
        print(f"💎 {coin:<3}: {Fore.WHITE}${s['Price']:,.2f}{Style.RESET}")
        print(f"   • 趨勢: SMA140 (${s['SMA_140']:,.0f}) {color}{trend_dist:+.1f}%{Style.RESET}")
        print(f"   • 貪婪: {s['Mayer']:.2f} (警戒 > 2.4)")
        print(f"   👉 指令: {Style.BRIGHT}{color}{s['Signal']}{Style.RESET} | {s['Detail']}")
        print("-" * 20)

    print(f"\n{Fore.MAGENTA}🛡️ 後勤部隊 (Pendle 利息) 操作指令:{Style.RESET}")
    is_bear = status['BTC']['Action'] == -1
    
    if is_bear:
        btc_rsi = status['BTC']['RSI']
        trigger = STRATEGY_PARAMS['RSI_SNIPER']
        interest = USER_CONFIG['PENDLE_INTEREST_ACC']
        print(f"   目前狀態: {Fore.CYAN}熊市空倉中 (持有 USDT + Pendle){Style.RESET}")
        print(f"   累積利息: ${interest:,.0f} TWD")
        print(f"   監控指標: BTC RSI = {btc_rsi:.1f} (觸發點: < {trigger})")
        if btc_rsi < trigger:
            print(f"   🔥 {Fore.GREEN}[Smart DCA 訊號觸發！]{Style.RESET} 👉 買入 BTC + ETH (各半)！")
        else:
            print(f"   💤 {Fore.YELLOW}[等待中]{Style.RESET} 👉 利息繼續留在 Pendle 滾存。")
    else:
        print(f"   目前狀態: {Fore.GREEN}牛市滿倉中{Style.RESET} 👉 專注本金增長。")

    print("="*60 + "\n")

if __name__ == "__main__":
    try:
        raw = fetch_data()
        processed = process_data(raw)
        if processed and 'BTC' in processed:
            stat, today = analyze_market(processed)
            
            # 1. 顯示儀表板
            print_dashboard(stat, today)
            
            # 2. 發送 LINE (Messaging API)
            line_msg = generate_report(stat, today)
            send_line_push(line_msg)
            
        else:
            print("❌ 無法獲取數據")
    except Exception as e:
        print(f"❌ 錯誤: {e}")
