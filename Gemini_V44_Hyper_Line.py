# ==========================================
# Gemini V44 Hyper: Accumulation Engine (Debug Edition)
# ------------------------------------------
# [更新說明]
# 增加 LINE Token 讀取狀態的詳細日誌 (Log)，
# 幫助您在 GitHub Actions 的執行結果中找出為什麼沒收到訊息。
# ==========================================

import sys
import subprocess
import warnings
import pandas as pd
import numpy as np
import requests
import os 
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

# 自動安裝依賴
try:
    import yfinance as yf
except ImportError:
    print("📦 正在安裝必要套件 (yfinance)...")
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
# ⚙️ 用戶設定 (USER_CONFIG)
# ==========================================
USER_CONFIG = {
    'CURRENT_ASSETS': 3000000, 
    'TARGET_WEALTH': 20000000, 
    'PENDLE_INTEREST_ACC': 5000,
    
    # [LINE Token 設定說明]
    # 1. 如果您在 GitHub Actions 執行且已設定 Secrets (名稱為 LINE_TOKEN)，這裡請「留空」或「保留原樣」。
    #    (程式會優先讀取 GitHub Secrets，比較安全)
    # 2. 如果您是在「本機電腦」執行，才需要將 Token 貼在下方引號內。
    'LINE_TOKEN': '' 
}

STRATEGY_PARAMS = {
    'SMA_TREND': 140,
    'SMA_MAYER': 200,
    'VIX_PANIC': 30,
    'MAYER_GREED': 2.4,
    'RSI_SNIPER': 45
}

# ==========================================
# 1. 數據與策略邏輯
# ==========================================
def fetch_data():
    print(f"\n{Fore.CYAN}📥 正在掃描市場數據...{Style.RESET}")
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
        return
    is_greed = any(status[c]['Mayer'] > STRATEGY_PARAMS['MAYER_GREED'] for c in ['BTC', 'ETH', 'SOL'])
    if is_greed:
        print(f"   🤑 {Fore.YELLOW}檢測到市場過熱 (Mayer > 2.4){Style.RESET}")
        return
    is_choppy = any(abs(status[c]['Price'] - status[c]['SMA_140']) / status[c]['SMA_140'] < 0.02 for c in ['BTC', 'ETH', 'SOL'])
    if is_choppy:
        print(f"   😴 {Fore.WHITE}檢測到趨勢不明確{Style.RESET}")
        return
    print(f"   🌱 {Fore.GREEN}市場處於正常波動範圍{Style.RESET}")

# ==========================================
# 3. LINE 通知模組 (除錯加強版)
# ==========================================
def send_line_notify(message):
    print("\n" + "="*30)
    print("📲 準備發送 LINE 通知...")
    
    # 嘗試從環境變數讀取 (GitHub Secrets)
    env_token = os.environ.get('LINE_TOKEN')
    # 從設定檔讀取 (Local Config)
    config_token = USER_CONFIG.get('LINE_TOKEN', '')
    
    token = None
    source = ""
    
    # 優先使用環境變數，且確保不為空
    if env_token:
        token = env_token
        source = "GitHub Secrets (環境變數)"
    elif config_token and config_token.strip() != '' and config_token != '您的LINE_TOKEN_貼在這裡':
        token = config_token
        source = "USER_CONFIG (檔案設定)"
    
    if not token:
        print(f"{Fore.RED}❌ 錯誤: 未找到有效的 LINE Token！{Style.RESET}")
        print("   請確認 GitHub Secrets 設定正確，名稱必須是 'LINE_TOKEN'。")
        print("   或者在 USER_CONFIG 中填入 Token。")
        return

    # 隱碼顯示 Token 前幾碼以確認讀取正確
    masked_token = token[:4] + "****" + token[-4:]
    print(f"🔑 讀取 Token 來源: {source}")
    print(f"🔑 Token 預覽: {masked_token}")

    url = 'https://notify-api.line.me/api/notify'
    headers = {'Authorization': f'Bearer {token}'}
    data = {'message': message}
    
    try:
        print("📡 正在連線 LINE 伺服器...")
        response = requests.post(url, headers=headers, data=data)
        
        if response.status_code == 200:
            print(f"{Fore.GREEN}✅ 發送成功！請檢查手機。{Style.RESET}")
        else:
            print(f"{Fore.RED}❌ 發送失敗！HTTP 狀態碼: {response.status_code}{Style.RESET}")
            print(f"   回應訊息: {response.text}")
            if response.status_code == 401:
                print("   👉 原因: Token 無效。請重新申請 LINE Notify Token。")
    except Exception as e:
        print(f"{Fore.RED}❌ 網絡錯誤: {e}{Style.RESET}")
    print("="*30 + "\n")

def generate_line_message(status, today_date):
    assets = USER_CONFIG['CURRENT_ASSETS']
    target = USER_CONFIG['TARGET_WEALTH']
    progress = (assets / target) * 100
    date_str = today_date.strftime('%Y-%m-%d')
    
    msg = f"\n[🚀 V44 Hyper 戰報] {date_str}\n"
    msg += f"資產: ${assets/10000:.0f}萬 ({progress:.1f}%)\n"
    
    vix = status['VIX']
    vix_state = "🔴恐慌!" if status['IS_PANIC'] else "🟢安全"
    msg += f"環境: VIX {vix:.1f} ({vix_state})\n"
    msg += "-" * 15 + "\n"
    
    for coin in ['BTC', 'ETH', 'SOL']:
        s = status[coin]
        icon = "🟢" if s['Action'] == 1 else ("🔴" if s['Action'] == -1 else "🟡")
        trend = "及格" if s['Price'] > s['SMA_140'] else "破線"
        msg += f"{icon} {coin}: ${s['Price']:.0f} ({trend})\n"
        msg += f"   指令: {s['Signal']}\n"
    
    msg += "-" * 15 + "\n"
    
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
        
    return msg

# ==========================================
# 4. 戰情儀表板 (Console)
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

    print("="*60)
    print_discipline(status)
    print("="*60 + "\n")

if __name__ == "__main__":
    try:
        raw = fetch_data()
        processed = process_data(raw)
        if processed and 'BTC' in processed:
            stat, today = analyze_market(processed)
            print_dashboard(stat, today)
            # 發送 LINE (帶除錯日誌)
            line_msg = generate_line_message(stat, today)
            send_line_notify(line_msg)
        else:
            print("❌ 無法獲取數據")
    except Exception as e:
        print(f"❌ 錯誤: {e}")
