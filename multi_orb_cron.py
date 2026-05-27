"""
MULTI-STOCK ORB — AUTOMATED CRON SCRIPT
========================================
Schedule: Every 1 min (9:30 AM - 3:15 PM IST)
- 9:30 AM: Scans 87 stocks, calculates OR, picks top 3, sends alert
- 9:36-10:00 AM: Monitors for breakout entry
- 10:00 AM: Cancels untraded stocks
- Until 3:15 PM: Monitors SL/Target, then EOD exit
- Max 3 trades per day

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
TAB_NAME = "MultiORB"
CAPITAL = 120000
LEVERAGE = 5
PER_TRADE = 40000 * LEVERAGE  # ₹2L exposure per trade
MAX_TRADES = 3
MIN_RANGE_PCT = 0.7
MAX_RANGE_PCT = 1.5
TARGET_MULT = 3.0
CHARGES = 100  # per trade approx

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


def get_today_rows(ws):
    """Get all rows for today."""
    today = datetime.now().strftime('%Y-%m-%d')
    records = ws.get_all_records()
    rows = []
    for i, r in enumerate(records, start=2):
        if r.get('Date') == today:
            rows.append((i, r))
    return rows


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


def scan_stocks():
    """Scan all 87 stocks, return top 3 by OR range %."""
    candidates = []
    for stock in STOCKS:
        try:
            ticker = stock + '.NS'
            df = yf.download(ticker, period='5d', interval='1m', progress=False)
            if df.empty:
                continue
            df.columns = df.columns.get_level_values(0)
            df.index = df.index.tz_localize(None)
            today = datetime.now().strftime('%Y-%m-%d')
            today_data = df[df.index.strftime('%Y-%m-%d') == today]
            if len(today_data) < 15:
                continue

            # OR = first 15 min (9:15-9:30)
            or_candles = today_data.iloc[:15]
            or_high = float(or_candles['High'].max())
            or_low = float(or_candles['Low'].min())
            or_range = or_high - or_low
            open_price = float(today_data.iloc[0]['Open'])

            if open_price == 0 or or_range == 0:
                continue
            or_pct = or_range / open_price * 100

            if or_pct < MIN_RANGE_PCT or or_pct > MAX_RANGE_PCT:
                continue

            candidates.append({
                'stock': stock,
                'or_high': or_high,
                'or_low': or_low,
                'or_range': or_range,
                'or_pct': or_pct,
            })
        except:
            continue

    # Sort by OR range % descending, pick top 3
    candidates.sort(key=lambda x: x['or_pct'], reverse=True)
    return candidates[:MAX_TRADES]


def get_current_price(ticker):
    try:
        df = yf.download(ticker, period='1d', interval='1m', progress=False)
        if df.empty:
            return None
        df.columns = df.columns.get_level_values(0)
        return float(df['Close'].iloc[-1])
    except:
        return None


def run():
    now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
    print(f"[{now_ist.strftime('%H:%M:%S')}] Multi-ORB Cron running...")

    ws = get_sheet()
    today = now_ist.strftime('%Y-%m-%d')
    today_rows = get_today_rows(ws)

    # --- STEP 1: First run (9:30 AM) — scan and pick top 3 ---
    if not today_rows:
        if now_ist.hour == 9 and now_ist.minute < 36:
            # Too early, wait for OR to form
            print("Waiting for 9:30 AM OR to complete...")
            return

        picks = scan_stocks()
        if not picks:
            send_telegram(f"Multi-ORB ({today}): No stocks qualify (OR 0.7-1.5%). Skipping today.")
            print("No qualifying stocks.")
            return

        msg_lines = [f"🎯 MULTI-ORB LEVELS ({today})\n"]
        for i, p in enumerate(picks, 1):
            qty = int(PER_TRADE / p['or_high'])
            target_l = p['or_high'] + p['or_range'] * TARGET_MULT
            target_s = p['or_low'] - p['or_range'] * TARGET_MULT
            # Write to sheet: Date, Stock, OR High, OR Low, OR%, Direction, Entry, SL, Target, Exit, Exit Reason, P&L, Status
            ws.append_row([today, p['stock'], round(p['or_high'], 2), round(p['or_low'], 2),
                          round(p['or_pct'], 2), '', '', '', '', '', '', '', 'WATCHING'])
            msg_lines.append(f"#{i} {p['stock']} (OR {p['or_pct']:.1f}%)")
            msg_lines.append(f"   High: {p['or_high']:.1f} | Low: {p['or_low']:.1f}")
            msg_lines.append(f"   BUY>{p['or_high']:.1f} TGT {target_l:.1f} | SHORT<{p['or_low']:.1f} TGT {target_s:.1f}")
            msg_lines.append("")

        msg_lines.append(f"Entry: 9:36-10:00 AM | Exit: 3:15 PM")
        send_telegram("\n".join(msg_lines))
        print(f"Picked {len(picks)} stocks. Alerts sent.")
        return

    # --- STEP 2: Check each stock's status ---
    for row_num, row_data in today_rows:
        status = row_data.get('Status', '')
        stock = row_data.get('Stock', '')
        if not stock:
            continue

        # Already done
        if status == 'CLOSED':
            continue

        or_high = float(row_data['OR High'])
        or_low = float(row_data['OR Low'])
        or_range = or_high - or_low
        ticker = stock + '.NS'

        # --- WATCHING: check for breakout ---
        if status == 'WATCHING':
            price = get_current_price(ticker)
            if price is None:
                continue

            if price > or_high:
                # LONG breakout
                entry = or_high
                sl = or_low
                target = entry + or_range * TARGET_MULT
                qty = int(PER_TRADE / entry)
                pnl_risk = round((sl - entry) * qty)
                ws.update(f'F{row_num}:M{row_num}', [['LONG', round(entry, 2), round(sl, 2), round(target, 2), '', '', '', 'IN TRADE']])
                send_telegram(f"🟢 BUY {stock} @ {entry:.1f}\nSL: {sl:.1f} | TGT: {target:.1f}\nQty: {qty} | Risk: Rs{abs(pnl_risk):,}")
                print(f"LONG {stock} at {entry:.1f}")

            elif price < or_low:
                # SHORT breakout
                entry = or_low
                sl = or_high
                target = entry - or_range * TARGET_MULT
                qty = int(PER_TRADE / entry)
                pnl_risk = round((sl - entry) * qty)
                ws.update(f'F{row_num}:M{row_num}', [['SHORT', round(entry, 2), round(sl, 2), round(target, 2), '', '', '', 'IN TRADE']])
                send_telegram(f"🔴 SHORT {stock} @ {entry:.1f}\nSL: {sl:.1f} | TGT: {target:.1f}\nQty: {qty} | Risk: Rs{abs(pnl_risk):,}")
                print(f"SHORT {stock} at {entry:.1f}")

            elif now_ist.hour >= 10:
                # Deadline passed, no breakout
                ws.update(f'F{row_num}:M{row_num}', [['NO ENTRY', '', '', '', '', '', '', 'CLOSED']])
                print(f"{stock}: No breakout by 10:00 AM. Skipped.")

            continue

        # --- IN TRADE: check SL/Target/EOD ---
        if status == 'IN TRADE':
            price = get_current_price(ticker)
            if price is None:
                continue

            direction = row_data['Direction']
            entry = float(row_data['Entry'])
            sl = float(row_data['SL'])
            target = float(row_data['Target'])
            qty = int(PER_TRADE / entry)

            exit_price = None
            exit_reason = None

            if direction == 'LONG':
                if price <= sl:
                    exit_price, exit_reason = sl, 'SL'
                elif price >= target:
                    exit_price, exit_reason = target, 'TGT'
                elif now_ist.hour >= 15 and now_ist.minute >= 15:
                    exit_price, exit_reason = price, 'EOD'
            else:  # SHORT
                if price >= sl:
                    exit_price, exit_reason = sl, 'SL'
                elif price <= target:
                    exit_price, exit_reason = target, 'TGT'
                elif now_ist.hour >= 15 and now_ist.minute >= 15:
                    exit_price, exit_reason = price, 'EOD'

            if exit_price:
                if direction == 'LONG':
                    pnl = round((exit_price - entry) * qty) - CHARGES
                else:
                    pnl = round((entry - exit_price) * qty) - CHARGES

                ws.update(f'I{row_num}:M{row_num}', [[round(exit_price, 2), exit_reason, pnl, '', 'CLOSED']])
                emoji = '🟢' if pnl > 0 else '🔴'
                send_telegram(f"{emoji} EXIT {stock} ({direction})\nEntry: {entry:.1f} | Exit: {exit_price:.1f}\nReason: {exit_reason} | P&L: Rs{pnl:+,}")
                print(f"EXIT {stock}: {exit_reason}, P&L: Rs{pnl:+,}")

    print("Done.")
