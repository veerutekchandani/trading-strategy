"""
INTRADAY ORB — AUTOMATED CRON SCRIPT
======================================
Runs every 5 min (10:15 AM - 3:15 PM IST) via GitHub Actions.
- Calculates ORB levels at 10:15 AM
- Monitors for breakout
- Logs entry/exit to Google Sheets
- Sends Telegram alerts
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
LOT_SIZE = 65
MIN_RANGE = 50
MAX_RANGE = 250
TARGET_MULT = 1.5

# Zerodha F&O Futures charges per trade
CHARGES = 912  # STT ₹764 + Brokerage ₹40 + Transaction ₹56 + GST ₹18 + Stamp ₹31 + SEBI ₹3

def calc_pnl(nifty_move):
    """Calculate P&L for futures after charges."""
    gross = round(nifty_move * LOT_SIZE)
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
        ws = spreadsheet.add_worksheet(TAB_NAME, rows=500, cols=14)
        ws.update('A1:O1', [['Date', 'OR High', 'OR Low', 'Range', 'Signal',
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
def get_nifty_data():
    """Get today's 5-min data."""
    df = yf.download('^NSEI', period='5d', interval='5m', progress=False)
    df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    today = datetime.now().date()
    today_data = df[df.index.date == today]
    return today_data


def get_current_price():
    """Get latest Nifty price."""
    df = yf.download('^NSEI', period='1d', interval='5m', progress=False)
    df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    if len(df) > 0:
        return float(df['Close'].iloc[-1]), float(df['High'].iloc[-1]), float(df['Low'].iloc[-1])
    return None, None, None


