# ==========================================
# Gemini V37 Auto Commander (GitHub Actions 版) - Messaging API 升級版
# ------------------------------------------
# 功能：自動抓取數據 -> 訓練模型 -> 判斷趨勢 -> 發送 LINE 訊息
# 更新：已從 LINE Notify 遷移至 LINE Messaging API
# 更新2：訊息內容擴充，包含完整戰情室資訊
# ==========================================

import os
import requests
import json
import warnings
import yfinance as yf
import pandas as pd
import numpy as np
from stable_baselines3 import PPO
import gymnasium as gym
from gymnasium import spaces

warnings.filterwarnings("ignore")

# 從環境變數讀取 LINE Messaging API 設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

def send_line_push(msg):
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("❌ 未設定 LINE_CHANNEL_ACCESS_TOKEN 或 LINE_USER_ID，無法發送通知")
        print("--- 訊息內容 ---")
        print(msg)
        return
    
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }
    
    # Messaging API 的 Payload 格式
    payload = {
        "to": LINE_USER_ID,
        "messages": [
            {
                "type": "text",
                "text": msg
            }
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print("✅ Line 訊息發送成功")
        else:
            print(f"❌ Line 發送失敗: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"❌ 連線錯誤: {e}")

# ==========================================
# 1. 數據獲取與特徵工程
# ==========================================
print("正在連線數據庫...")
START_DATE = '2015-01-01'
tickers = ['BTC-USD', '^VIX']
raw_data = yf.download(tickers, start=START_DATE, group_by='ticker', progress=False)

df = pd.DataFrame()
try:
    if 'BTC-USD' in raw_data.columns:
        df['Close'] = raw_data['BTC-USD']['Close']
    elif 'Close' in raw_data.columns:
        df['Close'] = raw_data['Close']
    
    if '^VIX' in raw_data.columns:
        df['VIX'] = raw_data['^VIX']['Close']
    else:
        df['VIX'] = 20.0
except KeyError:
    df['Close'] = raw_data.iloc[:, 0]
    df['VIX'] = 20.0

df.ffill(inplace=True)
df.dropna(inplace=True)

# 指標計算
df['SMA_140'] = df['Close'].rolling(window=140).mean()
df['Dist_Trend'] = (df['Close'] - df['SMA_140']) / df['SMA_140']
df['SMA_200'] = df['Close'].rolling(window=200).mean()
df['Mayer'] = df['Close'] / df['SMA_200']
df['VIX_Level'] = df['VIX'] / 30.0

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))
df['RSI'] = calculate_rsi(df['Close'])

df.dropna(inplace=True)
train_df = df.copy()

# ==========================================
# 2. AI 環境
# ==========================================
class GeminiFinalEnv(gym.Env):
    def __init__(self, dataframe):
        super(GeminiFinalEnv, self).__init__()
        self.df = dataframe
        self.current_step = 0
        self.action_space = spaces.Discrete(3) 
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(5,), dtype=np.float32)
        self.holdings = 0.0 

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.holdings = 0.0
        return self._next_observation(), {}
    
    def _next_observation(self):
        obs = np.array([
            self.df['Dist_Trend'].iloc[self.current_step],
            self.df['Mayer'].iloc[self.current_step] / 3.0,
            self.df['VIX_Level'].iloc[self.current_step],
            self.df['RSI'].iloc[self.current_step] / 100,
            float(self.holdings)
        ], dtype=np.float32)
        return np.nan_to_num(obs)

    def step(self, action):
        self.current_step += 1
        target_pct = {0: 0.0, 1: 0.5, 2: 1.0}[int(action)]
        
        # 風控邏輯
        if self.df['Mayer'].iloc[self.current_step] > 2.4:
            target_pct = min(target_pct, 0.5)
        if self.df['Dist_Trend'].iloc[self.current_step] < 0:
            if self.df['RSI'].iloc[self.current_step] > 30: 
                target_pct = 0.0
        if self.df['VIX_Level'].iloc[self.current_step] > 1.0:
            target_pct = 0.0

        btc_ret = self.df['Close'].iloc[self.current_step] / self.df['Close'].iloc[self.current_step-1] - 1
        reward = target_pct * btc_ret * 100
        if self.df['Dist_Trend'].iloc[self.current_step] > 0 and target_pct == 1.0:
            reward += 0.01
            
        done = self.current_step >= len(self.df) - 2
        return self._next_observation(), reward, done, False, {}

# ==========================================
# 3. 訓練與預測
# ==========================================
print("AI 正在分析歷史數據...")
env_train = GeminiFinalEnv(train_df)
model = PPO("MlpPolicy", env_train, verbose=0, learning_rate=0.0003, ent_coef=0.01)
# 為了節省 GitHub 資源，每日執行訓練步數可稍微降低，因為模型結構簡單
model.learn(total_timesteps=30000)

