"""
MONTHLY MOMENTUM — SINGLE TAB CRON
====================================
Schedule: Daily at 3:30 PM IST (10:00 UTC)
- Checks if last trading day of month
- If yes: sells old holdings, buys new top 3
- Nifty trend filter: skip if 10 EMA < 20 EMA
- Logs everything to single "Momentum" tab

Sheet columns: Month, Stock, Entry, Exit, P&L%, Status

Env vars:
  GCP_SERVICE_ACCOUNT
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
"""

import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials
import requests
import json
import os
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# --- CONFIG ---
SHEET_NAME = "Momentum Strategy"
TAB_NAME = "Momentum"
TOP_N = 3
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

NIFTY_100 = [
    'RELIANCE','TCS','HDFCBANK','INFY','ICICIBANK','HINDUNILVR','ITC','SBIN','BHARTIARTL','KOTAKBANK',
    'LT','AXISBANK','ASIANPAINT','MARUTI','TITAN','SUNPHARMA','ULTRACEMCO','WIPRO','HCLTECH','BAJFINANCE',
    'NESTLEIND','POWERGRID','NTPC','ONGC','TATASTEEL','ADANIENT','ADANIPORTS','APOLLOHOSP','BAJAJ-AUTO','BAJAJFINSV',
    'BPCL','BRITANNIA','CIPLA','COALINDIA','DIVISLAB','DRREDDY','EICHERMOT','GRASIM','HDFCLIFE','HEROMOTOCO',
    'HINDALCO','INDUSINDBK','JSWSTEEL','M&M','SBILIFE','SHRIRAMFIN','TATACONSUM','TECHM',
    'ABB','AMBUJACEM','BANKBARODA','BEL','BERGEPAINT','BOSCHLTD','CANBK','CHOLAFIN','COLPAL','DLF',
    'GAIL','GODREJCP','HAL','HAVELLS','ICICIPRULI','INDIGO','IOC','IRCTC','JINDALSTEL',
    'LUPIN','MARICO','MOTHERSON','NAUKRI','NHPC','PIDILITIND','PNB','RECLTD','SBICARD','SIEMENS',
    'SRF','TATAPOWER','TORNTPHARM','TRENT','VEDL','ZYDUSLIFE','DABUR',
    'PFC','POLYCAB','PERSISTENT','PIIND','MAXHEALTH','MANKIND','JSWENERGY','CUMMINSIND',
    'ETERNAL','TVSMOTOR','INDHOTEL','LICI','LTIM','JIOFIN','DMART',
]


def get_sheet():
    creds_json = os.environ.get('GCP_SERVICE_ACCOUNT', '')
    creds_dict = json.loads(creds_json)
    if 'private_key' in creds_dict:
        creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).worksheet(TAB_NAME)


def send_telegram(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        print(f"[Telegram] {message}")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={'chat_id': chat_id, 'text': message}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")


def is_last_trading_day():
    today = datetime.now()
    next_day = today + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.month != today.month


def check_nifty_trend():
    """Returns True if Nifty 10 EMA > 20 EMA (bullish)."""
    try:
        nifty = yf.download('^NSEI', period='3mo', progress=False)
        nifty.columns = nifty.columns.get_level_values(0)
        n10 = float(nifty['Close'].ewm(span=10).mean().iloc[-1])
        n20 = float(nifty['Close'].ewm(span=20).mean().iloc[-1])
        return n10 > n20, n10, n20
    except:
        return True, 0, 0  # proceed if check fails


def get_top_momentum():
    """Get top 3 stocks by 3-month momentum with filters."""
    results = []
    for stock in NIFTY_100:
        try:
            df = yf.download(stock + '.NS', period='1y', progress=False)
            if df.empty or len(df) < 63: continue
            df.columns = df.columns.get_level_values(0)
            
            current = float(df['Close'].iloc[-1])
            
            # 3-month return
            past = float(df['Close'].iloc[-63])
            if past <= 0: continue
            momentum = (current / past - 1) * 100
            
            # 3/3 consistency
            m1 = float(df['Close'].iloc[-1]) / float(df['Close'].iloc[-21]) - 1
            m2 = float(df['Close'].iloc[-21]) / float(df['Close'].iloc[-42]) - 1
            m3 = float(df['Close'].iloc[-42]) / float(df['Close'].iloc[-63]) - 1
            if not (m1 > 0 and m2 > 0 and m3 > 0): continue
            
            # Within 10% of 52-week high
            high_52w = float(df['High'].tail(252).max())
            if current < high_52w * 0.9: continue
            
            results.append({'stock': stock, 'price': round(current, 2), 'momentum': round(momentum, 1)})
        except:
            continue
    
    return sorted(results, key=lambda x: x['momentum'], reverse=True)[:TOP_N]


def run():
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    month_str = now.strftime('%Y-%m')
    print(f"[{now.strftime('%H:%M:%S')}] Monthly Momentum running...")

    if not is_last_trading_day():
        print("Not last trading day. Skipping.")
        return

    # Nifty trend filter
    bullish, n10, n20 = check_nifty_trend()
    if not bullish:
        msg = f"Momentum ({now.strftime('%b %Y')}): Nifty 10EMA ({n10:.0f}) < 20EMA ({n20:.0f}). SKIPPING — stay in cash."
        print(msg)
        send_telegram(msg)
        ws = get_sheet()
        ws.append_row([month_str, 'SKIPPED', '', '', '', 'Nifty bearish'])
        return

    print(f"Nifty OK: 10EMA ({n10:.0f}) > 20EMA ({n20:.0f})")

    ws = get_sheet()
    records = ws.get_all_records()

    # --- STEP 1: Close open positions (sell at current price) ---
    open_positions = [(i, r) for i, r in enumerate(records, start=2) if r.get('Status') == 'OPEN']
    
    exits = []
    for row_num, pos in open_positions:
        stock = pos['Stock']
        entry = float(pos['Entry'])
        try:
            df = yf.download(stock + '.NS', period='5d', progress=False)
            df.columns = df.columns.get_level_values(0)
            exit_price = float(df['Close'].iloc[-1])
        except:
            exit_price = entry
        
        pnl_pct = round((exit_price / entry - 1) * 100, 2)
        ws.update(f'D{row_num}:F{row_num}', [[round(exit_price, 2), pnl_pct, 'CLOSED']])
        exits.append(f"{stock}: ₹{entry:.0f} → ₹{exit_price:.0f} ({pnl_pct:+.1f}%)")

    # --- STEP 2: Buy new top 3 ---
    picks = get_top_momentum()
    
    if not picks:
        send_telegram(f"Momentum ({now.strftime('%b %Y')}): No stocks qualify. Staying in cash.")
        return

    # Write new positions
    for p in picks:
        ws.append_row([month_str, p['stock'], p['price'], '', '', 'OPEN'])

    # --- STEP 3: Send Telegram ---
    msg_lines = [f"📈 MOMENTUM REBALANCE — {now.strftime('%b %Y')}\n"]
    
    if exits:
        msg_lines.append("SOLD:")
        for e in exits:
            msg_lines.append(f"  {e}")
        msg_lines.append("")
    
    msg_lines.append("BOUGHT:")
    for p in picks:
        msg_lines.append(f"  {p['stock']} @ ₹{p['price']} (3m: +{p['momentum']}%)")
    
    msg_lines.append(f"\nHold till end of {(now + timedelta(days=32)).strftime('%b')}. No SL.")
    send_telegram("\n".join(msg_lines))
    print(f"Rebalance done. Sold {len(exits)}, Bought {len(picks)}.")
