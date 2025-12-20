# ==========================================
# Gemini V44 Hyper: Accumulation Engine (GitHub Edition)
# ------------------------------------------
# [核心功能]
# 1. 策略: V44 Hyper (40% BTC / 40% ETH / 20% SOL)
# 2. 階段: 資產累積期 (Accumulation) - 專注本金增長
# 3. 通知: 支援 GitHub Secrets (LINE_TOKEN) 自動發送戰報
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
# 0. 環境檢查與自我診斷
# ==========================================
print("="*50)
print("🔍 V44 系統啟動自我診斷...")

# 優先從 GitHub Secrets (環境變數) 讀取
LINE_TOKEN = os.environ.get('LINE_TOKEN')

# 如果環境變數沒設定，嘗試讀取下方設定 (本地測試用)
# 在 GitHub 上請勿在此填寫真實 Token，以免洩漏
LOCAL_CONFIG_TOKEN = '' 

if not LINE_TOKEN and LOCAL_CONFIG_TOKEN:
    LINE_TOKEN = LOCAL_CONFIG_TOKEN
    print("⚠️ 使用本地設定檔中的 Token")

if LINE_TOKEN:
    masked_token = LINE_TOKEN[:4] + "****" + LINE_TOKEN[-4:]
    print(f"✅ LINE Token 讀取成功！({masked_token})")
else:
    print("❌ 警告：未檢測到 LINE Token！將無法發送通知。")
    print("   (請在 GitHub Settings -> Secrets -> Actions 中設定 'LINE_TOKEN')")

# 自動安裝依賴 (yfinance)
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
# ⚙️ 用戶資產設定 (請依實際情況修改)
# ==========================================
USER_CONFIG = {
    'CURRENT_ASSETS': 3000000,  # 目前總資產 (TWD)
    'TARGET_WEALTH': 20000000,  # 目標金額 (TWD)
    'PENDLE_INTEREST_ACC': 5000 # 累積未投入的利息 (TWD)
}

# 策略參數
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
    start_date = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')
    
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
        
        # 指標計算
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
# 2. LINE 通知模組 (使用 LINE Notify)
# ==========================================
def send_line_notify(message):
    if not LINE_TOKEN:
        print(f"{Fore.YELLOW}⚠️ 跳過發送：無有效 Token{Style.RESET}")
        return

    url = 'https://notify-api.line.me/api/notify'
    headers = {'Authorization': f'Bearer {LINE_TOKEN}'}
    data = {'message': message}
    
    try:
        print("📤 正在推送 LINE 通知...")
        response = requests.post(url, headers=headers, data=data)
        if response.status_code == 200:
            print(f"{Fore.GREEN}✅ LINE 通知發送成功！{Style.RESET}")
        else:
            print(f"{Fore.RED}❌ 發送失敗: {response.status_code} {response.text}{Style.RESET}")
    except Exception as e:
        print(f"{Fore.RED}❌ 網絡錯誤: {e}{Style.RESET}")

def generate_report(status, today_date):
    assets = USER_CONFIG['CURRENT_ASSETS']
    target = USER_CONFIG['TARGET_WEALTH']
    progress = (assets / target) * 100
    date_str = today_date.strftime('%Y-%m-%d')
    
    # 組合訊息
    msg = f"\n[🚀 V44 Hyper 戰報] {date_str}\n"
    msg += f"資產: ${assets/10000:.0f}萬 ({progress:.1f}%)\n"
    
    vix = status['VIX']
    vix_state = "🔴恐慌!" if status['IS_PANIC'] else "🟢安全"
    msg += f"環境: VIX {vix:.1f} ({vix_state})\n"
    msg += "-" * 15 + "\n"
    
    # 幣種指令
    for coin in ['BTC', 'ETH', 'SOL']:
        s = status[coin]
        icon = "🟢" if s['Action'] == 1 else ("🔴" if s['Action'] == -1 else "🟡")
        trend = "及格" if s['Price'] > s['SMA_140'] else "破線"
        msg += f"{icon} {coin}: ${s['Price']:.0f} ({trend})\n"
        msg += f"   指令: {s['Signal']}\n"
        msg += f"   RSI: {s['RSI']:.1f} | Mayer: {s['Mayer']:.2f}\n"
    
    msg += "-" * 15 + "\n"
    
    # 利息操作
    is_bear = status['BTC']['Action'] == -1
    if is_bear:
        btc_rsi = status['BTC']['RSI']
        trigger = STRATEGY_PARAMS['RSI_SNIPER']
        if btc_rsi < trigger:
            msg += f"🔥 [Smart DCA 觸發!]\n"
            msg += f"RSI {btc_rsi:.1f} < {trigger}\n"
            msg += "👉 快把 Pendle 利息拿來買幣！"
        else:
            msg += f"💤 [利息滾存中]\n"
            msg += f"RSI {btc_rsi:.1f} (未達 {trigger})\n"
            msg += "👉 別急，價格還不夠甜。"
    else:
        msg += "💪 牛市衝刺中，利息操作暫停。"
        
    # 紀律提醒 (附加在訊息末尾)
    if status['IS_PANIC']:
        msg += "\n\n🧘 [紀律提醒]\n相信系統，持有現金。不要手動接刀！"
    elif any(status[c]['Mayer'] > STRATEGY_PARAMS['MAYER_GREED'] for c in ['BTC', 'ETH', 'SOL']):
        msg += "\n\n🧘 [紀律提醒]\n市場過熱，請執行減倉鎖住利潤。"
    else:
        msg += "\n\n🧘 [紀律提醒]\n專注本業，加大本金。別人的百倍幣與你無關。"

    return msg

# ==========================================
# 3. 戰情儀表板 (Console)
# ==========================================
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

# ==========================================
# 主程式
# ==========================================
if __name__ == "__main__":
    try:
        raw = fetch_data()
        processed = process_data(raw)
        if processed and 'BTC' in processed:
            stat, today = analyze_market(processed)
            
            # 1. 顯示儀表板
            print_dashboard(stat, today)
            
            # 2. 發送 LINE (如果 Token 存在)
            if LINE_TOKEN:
                line_msg = generate_report(stat, today)
                # 這裡單純印出訊息內容以供確認
                # print(line_msg) 
                send_line_notify(line_msg)
            else:
                print("⚠️ 跳過 LINE 發送 (未設定 Token)")
                
        else:
            print("❌ 無法獲取數據")
    except Exception as e:
        print(f"❌ 錯誤: {e}")