# 生成今日訊號
env_live = GeminiFinalEnv(train_df)
obs, _ = env_live.reset()
for _ in range(len(train_df) - 1):
    action, _ = model.predict(obs)
    env_live.step(action)
    obs = env_live._next_observation()

raw_action, _ = model.predict(obs)
raw_action = int(raw_action)

# ==========================================
# 4. 生成 Line 報告
# ==========================================
latest_data = df.iloc[-1]
latest_date = df.index[-1].strftime('%Y-%m-%d')
latest_price = latest_data['Close']
sma140 = latest_data['SMA_140']
mayer = latest_data['Mayer']
vix = latest_data['VIX']
rsi = latest_data['RSI']

target_pct = {0: 0.0, 1: 0.5, 2: 1.0}[raw_action]
status_icon = "⚪"
short_msg = ""
long_reason = ""

# 風控重現
is_bull = latest_data['Dist_Trend'] > 0
is_overheated = latest_data['Mayer'] > 2.4
is_oversold = latest_data['RSI'] < 30
is_panic = latest_data['VIX'] > 30

if is_panic:
    target_pct = 0.0
    status_icon = "🌪️"
    short_msg = "恐慌避險 (Cash Only)"
    long_reason = "VIX 指數過高 (>30)，市場極度不穩，強制空倉保命。"
elif is_overheated:
    target_pct = min(target_pct, 0.5)
    status_icon = "⚠️"
    short_msg = "過熱減碼 (Max 50%)"
    long_reason = "Mayer 倍數 > 2.4，價格嚴重偏離均線，強制減碼鎖定利潤。"
elif not is_bull:
    if is_oversold:
        status_icon = "⚡"
        short_msg = "熊市搶反彈 (High Risk)"
        long_reason = "雖然處於熊市 (價格 < 140日線)，但 RSI 超賣，嘗試搶短 (高風險)。"
    else:
        target_pct = 0.0
        status_icon = "🛑"
        short_msg = "空倉觀望 (Trend Off)"
        long_reason = "【熊市防禦】價格跌破 140日生命線，且無超賣訊號，強制空倉等待趨勢回穩。"
else:
    if raw_action == 2:
        status_icon = "🚀"
        short_msg = "滿倉進攻 (Full BTC)"
        long_reason = "【順勢進攻】價格站穩 140日線，估值合理，動能強勁。建議滿倉持有。"
    elif raw_action == 1:
        status_icon = "⚖️"
        short_msg = "半倉震盪 (50% BTC)"
        long_reason = "【震盪持有】趨勢向上但動能減弱，建議半倉持有，進可攻退可守。"
    else:
        status_icon = "🛡️"
        short_msg = "保守觀望"
        long_reason = "【保守觀望】趨勢雖向上，但 AI 偵測到潛在風險，選擇暫時空倉。"

# 計算建議金額 (範例本金: 100萬)
base_capital = 1000000 
btc_amount = base_capital * target_pct
cash_amount = base_capital * (1 - target_pct)

# 組合完整訊息 (Rich Message)
message = f"""
=========================
🏆 Gemini V37 實戰戰情室
📅 數據日期: {latest_date}
=========================

📊 [市場健康度體檢]
   💰 BTC 價格 : ${latest_price:,.2f}
   📈 趨勢線 (140MA): ${sma140:,.2f}   {'✅ 多頭' if is_bull else '❌ 空頭'}
   🌡️ 估值 (Mayer): {mayer:.2f}        {'🔥 過熱' if is_overheated else '❄️ 合理'}
   🌊 恐慌 (VIX)  : {vix:.2f}        {'🌪️ 恐慌' if is_panic else '😌 穩定'}
   ⚡ 動能 (RSI)  : {rsi:.2f}

📢 [AI 指揮官指令]
   {status_icon} {long_reason}

💼 [建議倉位配置] (範例本金: 100萬)
   -----------------------------------
   🟠 比特幣 (BTC) : {target_pct*100:>5.1f}%  (${btc_amount:,.0f})
   🟢 現  金 (USD) : {(1-target_pct)*100:>5.1f}%  (${cash_amount:,.0f})
   -----------------------------------

⚙️ [操作備忘錄] (請嚴格遵守)
   1. 請每日早上 8:00 (美股收盤後) 執行一次本程式。
   2. 【買入規則】：若建議從空倉/半倉轉為滿倉，請分 3-5 天分批買進 (防假突破)。
   3. 【賣出規則】：若建議從持倉轉為空倉 (🛑)，請勿猶豫，一次果斷賣出 (避險優先)。
   4. 若建議倉位與目前持倉差距 > 10%，才需要進行調整 (省手續費)。
=========================
"""

# 印出到 Console 方便除錯
print(message)

# 發送到 LINE
send_line_push(message)
