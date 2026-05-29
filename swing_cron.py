"""
EMA STACK SWING — AUTOMATED CRON SCRIPT
=========================================
Schedule: Daily at 3:15 PM IST (9:45 UTC)
- Checks for exits (positions held 5 days)
- Scans 87 stocks for EMA stack signal
- Sends Telegram alerts for buy/sell
- Max 3 positions at once

Signal: EMA 5 > EMA 10 > EMA 20 > EMA 50 + Volume > 1.5x + 5d return > 3%
Entry: Buy at close (3:25 PM)
Exit: Sell at close after 5 trading days (no SL)
Capital: ₹6L (3 slots × ₹2L each)

Env vars needed:
  GCP_SERVICE_ACCOUNT  - Google service account JSON
  TELEGRAM_BOT_TOKEN   - Telegram bot token
  TELEGRAM_CHAT_ID     - Your chat ID
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
TAB_NAME = "Swing"
MAX_POSITIONS = 3
HOLD_DAYS = 5
CAPITAL_PER_TRADE = 200000  # ₹2L per slot

STOCKS = [
    "TCS","INFY","HCLTECH","WIPRO","TECHM","MPHASIS","COFORGE","PERSISTENT","LTTS",
    "HDFCBANK","ICICIBANK","SBIN","KOTAKBANK","AXISBANK","INDUSINDBK","BANKBARODA","PNB","FEDERALBNK","IDFCFIRSTB","AUBANK","BANDHANBNK",
    "SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","APOLLOHOSP","TORNTPHARM","LUPIN","AUROPHARMA","BIOCON","ALKEM",
    "M&M","MARUTI","BAJAJ-AUTO","HEROMOTOCO","EICHERMOT","BALKRISIND","BHARATFORG","MOTHERSON","BOSCHLTD",
    "TATASTEEL","HINDALCO","JSWSTEEL","COALINDIA","VEDL","ADANIENT","NMDC","SAIL","NATIONALUM","JINDALSTEL",
    "HINDUNILVR","ITC","NESTLEIND","BRITANNIA","DABUR","GODREJCP","MARICO","COLPAL","TATACONSUM","VBL",
    "DLF","GODREJPROP","OBEROIRLTY","PRESTIGE","PHOENIXLTD","BRIGADE","LODHA","SOBHA","SUNTECK","MAHLIFE",
    "RELIANCE","ONGC","NTPC","POWERGRID","ADANIGREEN","BPCL","IOC","GAIL","TATAPOWER","ADANIENSOL",
    "CANBK","UNIONBANK","IOB","INDIANB","MAHABANK","CENTRALBK","BANKINDIA",
]

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']


def get_sheet():
    creds_json = os.environ.get('GCP_SERVICE_ACCOUNT', '')
    if not creds_json:
        raise Exception("GCP_SERVICE_ACCOUNT env var not set")
    creds_dict = json.loads(creds_json)
    if 'private_key' in creds_dict:
        creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open(SHEET_NAME)
    return sh.worksheet(TAB_NAME)


def send_telegram(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        print(f"Telegram not configured. Message: {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        print(f"Telegram: {resp.status_code}")
    except Exception as e:
        print(f"Telegram error: {e}")


def get_open_positions(ws):
    """Get currently open positions from sheet."""
    records = ws.get_all_records()
    open_pos = []
    for i, r in enumerate(records, start=2):
        if r.get('Status') == 'OPEN':
            open_pos.append((i, r))
    return open_pos


def scan_stocks():
    """Find stocks with EMA stack + volume + momentum."""
    candidates = []
    for stock in STOCKS:
        try:
            ticker = stock + '.NS'
            df = yf.download(ticker, period='6mo', progress=False)
            if df.empty or len(df) < 55:
                continue
            df.columns = df.columns.get_level_values(0)

            close = df['Close']
            ema5 = close.ewm(span=5).mean().iloc[-1]
            ema10 = close.ewm(span=10).mean().iloc[-1]
            ema20 = close.ewm(span=20).mean().iloc[-1]
            ema50 = close.ewm(span=50).mean().iloc[-1]

            # EMA stack: 5 > 10 > 20 > 50
            if not (ema5 > ema10 > ema20 > ema50):
                continue

            # Volume > 1.5x average
            vol_avg = df['Volume'].rolling(20).mean().iloc[-1]
            vol_today = float(df['Volume'].iloc[-1])
            if vol_avg == 0:
                continue
            vol_ratio = vol_today / vol_avg
            if vol_ratio < 1.5:
                continue

            # 5-day return > 3%
            ret_5d = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100
            if ret_5d < 3:
                continue

            price = float(close.iloc[-1])
            candidates.append({
                'stock': stock,
                'price': round(price, 2),
                'ema5': round(float(ema5), 2),
                'ema50': round(float(ema50), 2),
                'vol_ratio': round(vol_ratio, 1),
                'ret_5d': round(ret_5d, 1),
            })
        except:
            continue

    # Sort by volume ratio (strongest signal first)
    candidates.sort(key=lambda x: x['vol_ratio'], reverse=True)
    return candidates


def run():
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    today = now_ist.strftime('%Y-%m-%d')
    print(f"[{now_ist.strftime('%H:%M:%S')}] EMA Stack Swing running...")

    ws = get_sheet()
    open_positions = get_open_positions(ws)
    print(f"Open positions: {len(open_positions)}")

    # --- STEP 1: Check exits (positions held >= 5 days) ---
    exits = []
    for row_num, pos in open_positions:
        entry_date = pos.get('Date', '')
        if not entry_date:
            continue
        try:
            entry_dt = datetime.strptime(entry_date, '%Y-%m-%d')
        except:
            continue
        days_held = (now_ist - entry_dt).days
        # Count only trading days (approx: weekdays)
        trading_days = sum(1 for d in range(1, days_held+1)
                         if (entry_dt + timedelta(days=d)).weekday() < 5)

        if trading_days >= HOLD_DAYS:
            stock = pos['Stock']
            entry_price = float(pos['Entry'])
            # Get current price
            try:
                df = yf.download(stock + '.NS', period='5d', progress=False)
                df.columns = df.columns.get_level_values(0)
                exit_price = float(df['Close'].iloc[-1])
            except:
                exit_price = entry_price

            qty = int(CAPITAL_PER_TRADE / entry_price)
            pnl = round((exit_price - entry_price) * qty)

            # Update sheet
            ws.update(f'E{row_num}:G{row_num}', [[round(exit_price, 2), pnl, 'CLOSED']])
            exits.append(f"{stock}: Entry ₹{entry_price:.0f} → Exit ₹{exit_price:.0f} | P&L: Rs{pnl:+,}")

    if exits:
        msg = f"⏰ EXIT (Day 5) — {today}\n\n" + "\n".join(exits)
        send_telegram(msg)
        print(f"Exited {len(exits)} positions")

    # --- STEP 2: Check available slots ---
    open_positions = get_open_positions(ws)  # refresh after exits
    available = MAX_POSITIONS - len(open_positions)
    if available <= 0:
        print("All slots full. No new entries.")
        return

    # --- STEP 3: Scan for new signals ---
    candidates = scan_stocks()
    if not candidates:
        print("No EMA stack signals today.")
        send_telegram(f"Swing ({today}): No signals. {len(open_positions)} positions open.")
        return

    # Don't enter stocks already held
    held_stocks = set(pos['Stock'] for _, pos in open_positions)
    candidates = [c for c in candidates if c['stock'] not in held_stocks]

    # Pick top N to fill available slots
    picks = candidates[:available]
    if not picks:
        print("No new stocks to enter (already holding candidates).")
        return

    # --- STEP 4: Send alerts and log ---
    msg_lines = [f"🟢 SWING BUY — {today}\n"]
    for p in picks:
        sell_date = now_ist + timedelta(days=7)  # approx 5 trading days
        while sell_date.weekday() >= 5:
            sell_date += timedelta(days=1)

        msg_lines.append(f"{p['stock']} @ ~₹{p['price']}")
        msg_lines.append(f"  Vol: {p['vol_ratio']}x | 5d ret: +{p['ret_5d']}%")
        msg_lines.append(f"  Sell: ~{sell_date.strftime('%b %d')}")
        msg_lines.append("")

        # Write to sheet
        ws.append_row([today, p['stock'], p['price'], sell_date.strftime('%Y-%m-%d'), '', '', 'OPEN'])

    msg_lines.append(f"Hold 5 days. No SL. Sell at close on exit day.")
    send_telegram("\n".join(msg_lines))
    print(f"Entered {len(picks)} new positions.")
