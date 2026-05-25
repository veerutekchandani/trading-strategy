"""
VOLUME BREAKOUT SWING — DAILY SCANNER + AUTO PAPER TRADING
============================================================
Runs every evening after market close (3:45 PM IST).
1. Checks open positions — exits if SL/TGT/Day5 hit
2. Scans for new signals if slots available
3. Auto-enters paper trades in Google Sheet
4. Sends Telegram alerts

Env vars:
  GCP_SERVICE_ACCOUNT
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
"""

import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import requests
import json
import os
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# --- CONFIG ---
MAX_POSITIONS = 3
SL_ATR_MULT = 1.5
TGT_ATR_MULT = 2.5
MAX_HOLD_DAYS = 5
MIN_VOL_RATIO = 2.5
MIN_RET_20D = 0.10
MAX_ATR_PCT = 4.0
MIN_CLOSE_POS = 0.7
CAPITAL = 500000
LEVERAGE = 5
BUDGET_PER_POS = CAPITAL * LEVERAGE / MAX_POSITIONS  # ~₹8.33L notional
SHEET_NAME = "Momentum Strategy"
LOT_SIZE_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

FNO_STOCKS = [
    'RELIANCE','TCS','HDFCBANK','ICICIBANK','INFY','HINDUNILVR','ITC','SBIN','BHARTIARTL','BAJFINANCE',
    'LT','HCLTECH','AXISBANK','KOTAKBANK','TITAN','ASIANPAINT','MARUTI','SUNPHARMA','TATAMOTORS','NTPC',
    'ULTRACEMCO','BAJAJFINSV','WIPRO','ONGC','JSWSTEEL','POWERGRID','ADANIENT','ADANIPORTS','TATASTEEL','COALINDIA',
    'NESTLEIND','TECHM','HDFCLIFE','GRASIM','APOLLOHOSP','DIVISLAB','BPCL','CIPLA','DRREDDY','EICHERMOT',
    'SBILIFE','BRITANNIA','HINDALCO','INDUSINDBK','BAJAJ-AUTO','TATACONSUM','GODREJCP','HEROMOTOCO','VEDL','M&M',
    'DABUR','PIDILITIND','HAVELLS','SIEMENS','AMBUJACEM','ACC','BIOCON','BANDHANBNK','CHOLAFIN',
    'COLPAL','CONCOR','DLF','GAIL','ICICIPRULI','IDFCFIRSTB','INDIGO','IOC','IRCTC','JUBLFOOD',
    'LUPIN','MARICO','MUTHOOTFIN','NAUKRI','PAGEIND','PETRONET','PFC',
    'PIIND','PNB','RECLTD','SBICARD','SHREECEM','SRF','TATAPOWER','TORNTPHARM','TRENT','UPL',
    'VOLTAS','JSWENERGY','CANBK','UNIONBANK','BANKBARODA','HAL','BEL',
    'ALKEM','AUROPHARMA','BALKRISIND','BATAINDIA','BHEL','BOSCHLTD','CANFINHOME',
    'COFORGE','CROMPTON','CUMMINSIND','DEEPAKNTR','DIXON','ESCORTS','EXIDEIND','FEDERALBNK',
    'FORTIS','GLENMARK','GNFC','GRANULES','HDFCAMC','HINDPETRO',
    'IPCALAB','JINDALSTEL','JKCEMENT','KPITTECH','LALPATHLAB','LAURUSLABS',
    'LICHSGFIN','LTTS','MANAPPURAM','MFSL','MOTHERSON','MPHASIS','MRF','NATIONALUM',
    'NAVINFLUOR','NHPC','NMDC','OBEROIRLTY','PERSISTENT','POLYCAB',
    'RAMCOCEM','RBLBANK','SAIL','SUNTV','SYNGENE',
    'TATACHEM','TATACOMM','TATAELXSI','TVSMOTOR','UBL',
    'ZYDUSLIFE','ASTRAL','BDL','CDSL','CYIENT','DALBHARAT',
    'GODREJIND','HINDCOPPER','HUDCO','INDHOTEL','MCX','METROPOLIS',
    'SHRIRAMFIN','SJVN',
]


def get_sheet():
    creds_json = os.environ.get('GCP_SERVICE_ACCOUNT', '')
    creds_dict = json.loads(creds_json)
    if 'private_key' in creds_dict:
        creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME)


