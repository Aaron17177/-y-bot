# ==========================================
# Gemini V44 Hyper: Accumulation Engine (Ultimate Edition)
# ------------------------------------------
# 這是專為「資產累積期」設計的執行腳本。
# 
# [功能清單]
# 1. 📊 戰情儀表板: 顯示即時幣價、指標、操作指令。
# 2. 🧘 紀律提醒: 根據市場情緒 (VIX/Mayer) 輸出心理建設警語。
# 3. 📲 LINE Notify: 執行完畢後自動發送戰報到手機。
# ==========================================

import sys
import subprocess
import warnings
import pandas as pd
import numpy as np
import requests
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
    'CURRENT_ASSETS': 3000000,  # 輸入您目前的總資產 (TWD)
    'TARGET_WEALTH': 20000000,  # 您的第一階段目標 (TWD)
    'PENDLE_INTEREST_ACC': 5000, # 目前累積在 Pendle 未提領的利息 (TWD)
    
    # [重要] 請填入您的 LINE Notify Token
    # 申請網址: https://notify-bot.line.me/my/
    'LINE_TOKEN': '您的LINE_TOKEN_貼在這裡' 
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
# 2. 紀律提醒模組 (Mindset Check)
# ==========================================
def print_discipline(status):
    print(f"\n{Fore.CYAN}🧘 V44 交易心理與紀律提醒 (Mindset Check):{Style.RESET}")
    
    # 情境 1: 恐慌時刻
    if status['IS_PANIC']:
        print(f"   ⚠️  {Fore.RED}檢測到市場極度恐慌 (VIX > 30){Style.RESET}")
        print("   👉 [心法]：相信系統。如果 V44 叫你空倉，就持有 USDT 去睡覺。")
        print("   👉 [禁忌]：千萬不要試圖手動接刀！也不要因為看新聞說『比特幣要歸零』就恐慌亂賣。")
        print("   💡 [行動]：確認 Pendle 利息是否入帳，那是你在這段時間唯一的安慰。")
        return

    # 情境 2: 貪婪時刻
    is_greed = any(status[c]['Mayer'] > STRATEGY_PARAMS['MAYER_GREED'] for c in ['BTC', 'ETH', 'SOL'])
    if is_greed:
        print(f"   🤑 {Fore.YELLOW}檢測到市場過熱 (Mayer > 2.4){Style.RESET}")
        print("   👉 [心法]：樹不會長到天上去。執行減倉是為了『鎖住利潤』。")
        print("   👉 [禁忌]：不要覺得自己是神，不要把生活費也拿進來加倉。")
        print("   💡 [行動]：享受獲利，但保持清醒。")
        return

    # 情境 3: 震盪/無聊時刻 (價格在均線附近)
    is_choppy = any(abs(status[c]['Price'] - status[c]['SMA_140']) / status[c]['SMA_140'] < 0.02 for c in ['BTC', 'ETH', 'SOL'])
    if is_choppy:
        print(f"   😴 {Fore.WHITE}檢測到趨勢不明確 (價格在均線附近糾纏){Style.RESET}")
        print("   👉 [心法]：無聊是交易的一部分。接受『小虧』是為了抓到後面的『大賺』。")
        print("   👉 [禁忌]：不要手癢去開合約嚕短線，不要隨意更改 SMA 參數。")
        print("   💡 [行動]：關掉看盤軟體，去做別的事。")
        return

    # 情境 4: 正常趨勢 / FOMO 防治
    print(f"   🌱 {Fore.GREEN}市場處於正常波動範圍{Style.RESET}")
    print("   👉 [心法]：專注本業，加大本金投入。別人的百倍幣與你無關。")
    print("   👉 [目標]：你的終點是 2000 萬退休，不是當賭神。堅持執行 V44。")
    print("   💡 [提醒]：不要因為朋友賺了錢就隨意更改配置 (SOL 20% 已經很夠了)。")

# ==========================================
# 3. LINE 通知模組
# ==========================================
def send_line_notify(message):
    token = USER_CONFIG['LINE_TOKEN']
    if token == '您的LINE_TOKEN_貼在這裡' or not token:
        print(f"{Fore.YELLOW}⚠️ 未設定 LINE Token，跳過發送。{Style.RESET}")
        return

    url = 'https://notify-api.line.me/api/notify'
    headers = {'Authorization': f'Bearer {token}'}
    data = {'message': message}
    
    try:
        response = requests.post(url, headers=headers, data=data)
        if response.status_code == 200:
            print(f"{Fore.GREEN}✅ LINE 通知發送成功！{Style.RESET}")
        else:
            print(f"{Fore.RED}❌ LINE 發送失敗: {response.status_code}{Style.RESET}")
    except Exception as e:
        print(f"{Fore.RED}❌ 網絡錯誤: {e}{Style.RESET}")

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
    
    # 幣種指令
    for coin in ['BTC', 'ETH', 'SOL']:
        s = status[coin]
        icon = "🟢" if s['Action'] == 1 else ("🔴" if s['Action'] == -1 else "🟡")
        trend = "及格" if s['Price'] > s['SMA_140'] else "破線"
        msg += f"{icon} {coin}: ${s['Price']:.0f} ({trend})\n"
        msg += f"   指令: {s['Signal']}\n"
    
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
    print(f"⚖️ 標準配置: 40% BTC / 40% ETH / 20% SOL")
    
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
        print(f"   👉 指令: {Style.BRIGHT}{color}{s['Signal']}{Style.RESET} | 原因: {s['Detail']}")
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
            print(f"   🔥 {Fore.GREEN}[Smart DCA 訊號觸發！]{Style.RESET}")
            print(f"   👉 動作: 請提領 Pendle 利息，買入 BTC + ETH (各半)。")
        else:
            print(f"   💤 {Fore.YELLOW}[等待中]{Style.RESET}")
            print(f"   👉 動作: 利息繼續留在 Pendle 複利滾存。")
            
    else:
        print(f"   目前狀態: {Fore.GREEN}牛市滿倉中{Style.RESET}")
        print(f"   👉 動作: 專注於本金增長，暫無利息定投操作。")

    print("="*60)
    
    # 呼叫紀律模組
    print_discipline(status)
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
            
            # 1. 顯示完整儀表板 (含紀律提醒)
            print_dashboard(stat, today)
            
            # 2. 發送 LINE 通知
            line_msg = generate_line_message(stat, today)
            send_line_notify(line_msg)
            
        else:
            print("❌ 無法獲取數據")
    except Exception as e:
        print(f"❌ 錯誤: {e}")
