import yfinance as yf
import pandas as pd
import numpy as np
import requests
import os
import csv
import warnings
from datetime import datetime

# 忽略不必要的警告
warnings.filterwarnings("ignore")

# ==========================================
# 1. 參數設定 (V17.12 Apex Sniper - The Alpha Predator)
# ==========================================
# 執行環境：GitHub Actions (Daily)
# 核心邏輯：Multikill Mode (弒君換馬) + MSTR/SafeHaven 生態

LINE_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')
PORTFOLIO_FILE = 'portfolio.csv'

USD_TWD_RATE = 32.5
MAX_TOTAL_POSITIONS = 4

# --- V17.12 參數 (冠軍參數) ---
SECTOR_PARAMS = {
    'CRYPTO_SPOT': {'stop': 0.40, 'zombie': 4,  'trail_1': 0.40, 'trail_2': 0.25, 'trail_3': 0.15},
    'CRYPTO_LEV':  {'stop': 0.50, 'zombie': 3,  'trail_1': 0.50, 'trail_2': 0.30, 'trail_3': 0.15},
    'CRYPTO_MEME': {'stop': 0.60, 'zombie': 3,  'trail_1': 0.60, 'trail_2': 0.30, 'trail_3': 0.15},
    'US_STOCK':    {'stop': 0.25, 'zombie': 8,  'trail_1': 0.25, 'trail_2': 0.15, 'trail_3': 0.10},
    'US_LEV':      {'stop': 0.35, 'zombie': 4,  'trail_1': 0.35, 'trail_2': 0.20, 'trail_3': 0.10},
    'LEV_3X':      {'stop': 0.35, 'zombie': 3,  'trail_1': 0.35, 'trail_2': 0.20, 'trail_3': 0.10},
    'LEV_2X':      {'stop': 0.40, 'zombie': 4,  'trail_1': 0.40, 'trail_2': 0.25, 'trail_3': 0.15},
    'TW_STOCK':    {'stop': 0.25, 'zombie': 8,  'trail_1': 0.25, 'trail_2': 0.15, 'trail_3': 0.10},
    'TW_LEV':      {'stop': 0.30, 'zombie': 6,  'trail_1': 0.30, 'trail_2': 0.20, 'trail_3': 0.10},
    'US_GROWTH':   {'stop': 0.40, 'zombie': 7,  'trail_1': 0.40, 'trail_2': 0.20, 'trail_3': 0.15},
    'SAFE_HAVEN':  {'stop': 0.20, 'zombie': 10, 'trail_1': 0.20, 'trail_2': 0.10, 'trail_3': 0.05}
}

