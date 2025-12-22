# Gemini V44 Hyper: Accumulation Engine (Messaging API + Lazy Summary)

# ------------------------------------------

# [修正說明]

# 1. 訊息開頭加回「📋 今日操作懶人包」。

# 2. 完整支援 LINE Messaging API 與 GitHub Secrets。

# 3. 包含 V44 Hyper 核心策略與 Smart DCA。

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

    

    # 先判斷 BTC 狀態 (大哥濾網)

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

        action_short = "持有" # 懶人包專用簡訊

        

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

# 3. 訊息生成 (Report Generator)

# ==========================================

def generate_report(status, today_date):

    assets = USER_CONFIG['CURRENT_ASSETS']

    target = USER_CONFIG['TARGET_WEALTH']

    progress = (assets / target) * 100

    date_str = today_date.strftime('%Y-%m-%d')

    

    # -------------------------

    # 懶人包區塊

    # -------------------------

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

    

    # -------------------------

    # 詳細戰情區塊

    # -------------------------

    msg += f"🏆 V44 三核戰情室\n"

    msg += f"=========================\n"

    

    # 資產進度

    msg += f"💰 資產: ${assets/10000:.0f}萬 ({progress:.1f}%)\n"

    

    vix = status['VIX']

    vix_state = "🔴恐慌!" if status['IS_PANIC'] else "🟢安全"

    msg += f"🌍 環境: VIX {vix:.1f} ({vix_state})\n"

    msg += "-" * 20 + "\n"

    

    total_allocation = 0.0

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

    

    # 資產配置建議

    msg += f"-------------------------\n"

    msg += f"💼 [總資產建議配置]\n"

    msg += f"   🟠 BTC : {status['BTC']['BaseWeight']*status['BTC']['TargetPct']*100:>4.1f}%\n"

    msg += f"   🔵 ETH : {status['ETH']['BaseWeight']*status['ETH']['TargetPct']*100:>4.1f}%\n"

    msg += f"   🟣 SOL : {status['SOL']['BaseWeight']*status['SOL']['TargetPct']*100:>4.1f}%\n"

    msg += f"   🟢 Cash: {cash_allocation*100:>4.1f}%\n"

    msg += f"-------------------------\n\n"

    

    # 利息操作提醒 (Smart DCA)

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

    msg += "1. SOL 波動大，嚴格遵守 20% 上限。\n"

    msg += "2. 熊市紀律：BTC 轉空時，SOL 必須清倉。\n"

    

    # 附加動態心理建設

    discipline_msg = print_discipline(status) # 這會在 Console 印出

    msg += discipline_msg # 這會加到 LINE 訊息



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
