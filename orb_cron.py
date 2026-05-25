"""
STOCK ORB — AUTOMATED CRON SCRIPT
====================================
Schedule: Every 1 min (9:30 AM - 2:15 PM IST)
- 9:30 AM: Calculates OR levels, picks top stock, sends alert
- 9:36 AM+: Monitors for breakout entry
- 10:00 AM: Cancels if no breakout
- Until 2:15 PM: Monitors SL/Target, then EOD exit
- Max 1 trade per day

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
TAB_NAME = "Intraday"
CAPITAL = 175000
LEVERAGE = 5
POSITION_SIZE = CAPITAL * LEVERAGE  # ₹8,75,000
MIN_RANGE_PCT = 0.5  # minimum OR range as % of price
MAX_RANGE_PCT = 3.0  # maximum OR range as % of price
TARGET_MULT = 3.0    # 3x OR range
SL_MULT = 2.0        # 2x OR range
CHARGES = 358        # per trade (intraday)

STOCKS = [
    'RELIANCE.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'SBIN.NS', 'INFY.NS',
    'BAJFINANCE.NS', 'BHARTIARTL.NS', 'AXISBANK.NS', 'ITC.NS', 'TCS.NS'
]

def calc_pnl(entry, exit_price):
    """Calculate P&L for stock intraday trade."""
    qty = int(POSITION_SIZE / entry)
    gross = round((exit_price - entry) * qty)
    net = gross - CHARGES
    return net, gross, CHARGES

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']


# --- GOOGLE SHEETS ---
def get_sheet():
    creds_json = os.environ.get('GCP_SERVICE_ACCOUNT', '')
    if not creds_json:
        raise Exception("GCP_SERVICE_ACCOUNT env var not set")
    creds_dict = json.loads(creds_json)
    if 'private_key' in creds_dict:
        creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)

    # Create Intraday tab if not exists
    existing = [ws.title for ws in spreadsheet.worksheets()]
    if TAB_NAME not in existing:
        ws = spreadsheet.add_worksheet(TAB_NAME, rows=500, cols=15)
        ws.update('A1:O1', [['Date', 'Stock', 'OR High', 'OR Low', 'Range%', 'Signal',
                             'Entry', 'SL', 'Target', 'Exit', 'Gross P&L', 'Charges', 'Net P&L', 'Result', 'Status']])
    return spreadsheet.worksheet(TAB_NAME)


def get_today_row(ws):
    """Get today's row from sheet. Returns (row_number, row_data) or (None, None)."""
    today = datetime.now().strftime('%Y-%m-%d')
    records = ws.get_all_records()
    for i, row in enumerate(records):
        if row.get('Date') == today:
            return i + 2, row  # +2 because header is row 1, records are 0-indexed
    return None, None