# ==========================================
# 2. 戰略資產池 (V17.12 The Alpha Predator)
# ==========================================
ASSET_MAP = {
    # --- 1. CRYPTO GODS ---
    'MSTR': 'CRYPTO_LEV', # [NEW] King of Beta
    'MSTU': 'CRYPTO_LEV', 'CONL': 'CRYPTO_LEV', 'BITX': 'CRYPTO_LEV', 'ETHU': 'CRYPTO_MEME', 'WGMI': 'CRYPTO_LEV',
    'DOGE-USD': 'CRYPTO_MEME', 'SHIB-USD': 'CRYPTO_MEME', 'BONK-USD': 'CRYPTO_MEME', 'PEPE24478-USD': 'CRYPTO_MEME', 'WIF-USD': 'CRYPTO_MEME',
    'BTC-USD': 'CRYPTO_SPOT', 'ETH-USD': 'CRYPTO_SPOT',
    'SOL-USD': 'CRYPTO_SPOT', 'AVAX-USD': 'CRYPTO_SPOT', 'NEAR-USD': 'CRYPTO_SPOT', 'SUI20947-USD': 'CRYPTO_SPOT', 'KAS-USD': 'CRYPTO_SPOT', 'RENDER-USD': 'CRYPTO_SPOT',

    # --- 2. US LEVERAGE ---
    'SOXL': 'LEV_3X', 'FNGU': 'LEV_3X', 'TQQQ': 'LEV_3X', 'BULZ': 'LEV_3X', 'TECL': 'LEV_3X', 'LABU': 'LEV_3X',
    'NVDL': 'LEV_2X', 'TSLL': 'LEV_2X', 'USD': 'LEV_2X', 'AMZU': 'LEV_2X', 'AAPU': 'LEV_2X',

    # --- 3. HEDGE / SAFE HAVEN ---
    'TMF': 'SAFE_HAVEN', # [NEW] 20Y Treasury 3x Bull
    'NUGT': 'SAFE_HAVEN', # [NEW] Gold Miners 2x Bull

    # --- 4. STOCKS ---
    'PLTR': 'US_GROWTH', 'SMCI': 'US_GROWTH', 'ARM': 'US_GROWTH', 'CRWD': 'US_GROWTH', 'PANW': 'US_GROWTH', 'SHOP': 'US_GROWTH',
    'APP': 'US_GROWTH',
    'IONQ': 'US_GROWTH', 'RGTI': 'US_GROWTH', 'RKLB': 'US_GROWTH', 'VRT': 'US_GROWTH',
    'SNOW': 'US_GROWTH', 'VST': 'US_GROWTH', 'ASTS': 'US_GROWTH', 'OKLO': 'US_GROWTH', 'VKTX': 'US_GROWTH',

    # --- 5. TW STOCKS ---
    '2330.TW': 'TW_STOCK', '2317.TW': 'TW_STOCK', '2454.TW': 'TW_STOCK', '2382.TW': 'TW_STOCK',
    '3231.TW': 'TW_STOCK', '6669.TW': 'TW_STOCK', 
    '2603.TW': 'TW_STOCK', '2609.TW': 'TW_STOCK', '8996.TW': 'TW_STOCK',
    '6515.TW': 'TW_STOCK', '6442.TW': 'TW_STOCK', '6683.TWO': 'TW_STOCK',
    '8299.TWO': 'TW_STOCK', '3529.TWO': 'TW_STOCK', '3081.TWO': 'TW_STOCK', '6739.TWO': 'TW_STOCK', # [Fix] Reverted to .TWO for Yahoo
    '2359.TW': 'TW_STOCK', '3131.TWO': 'TW_STOCK', '3583.TW': 'TW_STOCK', '8054.TWO': 'TW_STOCK',
    '3661.TW': 'TW_STOCK', '3443.TW': 'TW_STOCK', '3035.TW': 'TW_STOCK', '5269.TW': 'TW_STOCK',
    '6531.TW': 'TW_STOCK', '2388.TW': 'TW_STOCK',
    '00631L.TW': 'TW_LEV'
}

# Extended Tier 1 List (Score * 1.2)
TIER_1_ASSETS = [
    'MSTR', # Top Tier Addition
    'MSTU', 'CONL', 'NVDL', 'SOXL', 'BITX',
    'DOGE-USD', 'PEPE24478-USD',
    '2330.TW', '00631L.TW',
    'PLTR', 'ETHU', 'ASTS', 'RGTI', 'BONK-USD', 'RENDER-USD',
    'SHIB-USD', 'WIF-USD', 'AVAX-USD', 'LABU'
]

WATCHLIST = list(ASSET_MAP.keys())
BENCHMARKS = ['SPY', 'BTC-USD', '^TWII']