def send_telegram(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        print(f"[Telegram disabled] {message}")
        return
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'})


def get_live_price(stock):
    try:
        df = yf.download(stock + '.NS', period='5d', progress=False)
        df.columns = df.columns.get_level_values(0)
        if len(df) > 0:
            return float(df['Close'].iloc[-1])
    except:
        pass
    return None


def fetch_lot_sizes():
    """Fetch live lot sizes from Fyers symbol master."""
    try:
        r = requests.get(LOT_SIZE_URL, timeout=10)
        lots = {}
        for line in r.text.strip().split('\n'):
            parts = line.split(',')
            if len(parts) < 14: continue
            if 'FUT' not in parts[1]: continue
            underlying = parts[13]
            lot = int(parts[3]) if parts[3].isdigit() else 0
            if lot > 0 and underlying not in lots:
                if underlying in ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX']: continue
                lots[underlying] = lot
        return lots
    except:
        # Fallback: load from saved file
        try:
            import json
            with open(os.path.join(os.path.dirname(__file__), 'fno_lot_sizes.json')) as f:
                return json.load(f)
        except:
            return {}


def check_nifty_regime():
    try:
        df = yf.download('^NSEI', period='3mo', progress=False)
        df.columns = df.columns.get_level_values(0)
        ema50 = float(df['Close'].ewm(span=50).mean().iloc[-1])
        close = float(df['Close'].iloc[-1])
        return close > ema50, close, ema50
    except:
        return True, 0, 0


def manage_open_trades(swing_ws):
    """Check open trades — exit if SL hit, TGT hit, or Day 5 reached."""
    records = swing_ws.get_all_records()
    open_trades = [r for r in records if r.get('Status') == 'OPEN']
    closed_today = []
    today = datetime.now()

    for trade in open_trades:
        stock = trade['Stock']
        entry = float(trade['Entry'])
        sl = float(trade['SL'])
        target = float(trade['Target'])
        entry_date = datetime.strptime(trade['Date'], '%Y-%m-%d')
        days_held = (today - entry_date).days

        live_price = get_live_price(stock)
        if not live_price:
            continue

        exit_reason = None
        exit_price = None

        if live_price <= sl:
            exit_reason = 'SL'
            exit_price = sl
        elif live_price >= target:
            exit_reason = 'TGT'
            exit_price = target
        elif days_held >= MAX_HOLD_DAYS:
            exit_reason = 'DAY5'
            exit_price = live_price

        if exit_reason:
            qty = int(trade.get('Qty', 0))
            pnl = (exit_price - entry) * qty
            charges = qty * entry * 0.0006 + 40  # STT + exchange + brokerage
            net_pnl = round(pnl - charges)

            # Update row in sheet
            row_idx = records.index(trade) + 2  # +2 for header + 1-indexed
            swing_ws.update(f'G{row_idx}:K{row_idx}', [[
                round(exit_price, 2), exit_reason, today.strftime('%Y-%m-%d'),
                net_pnl, 'CLOSED'
            ]])
            closed_today.append({'stock': stock, 'reason': exit_reason, 'pnl': net_pnl})

    return open_trades, closed_today


def scan_stocks():
    """Scan for volume breakout signals with real lot sizes."""
    lot_sizes = fetch_lot_sizes()
    signals = []
    for stock in FNO_STOCKS:
        try:
            lot = lot_sizes.get(stock)
            if not lot:
                continue

            df = yf.download(stock + '.NS', period='3mo', progress=False)
            df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Close'])
            if len(df) < 55:
                continue

            close = float(df['Close'].iloc[-1])

            # Check affordability
            lot_value = lot * close
            if lot_value > BUDGET_PER_POS:
                continue
            num_lots = 2 if (lot * close * 2) <= BUDGET_PER_POS else 1
            qty = num_lots * lot

            high = float(df['High'].iloc[-1])
            low = float(df['Low'].iloc[-1])
            volume = float(df['Volume'].iloc[-1])

            ema20 = float(df['Close'].ewm(span=20).mean().iloc[-1])
            ema50 = float(df['Close'].ewm(span=50).mean().iloc[-1])
            if ema20 <= ema50:
                continue

            avg_vol = float(df['Volume'].rolling(20).mean().iloc[-1])
            if avg_vol == 0:
                continue
            vol_ratio = volume / avg_vol
            if vol_ratio < MIN_VOL_RATIO:
                continue

            day_range = high - low
            if day_range == 0:
                continue
            close_pos = (close - low) / day_range
            if close_pos < MIN_CLOSE_POS:
                continue

            ret_20d = close / float(df['Close'].iloc[-21]) - 1 if len(df) > 21 else 0
            if ret_20d < MIN_RET_20D:
                continue

            atr = float((df['High'] - df['Low']).rolling(14).mean().iloc[-1])
            atr_pct = atr / close * 100
            if atr_pct > MAX_ATR_PCT:
                continue

            sl = round(close - SL_ATR_MULT * atr, 2)
            target = round(close + TGT_ATR_MULT * atr, 2)

            signals.append({
                'stock': stock, 'price': round(close, 2),
                'lot_size': lot, 'num_lots': num_lots, 'qty': qty,
                'position_value': round(lot_value * num_lots),
                'vol_ratio': round(vol_ratio, 1), 'ret_20d': round(ret_20d * 100, 1),
                'atr': round(atr, 2), 'sl': sl, 'target': target,
                'sl_pct': round((close - sl) / close * 100, 1),
                'tgt_pct': round((target - close) / close * 100, 1),
            })
        except:
            continue

    signals.sort(key=lambda x: x['ret_20d'], reverse=True)
    return signals


def enter_paper_trades(swing_ws, signals, slots_available):
    """Auto-enter top signals as paper trades in sheet."""
    today = datetime.now().strftime('%Y-%m-%d')
    new_entries = []

    for s in signals[:slots_available]:
        # Add row: Date, Stock, Entry, SL, Target, Qty, Day, Exit, Exit Reason, Exit Date, P&L, Status
        swing_ws.append_row([
            today, s['stock'], s['price'], s['sl'], s['target'],
            s['qty'], 1, '', '', '', '', 'OPEN'
        ])
        new_entries.append(s)

    return new_entries


def run():
    today = datetime.now()
    print(f"[{today.strftime('%Y-%m-%d %H:%M')}] Swing Scanner running...")

    # Check Nifty regime
    nifty_ok, nifty_close, nifty_ema50 = check_nifty_regime()
    if not nifty_ok:
        msg = f"🛑 <b>SWING — MARKET OFF</b>\nNifty ({nifty_close:,.0f}) < 50 EMA ({nifty_ema50:,.0f}). No trades."
        send_telegram(msg)
        print("Nifty below 50 EMA.")
        return

    # Get sheet
    try:
        spreadsheet = get_sheet()
        try:
            swing_ws = spreadsheet.worksheet("Swing")
        except:
            swing_ws = spreadsheet.add_worksheet("Swing", rows=1000, cols=12)
            swing_ws.update('A1:L1', [['Date','Stock','Entry','SL','Target','Qty','Day','Exit','Exit Reason','Exit Date','P&L','Status']])
    except Exception as e:
        print(f"Sheet error: {e}")
        return

    # Step 1: Manage open trades (check SL/TGT/Day5)
    open_trades, closed_today = manage_open_trades(swing_ws)
    current_open = len([t for t in open_trades if t['Stock'] not in [c['stock'] for c in closed_today]])

    # Step 2: Send exit alerts
    if closed_today:
        msg = f"📤 <b>SWING EXITS — {today.strftime('%d %b')}</b>\n\n"
        for c in closed_today:
            emoji = '🟢' if c['pnl'] > 0 else '🔴'
            msg += f"{emoji} {c['stock']} | {c['reason']} | ₹{c['pnl']:+,.0f}\n"
        send_telegram(msg)

    # Step 3: Scan for new signals if slots available
    slots = MAX_POSITIONS - current_open
    if slots <= 0:
        print(f"All {MAX_POSITIONS} slots full. No scan needed.")
        return

    print(f"{slots} slot(s) available. Scanning...")
    signals = scan_stocks()

    # Filter out stocks already in open positions
    open_stocks = [t['Stock'] for t in open_trades if t['Stock'] not in [c['stock'] for c in closed_today]]
    signals = [s for s in signals if s['stock'] not in open_stocks]

    if not signals:
        print("No signals today.")
        return

    # Step 4: Auto-enter paper trades
    new_entries = enter_paper_trades(swing_ws, signals, slots)

    # Step 5: Send entry alert
    msg = f"🔥 <b>SWING ENTRY — {today.strftime('%d %b')}</b>\n"
    msg += f"<i>Nifty: {nifty_close:,.0f} ✅ | {current_open + len(new_entries)}/{MAX_POSITIONS} positions</i>\n\n"
    for s in new_entries:
        msg += f"<b>{s['stock']}</b> @ ₹{s['price']}\n"
        msg += f"  📦 Lot: {s['lot_size']} × {s['num_lots']} = {s['qty']} shares (₹{s['position_value']:,})\n"
        msg += f"  🛑 SL (GTT): ₹{s['sl']} (-{s['sl_pct']}%)\n"
        msg += f"  🎯 Target: ₹{s['target']} (+{s['tgt_pct']}%)\n"
        msg += f"  📊 Vol: {s['vol_ratio']}x | Mom: +{s['ret_20d']}%\n\n"
    send_telegram(msg)
    print(f"Entered {len(new_entries)} new trades.")


if __name__ == "__main__":
    run()