# --- MAIN LOGIC ---
def run():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ORB Cron running...")

    ws = get_sheet()
    today = datetime.now().strftime('%Y-%m-%d')
    row_num, row_data = get_today_row(ws)

    # --- STEP 1: First run of the day — calculate ORB ---
    if row_num is None:
        today_data = get_nifty_data()
        if len(today_data) < 12:
            print("Market not open yet or insufficient data.")
            return

        first_30 = today_data.iloc[:12]  # First hour = 12 candles of 5-min
        orb_high = float(first_30['High'].max())
        orb_low = float(first_30['Low'].min())
        orb_range = orb_high - orb_low

        if orb_range < MIN_RANGE or orb_range > MAX_RANGE:
            # No trade today
            ws.append_row([today, round(orb_high, 1), round(orb_low, 1), round(orb_range, 1),
                          'NO TRADE', '', '', '', '', 0, 0, 0, f'Range {orb_range:.0f} outside {MIN_RANGE}-{MAX_RANGE}', 'CLOSED'])
            send_telegram(f"⚠️ <b>ORB — NO TRADE TODAY</b>\n\n"
                         f"Range: {orb_range:.0f} pts (outside {MIN_RANGE}-{MAX_RANGE})\n"
                         f"OR High: {orb_high:.1f}\nOR Low: {orb_low:.1f}")
            print(f"No trade — range {orb_range:.0f} outside limits.")
            return

        # Save ORB levels, status = WATCHING
        target_long = orb_high + orb_range * TARGET_MULT
        target_short = orb_low - orb_range * TARGET_MULT
        ws.append_row([today, round(orb_high, 1), round(orb_low, 1), round(orb_range, 1),
                      '', '', '', '', '', '', '', '', '', 'WATCHING'])

        send_telegram(f"📊 <b>ORB LEVELS SET</b> — {today}\n\n"
                     f"OR High: <b>{orb_high:.1f}</b>\n"
                     f"OR Low: <b>{orb_low:.1f}</b>\n"
                     f"Range: {orb_range:.0f} pts\n\n"
                     f"🟢 BUY above {orb_high:.1f} → Target {target_long:.1f}\n"
                     f"🔴 SHORT below {orb_low:.1f} → Target {target_short:.1f}\n"
                     f"💰 Risk: ₹{orb_range * LOT_SIZE:,.0f} | Reward: ₹{orb_range * TARGET_MULT * LOT_SIZE:,.0f}")
        print(f"ORB set: High={orb_high:.1f}, Low={orb_low:.1f}, Range={orb_range:.0f}")
        return

    # --- STEP 2: Already have today's row ---
    status = row_data.get('Status', '')

    # Already closed — do nothing
    if status == 'CLOSED':
        print("Today's trade already closed. Nothing to do.")
        return

    orb_high = float(row_data['OR High'])
    orb_low = float(row_data['OR Low'])
    orb_range = float(row_data['Range'])

    # --- STEP 3: WATCHING — check for breakout ---
    if status == 'WATCHING':
        today_data = get_nifty_data()
        if len(today_data) < 13:
            return

        # Check candles after ORB period for breakout
        after_orb = today_data.iloc[12:]
        for _, candle in after_orb.iterrows():
            if float(candle['Close']) > orb_high:
                # LONG breakout
                entry = orb_high
                sl = orb_low
                target = entry + orb_range * TARGET_MULT
                ws.update(f'E{row_num}:H{row_num}', [['LONG', round(entry, 1), round(sl, 1), round(target, 1)]])
                ws.update(f'O{row_num}', [['IN TRADE']])

                send_telegram(f"🟢 <b>BUY SIGNAL — ENTRY!</b>\n\n"
                             
                             f"Direction: LONG\n"
                             f"Entry: {entry:.1f}\n"
                             f"Stop Loss: {sl:.1f}\n"
                             f"Target: {target:.1f}\n"
                             f"Risk: ₹{abs(calc_pnl(sl - entry)[0]):,.0f}\n"
                             f"Reward: ₹{calc_pnl(target - entry)[0]:,.0f}\n"
                             f"⏰ Exit by 3:15 PM")
                print(f"LONG entry at {entry:.1f}")
                return

            elif float(candle['Close']) < orb_low:
                # SHORT breakout
                entry = orb_low
                sl = orb_high
                target = entry - orb_range * TARGET_MULT
                ws.update(f'E{row_num}:H{row_num}', [['SHORT', round(entry, 1), round(sl, 1), round(target, 1)]])
                ws.update(f'O{row_num}', [['IN TRADE']])

                send_telegram(f"🔴 <b>SHORT SIGNAL — ENTRY!</b>\n\n"
                             
                             f"Direction: SHORT\n"
                             f"Entry: {entry:.1f}\n"
                             f"Stop Loss: {sl:.1f}\n"
                             f"Target: {target:.1f}\n"
                             f"Risk: ₹{abs(calc_pnl(entry - sl)[0]):,.0f}\n"
                             f"Reward: ₹{calc_pnl(entry - target)[0]:,.0f}\n"
                             f"⏰ Exit by 3:15 PM")
                print(f"SHORT entry at {entry:.1f}")
                return

        # Check if it's 3:15 PM — close as no breakout
        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if now_ist.hour >= 15 and now_ist.minute >= 15:
            ws.update(f'E{row_num}', [['NO BREAKOUT']])
            ws.update(f'J{row_num}:P{row_num}', [[0, 0, 0, 'NO BREAKOUT', 'CLOSED']])
            send_telegram("⏰ <b>Market closing — No breakout today.</b> No trade taken.")
            print("No breakout by 3:15 PM. Day closed.")

        print("Still watching for breakout...")
        return

    # --- STEP 4: IN TRADE — check SL/Target ---
    if status == 'IN TRADE':
        signal = row_data['Signal']
        entry = float(row_data['Entry'])
        sl = float(row_data['SL'])
        target = float(row_data['Target'])

        today_data = get_nifty_data()
        if len(today_data) < 13:
            return

        # Check recent candles for SL/Target hit
        after_orb = today_data.iloc[12:]
        for _, candle in after_orb.iterrows():
            if signal == 'LONG':
                if float(candle['Low']) <= sl:
                    pnl = calc_pnl(sl - entry)[0]
                    ws.update(f'I{row_num}:P{row_num}', [[round(sl, 1), '', get_charges(), round(pnl), 'SL HIT', 'CLOSED']])
                    send_telegram(f"🔴 <b>STOP LOSS HIT</b>\n\n"
                                 f"Exit: {sl:.1f}\nP&L: ₹{pnl:+,.0f}\nResult: SL HIT")
                    print(f"SL hit. P&L: ₹{pnl:+,.0f}")
                    return
                if float(candle['High']) >= target:
                    pnl = calc_pnl(target - entry)[0]
                    ws.update(f'I{row_num}:P{row_num}', [[round(target, 1), '', get_charges(), round(pnl), 'TARGET', 'CLOSED']])
                    send_telegram(f"🟢 <b>TARGET HIT!</b> 🎉\n\n"
                                 f"Exit: {target:.1f}\nP&L: ₹{pnl:+,.0f}\nResult: TARGET HIT")
                    print(f"Target hit! P&L: ₹{pnl:+,.0f}")
                    return
            else:  # SHORT
                if float(candle['High']) >= sl:
                    pnl = calc_pnl(entry - sl)[0]
                    ws.update(f'I{row_num}:P{row_num}', [[round(sl, 1), '', get_charges(), round(pnl), 'SL HIT', 'CLOSED']])
                    send_telegram(f"🔴 <b>STOP LOSS HIT</b>\n\n"
                                 f"Exit: {sl:.1f}\nP&L: ₹{pnl:+,.0f}\nResult: SL HIT")
                    print(f"SL hit. P&L: ₹{pnl:+,.0f}")
                    return
                if float(candle['Low']) <= target:
                    pnl = calc_pnl(entry - target)[0]
                    ws.update(f'I{row_num}:P{row_num}', [[round(target, 1), '', get_charges(), round(pnl), 'TARGET', 'CLOSED']])
                    send_telegram(f"🟢 <b>TARGET HIT!</b> 🎉\n\n"
                                 f"Exit: {target:.1f}\nP&L: ₹{pnl:+,.0f}\nResult: TARGET HIT")
                    print(f"Target hit! P&L: ₹{pnl:+,.0f}")
                    return

        # Check if 3:15 PM — force exit
        now_ist = datetime.utcnow() + timedelta(hours=5, minutes=30)
        if now_ist.hour >= 15 and now_ist.minute >= 15:
            current, _, _ = get_current_price()
            if current:
                if signal == 'LONG':
                    pnl = calc_pnl(current - entry)[0]
                else:
                    pnl = calc_pnl(entry - current)[0]
                ws.update(f'I{row_num}:P{row_num}', [[round(current, 1), '', get_charges(), round(pnl), 'EOD EXIT', 'CLOSED']])
                send_telegram(f"⏰ <b>EOD EXIT</b> (3:15 PM)\n\n"
                             f"Exit: {current:.1f}\nP&L: ₹{pnl:+,.0f}\nResult: EOD EXIT")
                print(f"EOD exit at {current:.1f}. P&L: ₹{pnl:+,.0f}")
            return

        print("In trade, monitoring SL/Target...")


if __name__ == "__main__":
    run()