# ==========================================
# 3. 輔助函式
# ==========================================
def normalize_symbol(raw_symbol):
    raw_symbol = str(raw_symbol).strip().upper()
    
    # [Fix] 強制修正常見錯誤代碼
    fix_map = {
        '6683.TW': '6683.TWO', # 雍智科技是上櫃
        '6739.TW': '6739.TWO'  # AES-KY: 雖然是上市，但若 Yahoo .TW 抓不到，改回 .TWO
    }
    if raw_symbol in fix_map: return fix_map[raw_symbol]

    mapping = {
        'PEPE': 'PEPE24478-USD', 'SHIB': 'SHIB-USD', 'DOGE': 'DOGE-USD',
        'BONK': 'BONK-USD', 'WIF': 'WIF-USD', 'RNDR': 'RENDER-USD'
    }
    if raw_symbol in mapping: return mapping[raw_symbol]

    if raw_symbol.isdigit():
        for t in WATCHLIST:
            if ('.TW' in t or '.TWO' in t) and t.startswith(raw_symbol + '.'):
                return t
        return f"{raw_symbol}.TW"
    return raw_symbol

def get_sector(symbol):
    return ASSET_MAP.get(symbol, 'US_STOCK')

def load_portfolio():
    holdings = {}
    if not os.path.exists(PORTFOLIO_FILE): return holdings
    try:
        with open(PORTFOLIO_FILE, mode='r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None) # Skip header
            for row in reader:
                if not row or len(row) < 2: continue
                symbol = normalize_symbol(row[0]) # 會自動修正
                try:
                    entry_price = float(row[1])
                    entry_date = row[2] if len(row) > 2 else datetime.now().strftime('%Y-%m-%d')
                    holdings[symbol] = {'entry_price': entry_price, 'entry_date': entry_date}
                except ValueError: continue
        return holdings
    except Exception: return {}

def update_portfolio_csv(holdings, new_buys=None):
    try:
        data_to_write = []
        for symbol, data in holdings.items():
            data_to_write.append([symbol, data['entry_price'], data['entry_date']])

        if new_buys:
            today = datetime.now().strftime('%Y-%m-%d')
            for buy in new_buys:
                if not any(row[0] == buy['Symbol'] for row in data_to_write):
                    data_to_write.append([buy['Symbol'], buy['Price'], today])

        with open(PORTFOLIO_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Symbol', 'EntryPrice', 'EntryDate'])
            writer.writerows(data_to_write)
        print("✅ Portfolio CSV 已更新")
    except Exception as e:
        print(f"❌ 更新 CSV 失敗: {e}")

# ==========================================
# 4. 分析引擎 (Multikill Live Engine V17.12)
# ==========================================
def analyze_market():
    portfolio = load_portfolio()
    all_tickers = list(set(BENCHMARKS + list(portfolio.keys()) + WATCHLIST))

    print(f"📥 下載 {len(all_tickers)} 檔數據 (Apex Sniper V17.12)...")
    try:
        # 使用 auto_adjust=True 確保與回測價格一致
        data = yf.download(all_tickers, period="300d", progress=False, auto_adjust=True)
        if data.empty: return None
        if len(all_tickers) == 1:
             closes = data['Close'].to_frame(name=all_tickers[0])
        else:
             closes = data['Close'].ffill()
    except Exception as e:
        print(f"❌ 數據下載失敗: {e}"); return None

    # --- 1. 計算指標 ---
    current_prices = {t: closes[t].iloc[-1] for t in all_tickers if t in closes.columns}

    regime = {}
    if 'SPY' in closes.columns:
        regime['US_BULL'] = closes['SPY'].iloc[-1] > closes['SPY'].rolling(200).mean().iloc[-1]
    if 'BTC-USD' in closes.columns:
        regime['CRYPTO_BULL'] = closes['BTC-USD'].iloc[-1] > closes['BTC-USD'].rolling(100).mean().iloc[-1]
    if '^TWII' in closes.columns:
        regime['TW_BULL'] = closes['^TWII'].iloc[-1] > closes['^TWII'].rolling(60).mean().iloc[-1]

    sells = []; keeps = []; buys = []; swaps = []

    # --- 2. 持倉健檢 (Stop Loss / Zombie / Hibernation) ---
    for symbol, data in portfolio.items():
        if symbol not in current_prices: continue
        curr_price = current_prices[symbol]
        entry_price = data['entry_price']
        entry_date = datetime.strptime(data['entry_date'], '%Y-%m-%d')
        days_held = (datetime.now() - entry_date).days

        sector = get_sector(symbol)
        params = SECTOR_PARAMS.get(sector, SECTOR_PARAMS['US_STOCK'])

        profit_pct = (curr_price - entry_price) / entry_price

        series = closes[symbol].dropna()
        if len(series) < 60: continue
        ma50 = series.rolling(50).mean().iloc[-1]

        reason = ""
        # A. 殭屍清除 (V17.12: 時間到達且未獲利即清除)
        if days_held > params['zombie'] and curr_price <= entry_price:
            reason = f"💤 殭屍清除 (> {params['zombie']}天且未獲利)"

        # B. 分區冬眠 (注意：避險資產 SAFE_HAVEN 通常不受冬眠影響，這裡簡單略過)
        elif sector != 'SAFE_HAVEN':
            if 'CRYPTO' in sector and not regime.get('CRYPTO_BULL', True): reason = "❄️ 分區冬眠 (BTC < MA100)"
            elif 'TW' in sector and not regime.get('TW_BULL', True): reason = "❄️ 分區冬眠 (TWII < MA60)"
            elif 'US' in sector and not regime.get('US_BULL', True): reason = "❄️ 分區冬眠 (SPY < MA200)"

        # C. 停利/止損計算
        limit = params['trail_1']
        if not reason:
            # Tiered Trailing V17.12
            if profit_pct > 1.0: limit = params['trail_3']
            elif profit_pct > 0.3: limit = params['trail_2']
            else: limit = params['trail_1']

            trail_stop_price = curr_price # 在 Live 版我們通常用當前價格評估，或假設 trailing_high 是當前價格
            # 簡化邏輯：若從最高點回撤超過 limit -> 賣出。但 Live Script 通常沒有紀錄 High。
            # 替代方案：檢查 Hard Stop 與 MA 保護
            
            # 1. 硬止損
            if profit_pct < -params['stop']:
                reason = f"🔴 觸及止損 ({profit_pct*100:.1f}%)"
            # 2. 技術出場 (跌破季線) - Crypto 與 3X 通常不看這個，只看硬止損
            elif sector in ['US_STOCK', 'TW_STOCK'] and curr_price < ma50:
                reason = "❌ 跌破季線 (MA50)"

        # 計算得分 (用於換馬)
        mom_20 = series.pct_change(20).iloc[-1]
        vol_20 = series.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)
        score = 0
        if not pd.isna(mom_20):
            mult = 1.0 + vol_20
            if symbol in TIER_1_ASSETS: mult *= 1.2
            if 'ADR' in sector: mult *= 1.1
            score = mom_20 * mult

        if reason:
            sells.append({'Symbol': symbol, 'Price': curr_price, 'Reason': reason, 'PnL': f"{profit_pct*100:.1f}%", 'Sector': sector})
        else:
            keeps.append({'Symbol': symbol, 'Price': curr_price, 'Entry': entry_price, 'Score': score, 'Profit': profit_pct, 'Days': days_held, 'Sector': sector, 'TrailLimit': limit})

    # --- 3. 選股掃描 (Candidates) ---
    candidates = []
    scan_pool = []
    
    # 避險資產邏輯：如果大盤皆弱 (US & Crypto Bear)，則加入避險資產掃描
    risk_off = not regime.get('US_BULL', True) and not regime.get('CRYPTO_BULL', True)
    if risk_off:
        scan_pool += [t for t in WATCHLIST if 'SAFE_HAVEN' in get_sector(t)]
    
    # 正常掃描
    if regime.get('CRYPTO_BULL', True): scan_pool += [t for t in WATCHLIST if 'CRYPTO' in get_sector(t)]
    if regime.get('US_BULL', True): scan_pool += [t for t in WATCHLIST if 'US' in get_sector(t) or 'SAFE_HAVEN' in get_sector(t)] # 允許混搭
    if regime.get('TW_BULL', True): scan_pool += [t for t in WATCHLIST if 'TW' in get_sector(t)]
    
    scan_pool = list(set(scan_pool))

    for t in scan_pool:
        if t in portfolio or t not in closes.columns: continue
        series = closes[t].dropna()
        if len(series) < 65: continue

        p = series.iloc[-1]
        m20 = series.rolling(20).mean().iloc[-1]
        m50 = series.rolling(50).mean().iloc[-1]
        m60 = series.rolling(60).mean().iloc[-1]

        # [V17.12] 趨勢濾網 (避險資產可稍微寬鬆，但這裡維持統一標準)
        if not (p > m20 and m20 > m50 and p > m60): continue

        mom_20 = series.pct_change(20).iloc[-1]
        
        # [V17.12] 成本與動能過濾
        sector = get_sector(t)
        if 'TW' in sector and mom_20 < 0.05: continue
        if 'LEV_3X' in sector and mom_20 < 0.05: continue
        if pd.isna(mom_20) or mom_20 <= 0: continue

        vol_20 = series.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)

        mult = 1.0 + vol_20
        if t in TIER_1_ASSETS: mult *= 1.2
        if 'ADR' in sector: mult *= 1.1

        final_score = mom_20 * mult

        candidates.append({'Symbol': t, 'Price': p, 'Score': final_score, 'Sector': sector})

    candidates.sort(key=lambda x: x['Score'], reverse=True)

    # --- 4. 弒君換馬 (Multikill Loop V17.12) ---
    while keeps and candidates:
        worst_holding = min(keeps, key=lambda x: x['Score'])
        
        existing_targets = [s['Buy']['Symbol'] for s in swaps]
        available_candidates = [c for c in candidates if c['Symbol'] not in existing_targets]
        
        if not available_candidates: break
            
        best_candidate = available_candidates[0]

        vol_hold = closes[worst_holding['Symbol']].pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)
        if pd.isna(vol_hold): vol_hold = 0

        # V17.12 Swap Threshold
        swap_thresh = 1.4 + (vol_hold * 0.1)
        swap_thresh = min(swap_thresh, 2.0)

        if best_candidate['Score'] > worst_holding['Score'] * swap_thresh:
            swaps.append({
                'Sell': worst_holding,
                'Buy': best_candidate,
                'Reason': f"Score {best_candidate['Score']:.2f} > {worst_holding['Score']:.2f} * {swap_thresh:.1f}"
            })
            keeps = [k for k in keeps if k != worst_holding]
            sells.append({'Symbol': worst_holding['Symbol'], 'Price': worst_holding['Price'], 'Reason': "💀 弒君換馬", 'PnL': f"{worst_holding['Profit']*100:.1f}%", 'Sector': worst_holding['Sector']})
        else:
            break

    # --- 5. 填補空位 (Fill Slots) ---
    buy_targets = [s['Buy'] for s in swaps]
    open_slots = MAX_TOTAL_POSITIONS - len(keeps) - len(swaps) # Swaps 已經一賣一買抵銷，但這裡是計算新的 Buy List
    
    existing_buys = [b['Symbol'] for b in buy_targets]
    pool_idx = 0
    while open_slots > 0 and pool_idx < len(candidates):
        cand = candidates[pool_idx]
        if cand['Symbol'] not in existing_buys:
            buy_targets.append(cand)
            open_slots -= 1
        pool_idx += 1

    return regime, sells, keeps, buy_targets, swaps