# --- TELEGRAM ---
def send_telegram(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        print(f"[Telegram disabled] {message}")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'})


# --- MARKET DATA ---
def get_stock_data(ticker):
    """Get today's 5-min data for a stock."""
    df = yf.download(ticker, period='5d', interval='5m', progress=False)
    df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    today = datetime.now().date()
    today_data = df[df.index.date == today]
    return today_data


def pick_orb_stock():
    """Pick the stock with biggest 15-min OR range % (0.5-3%)."""
    best_stock = None
    best_range_pct = 0
    best_data = None

    for ticker in STOCKS:
        try:
            today_data = get_stock_data(ticker)
            if len(today_data) < 3:  # need at least 15 min (3 × 5-min candles)
                continue
            first_15 = today_data.iloc[:3]  # 3 candles = 15 min
            orb_high = float(first_15['High'].max())
            orb_low = float(first_15['Low'].min())
            orb_range = orb_high - orb_low
            mid_price = (orb_high + orb_low) / 2
            range_pct = (orb_range / mid_price) * 100

            if MIN_RANGE_PCT <= range_pct <= MAX_RANGE_PCT and range_pct > best_range_pct:
                best_range_pct = range_pct
                best_stock = ticker
                best_data = {'high': orb_high, 'low': orb_low, 'range': orb_range,
                            'range_pct': range_pct, 'ticker': ticker,
                            'name': ticker.replace('.NS', '')}
        except:
            continue

    return best_data


def get_current_price(ticker):
    """Get latest price for a stock."""
    try:
        df = yf.download(ticker, period='1d', interval='5m', progress=False)
        df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        if len(df) > 0:
            return float(df['Close'].iloc[-1]), float(df['High'].iloc[-1]), float(df['Low'].iloc[-1])
    except:
        pass
    return None, None, None


# --- MAIN LOGIC ---
def run():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ORB Cron running...")

    ws = get_sheet()
    today = datetime.now().strftime('%Y-%m-%d')
    row_num, row_data = get_today_row(ws)

    # --- STEP 1: First run of the day — calculate ORB ---
    if row_num is None:
        stock = pick_orb_stock()
        if not stock:
            print("No stock qualifies for ORB today (range outside 0.5-3%).")
            return

        orb_high = stock['high']
        orb_low = stock['low']
        orb_range = stock['range']
        range_pct = stock['range_pct']
        ticker = stock['ticker']
        name = stock['name']

        # Save ORB levels, status = WATCHING
        target_long = orb_high + orb_range * TARGET_MULT
        target_short = orb_low - orb_range * TARGET_MULT
        qty = int(POSITION_SIZE / orb_high)
        ws.append_row([today, name, round(orb_high, 1), round(orb_low, 1), round(range_pct, 2),
                      '', '', '', '', '', '', '', '', 'WATCHING'])

        send_telegram(f"📊 <b>ORB LEVELS — {name}</b> ({today})\n\n"
                     f"OR High: <b>{orb_high:.1f}</b>\n"
                     f"OR Low: <b>{orb_low:.1f}</b>\n"
                     f"Range: {range_pct:.2f}%\n\n"
                     f"🟢 BUY above {orb_high:.1f} → Target {target_long:.1f}\n"
                     f"🔴 SHORT below {orb_low:.1f} → Target {target_short:.1f}\n"
                     f"💰 Qty: {qty} | Risk: ₹{orb_range * SL_MULT * qty:,.0f} | Reward: ₹{orb_range * TARGET_MULT * qty:,.0f}\n"
                     f"⏰ Entry by 10:00 AM | Exit by 2:15 PM")
        print(f"ORB set: {name} High={orb_high:.1f}, Low={orb_low:.1f}, Range={range_pct:.2f}%")
        return

    # --- STEP 2: Already have today's row ---
    status = row_data.get('Status', '')

    # Already closed — do nothing
    if status == 'CLOSED':
        print("Today's trade already closed. Nothing to do.")
        return

    orb_high = float(row_data['OR High'])
    orb_low = float(row_data['OR Low'])
    orb_range = orb_high - orb_low

    # --- STEP 3: WATCHING — check for breakout ---
    if status == 'WATCHING':
        stock_name = row_data.get('Stock', '')
        ticker = stock_name + '.NS'
        today_data = get_stock_data(ticker)
        if len(today_data) < 4:
            return

        # Check candles after ORB period (after first 3 candles = 15 min)
        after_orb = today_data.iloc[3:]
        for _, candle in after_orb.iterrows():
            if float(candle['Close']) > orb_high:
                # LONG breakout
                entry = orb_high
                sl = entry - orb_range * SL_MULT
                target = entry + orb_range * TARGET_MULT
                ws.update(f'F{row_num}:I{row_num}', [['LONG', round(entry, 1), round(sl, 1), round(target, 1)]])
                ws.update(f'O{row_num}', [['IN TRADE']])
                qty = int(POSITION_SIZE / entry)

                send_telegram(f"🟢 <b>BUY — {stock_name}</b>\n\n"
                             f"Entry: {entry:.1f}\n"
                             f"Stop Loss: {sl:.1f}\n"
                             f"Target: {target:.1f}\n"
                             f"Qty: {qty}\n"
                             f"Risk: ₹{abs(sl - entry) * qty:,.0f}\n"
                             f"Reward: ₹{(target - entry) * qty:,.0f}\n"
                             f"⏰ Exit by 2:15 PM")
                print(f"LONG {stock_name} at {entry:.1f}")
                return

            elif float(candle['Close']) < orb_low:
                # SHORT breakout
                entry = orb_low
                sl = entry + orb_range * SL_MULT
                target = entry - orb_range * TARGET_MULT
                ws.update(f'F{row_num}:I{row_num}', [['SHORT', round(entry, 1), round(sl, 1), round(target, 1)]])
                ws.update(f'O{row_num}', [['IN TRADE']])
                qty = int(POSITION_SIZE / entry)

                send_telegram(f"🔴 <b>SHORT — {stock_name}</b>\n\n"
                             f"Entry: {entry:.1f}\n"
                             f"Stop Loss: {sl:.1f}\n"
                             f"Target: {target:.1f}\n"
                             f"Qty: {qty}\n"
                             f"Risk: ₹{abs(sl - entry) * qty:,.0f}\n"
                             f"Reward: ₹{(entry - target) * qty:,.0f}\n"
                             f"⏰ Exit by 2:15 PM")
                print(f"SHORT {stock_name} at {entry:.1f}")
                return

        # Check if 10:00 AM — cancel if no breakout (deadline)
        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if now_ist.hour >= 10:
            ws.update(f'F{row_num}', [['NO BREAKOUT']])
            ws.update(f'K{row_num}:O{row_num}', [[0, 0, 0, 'NO BREAKOUT', 'CLOSED']])
            send_telegram(f"⏰ <b>10:00 AM — No breakout in {stock_name}.</b> Order cancelled.")
            print("No breakout by 10:00 AM. Cancelled.")
            return

        print("Still watching for breakout...")
        return

    # --- STEP 4: IN TRADE — check SL/Target ---
    if status == 'IN TRADE':
        stock_name = row_data.get('Stock', '')
        ticker = stock_name + '.NS'
        signal = row_data['Signal']
        entry = float(row_data['Entry'])
        sl = float(row_data['SL'])
        target = float(row_data['Target'])
        qty = int(POSITION_SIZE / entry)

        today_data = get_stock_data(ticker)
        if len(today_data) < 4:
            return

        after_orb = today_data.iloc[3:]
        for _, candle in after_orb.iterrows():
            if signal == 'LONG':
                if float(candle['Low']) <= sl:
                    pnl = calc_pnl(entry, sl)[0]
                    ws.update(f'J{row_num}:O{row_num}', [[round(sl, 1), round(pnl + CHARGES), CHARGES, round(pnl), 'SL HIT', 'CLOSED']])
                    send_telegram(f"🔴 <b>SL HIT — {stock_name}</b>\nExit: {sl:.1f} | P&L: ₹{pnl:+,.0f}")
                    return
                if float(candle['High']) >= target:
                    pnl = calc_pnl(entry, target)[0]
                    ws.update(f'J{row_num}:O{row_num}', [[round(target, 1), round(pnl + CHARGES), CHARGES, round(pnl), 'TARGET', 'CLOSED']])
                    send_telegram(f"🟢 <b>TARGET HIT — {stock_name}</b> 🎉\nExit: {target:.1f} | P&L: ₹{pnl:+,.0f}")
                    return
            else:  # SHORT
                if float(candle['High']) >= sl:
                    pnl = calc_pnl(sl, entry)[0]  # loss: sl > entry for short
                    pnl = -abs(pnl)  # ensure negative
                    ws.update(f'J{row_num}:O{row_num}', [[round(sl, 1), round(pnl + CHARGES), CHARGES, round(pnl), 'SL HIT', 'CLOSED']])
                    send_telegram(f"🔴 <b>SL HIT — {stock_name}</b>\nExit: {sl:.1f} | P&L: ₹{pnl:+,.0f}")
                    return
                if float(candle['Low']) <= target:
                    pnl = calc_pnl(target, entry)[0]  # profit: target < entry for short
                    pnl = abs(pnl)
                    ws.update(f'J{row_num}:O{row_num}', [[round(target, 1), round(pnl + CHARGES), CHARGES, round(pnl), 'TARGET', 'CLOSED']])
                    send_telegram(f"🟢 <b>TARGET HIT — {stock_name}</b> 🎉\nExit: {target:.1f} | P&L: ₹{pnl:+,.0f}")
                    return

        # Check if 2:15 PM — EOD exit
        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if now_ist.hour >= 14 and now_ist.minute >= 15:
            current, _, _ = get_current_price(ticker)
            if current:
                if signal == 'LONG':
                    pnl = calc_pnl(entry, current)[0]
                else:
                    pnl = int((entry - current) * qty) - CHARGES
                ws.update(f'J{row_num}:O{row_num}', [[round(current, 1), round(pnl + CHARGES), CHARGES, round(pnl), 'EOD EXIT', 'CLOSED']])
                send_telegram(f"⏰ <b>EOD EXIT — {stock_name}</b> (2:15 PM)\nExit: {current:.1f} | P&L: ₹{pnl:+,.0f}")

        print(f"In trade {stock_name}. Monitoring...")


if __name__ == "__main__":
    run()