def send_line_notify(msg):
    if not LINE_ACCESS_TOKEN or not LINE_USER_ID:
        print("⚠️ 未設定 LINE Token"); print(msg); return

    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {LINE_ACCESS_TOKEN}'}
    data = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": msg}]}
    try:
        requests.post(url, headers=headers, json=data)
    except Exception as e:
        print(f"發送 LINE 失敗: {e}")

def format_message(regime, sells, keeps, buys, swaps):
    msg = f"🦁 **V17.12 Apex Sniper (The Alpha Predator)**\n{datetime.now().strftime('%Y-%m-%d')}\n━━━━━━━━━━━━━━\n"
    msg += f"🌍 市場環境\n"
    us = "🟢" if regime.get('US_BULL') else "❄️"
    cry = "🟢" if regime.get('CRYPTO_BULL') else "❄️"
    tw = "🟢" if regime.get('TW_BULL') else "❄️"
    msg += f"美股: {us} | 幣圈: {cry} | 台股: {tw}\n━━━━━━━━━━━━━━\n"

    if sells:
        msg += "🔴 **【賣出指令】**\n"
        for s in sells:
            msg += f"❌ 賣出: {s['Symbol']}\n"
            msg += f"   原因: {s['Reason']}\n"
            msg += f"   損益: {s['PnL']}\n"
        msg += "--------------------\n"

    if swaps:
        msg += "💀 **【弒君換馬 (Multikill)】**\n"
        for s in swaps:
            msg += f"📉 賣出: {s['Sell']['Symbol']} (弱)\n"
            msg += f"🚀 買入: {s['Buy']['Symbol']} (強)\n"
            msg += f"   原因: {s['Reason']}\n"
        msg += "--------------------\n"

    if buys:
        msg += "🟢 **【執行買入】**\n"
        for b in buys:
            params = SECTOR_PARAMS.get(b['Sector'], SECTOR_PARAMS['US_STOCK'])
            stop_pct = params['stop']
            trail_pct = params['trail_1']
            stop_price = b['Price'] * (1 - stop_pct)

            msg += f"💰 買入: {b['Symbol']}\n"
            msg += f"   價格: {b['Price']:.2f}\n"
            msg += f"   分數: {b['Score']:.2f}\n"
            msg += f"   👮 券商設定: 移動停利 {int(trail_pct*100)}%\n"
            
            if stop_pct == trail_pct:
                 msg += f"   (🛑 同步底線: {stop_price:.2f} / -{int(stop_pct*100)}%)\n"
            else:
                 msg += f"   (🛑 災難底線: {stop_price:.2f} / -{int(stop_pct*100)}%)\n"
        msg += "--------------------\n"

    if keeps:
        msg += "🛡️ **【持倉監控】**\n"
        for k in keeps:
            pnl = k['Profit'] * 100
            emoji = "😍" if pnl > 20 else "😐" if pnl > 0 else "🤢"
            params = SECTOR_PARAMS.get(k['Sector'], SECTOR_PARAMS['US_STOCK'])
            zombie_left = params['zombie'] - k['Days']
            zombie_msg = f"🧟剩{zombie_left}天" if k['Profit'] <= 0 else "💪安全"
            limit_pct = int(k['TrailLimit'] * 100)
            msg += f"{emoji} {k['Symbol']} ({pnl:+.1f}%)\n"
            msg += f"   狀態: {zombie_msg}\n"
            msg += f"   🔥 動能: {k['Score']:.2f}\n"
            msg += f"   👮 券商設定: 移動停利 {limit_pct}%\n"
    else:
        if not buys and not swaps:
            msg += "☕ 目前空手，好好休息\n"

    msg += "━━━━━━━━━━━━━━"
    return msg

if __name__ == "__main__":
    res = analyze_market()
    if res:
        regime, sells, keeps, buys, swaps = res
        current_holdings = load_portfolio()

        # 1. 執行賣出 (包含 Stop/Zombie/Swap Sells)
        for s in sells:
            if s['Symbol'] in current_holdings:
                del current_holdings[s['Symbol']]

        # 2. 執行買入 (包含 Swap Buys/New Buys)
        final_csv_buys = [{'Symbol': b['Symbol'], 'Price': b['Price']} for b in buys]
        
        # 更新 CSV
        update_portfolio_csv(current_holdings, final_csv_buys)

        # 發送通知
        msg = format_message(regime, sells, keeps, buys, swaps)
        print(msg)
        send_line_notify(msg)
    else:
        print("❌ 分析失敗")
