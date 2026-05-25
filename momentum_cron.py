"""
MONTHLY MOMENTUM — AUTO REBALANCE CRON (v2)
=============================================
Runs on last trading day of EVERY month.
Calculates top 3 momentum stocks with filters:
  - 3/3 consistency (all 3 lookback months positive)
  - Within 10% of 52-week high
  - 20% SL monitored daily
Logs to Google Sheets + sends Telegram alert.

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
import pandas as pd
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# --- CONFIG ---
SHEET_NAME = "Momentum Strategy"
TOP_N = 3
LOOKBACK_MONTHS = 3
SKIP_MONTHS = []  # Trade all months now
DELIVERY_CHARGE_PCT = 0.0011  # 0.11% per side
SL_PCT = 0.20  # 20% stop loss per stock

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

NIFTY_100 = [
    'RELIANCE.NS','TCS.NS','HDFCBANK.NS','INFY.NS','ICICIBANK.NS',
    'HINDUNILVR.NS','ITC.NS','SBIN.NS','BHARTIARTL.NS','KOTAKBANK.NS',
    'LT.NS','AXISBANK.NS','ASIANPAINT.NS','MARUTI.NS','TITAN.NS',
    'SUNPHARMA.NS','ULTRACEMCO.NS','WIPRO.NS','HCLTECH.NS','BAJFINANCE.NS',
    'NESTLEIND.NS','POWERGRID.NS','NTPC.NS','ONGC.NS','TATASTEEL.NS',
    'ADANIENT.NS','ADANIPORTS.NS','APOLLOHOSP.NS','BAJAJ-AUTO.NS','BAJAJFINSV.NS',
    'BPCL.NS','BRITANNIA.NS','CIPLA.NS','COALINDIA.NS','DIVISLAB.NS',
    'DRREDDY.NS','EICHERMOT.NS','GRASIM.NS','HDFCLIFE.NS','HEROMOTOCO.NS',
    'HINDALCO.NS','INDUSINDBK.NS','JSWSTEEL.NS','M&M.NS','SBILIFE.NS',
    'SHRIRAMFIN.NS','TATACONSUM.NS','TECHM.NS',
    'ABB.NS','AMBUJACEM.NS','BANKBARODA.NS','BEL.NS','BERGEPAINT.NS',
    'BOSCHLTD.NS','CANBK.NS','CHOLAFIN.NS','COLPAL.NS','DLF.NS',
    'GAIL.NS','GODREJCP.NS','HAL.NS','HAVELLS.NS','ICICIPRULI.NS',
    'INDIGO.NS','IOC.NS','IRCTC.NS','JINDALSTEL.NS',
    'LUPIN.NS','MARICO.NS','MOTHERSON.NS','NAUKRI.NS','NHPC.NS',
    'PIDILITIND.NS','PNB.NS','RECLTD.NS','SBICARD.NS','SIEMENS.NS',
    'SRF.NS','TATAPOWER.NS','TORNTPHARM.NS','TRENT.NS',
    'VEDL.NS','ZYDUSLIFE.NS','DABUR.NS',
    'PFC.NS','POLYCAB.NS','PERSISTENT.NS','PIIND.NS',
    'MAXHEALTH.NS','MANKIND.NS','JSWENERGY.NS','CUMMINSIND.NS',
    'ETERNAL.NS','TVSMOTOR.NS','INDHOTEL.NS','LICI.NS','LTIM.NS','JIOFIN.NS','DMART.NS',
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


def get_momentum_ranking():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=300)  # need 252 days for 52w high
    results = []
    for ticker in NIFTY_100:
        try:
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Close'])
            if len(df) < 63:
                continue

            current = float(df['Close'].iloc[-1])
            lookback_days = LOOKBACK_MONTHS * 21

            # 3-month momentum
            past = float(df['Close'].iloc[-lookback_days])
            if past <= 0:
                continue
            momentum = ((current / past) - 1) * 100

            # Filter 1: 3/3 consistency — each month must be positive
            m1_ret = float(df['Close'].iloc[-1]) / float(df['Close'].iloc[-21]) - 1
            m2_ret = float(df['Close'].iloc[-21]) / float(df['Close'].iloc[-42]) - 1
            m3_ret = float(df['Close'].iloc[-42]) / float(df['Close'].iloc[-63]) - 1
            if m1_ret <= 0 or m2_ret <= 0 or m3_ret <= 0:
                continue

            # Filter 2: Within 10% of 52-week high
            high_52w = float(df['High'].tail(252).max())
            dist_from_high = (current / high_52w - 1) * 100
            if dist_from_high < -10:
                continue

            results.append({'stock': ticker.replace('.NS', ''), 'ticker': ticker,
                           'price': current, 'momentum': momentum,
                           'dist_52w': round(dist_from_high, 1)})
        except:
            pass
    return sorted(results, key=lambda x: x['momentum'], reverse=True)[:TOP_N]



def get_live_price(ticker):
    """Get live price from 5-min data."""
    try:
        df = yf.download(ticker, period="1d", interval="5m", progress=False)
        df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if len(df) > 0:
            return float(df["Close"].iloc[-1])
    except:
        pass
    return None

def is_last_trading_day():
    """Check if today is the last trading day of the month."""
    today = datetime.now()
    # Check if next trading day is in a different month
    next_day = today + timedelta(days=1)
    while next_day.weekday() >= 5:  # skip weekends
        next_day += timedelta(days=1)
    return next_day.month != today.month


def check_stop_losses():
    """
    NOTE: Stop losses are handled via GTT (Good Till Triggered) orders
    placed on Kite at buy time. This function only checks if any GTT
    was triggered and updates the sheet accordingly.
    
    GTT order is placed at: buy_price × 0.80 (20% below entry)
    The broker auto-executes when price hits SL — no manual intervention needed.
    """
    today = datetime.now()
    print(f"[{today.strftime('%Y-%m-%d %H:%M')}] Checking if any SL was triggered...")

    try:
        spreadsheet = get_sheet()
        portfolio_ws = spreadsheet.worksheet("Portfolio")
        config_ws = spreadsheet.worksheet("Config")
        trades_ws = spreadsheet.worksheet("Trades")
        holdings = portfolio_ws.get_all_records()
    except:
        print("Could not access sheets.")
        return

    config = {r['Key']: r['Value'] for r in config_ws.get_all_records()}
    cash = float(config.get('cash', 200000))
    today_str = today.strftime('%Y-%m-%d')
    sl_triggered = []

    for h in holdings:
        if not h.get('Stock'):
            continue
        ticker = h['Stock'] + '.NS'
        buy_price = float(h['Buy Price'])
        sl_price = buy_price * (1 - SL_PCT)

        # Check if current price is below SL (means GTT was triggered)
        live_price = get_live_price(ticker)
        if live_price and live_price <= sl_price:
            qty = int(h['Qty'])
            proceeds = qty * sl_price  # GTT executes at SL price
            sell_charges = round(proceeds * DELIVERY_CHARGE_PCT, 2)
            proceeds -= sell_charges
            pnl = proceeds - (qty * buy_price)
            cash += proceeds
            sl_triggered.append(h['Stock'])
            trades_ws.append_row([today_str, 'SL_EXIT', h['Stock'], qty, round(sl_price, 2), round(proceeds, 2), round(pnl, 2)])

    if sl_triggered:
        remaining = [h for h in holdings if h.get('Stock') and h['Stock'] not in sl_triggered]
        portfolio_ws.clear()
        portfolio_ws.update('A1:F1', [['Stock', 'Qty', 'Buy Price', 'Buy Date', 'Current Price', 'P&L %']])
        if remaining:
            rows = [[h['Stock'], h['Qty'], h['Buy Price'], h['Buy Date'], h['Current Price'], h['P&L %']] for h in remaining]
            portfolio_ws.update(f'A2:F{len(rows)+1}', rows)
        config_ws.update('B2', [[str(round(cash, 2))]])

        msg = f"🛑 <b>STOP LOSS TRIGGERED (GTT)</b>\n\n"
        msg += f"Exited: {', '.join(sl_triggered)}\n"
        msg += f"SL Price: {(1-SL_PCT)*100:.0f}% of buy price\n"
        msg += f"💵 Cash: ₹{cash:,.0f}"
        send_telegram(msg)
        print(f"SL triggered: {sl_triggered}")
    else:
        print("No SL hits today.")


def run():
    today = datetime.now()
    print(f"[{today.strftime('%Y-%m-%d %H:%M')}] Monthly Momentum Cron running...")

    # Only run on last trading day
    if not is_last_trading_day():
        print("Not the last trading day of the month. Skipping.")
        return

    print("Last trading day detected. Running rebalance...")

    spreadsheet = get_sheet()
    config_ws = spreadsheet.worksheet("Config")
    portfolio_ws = spreadsheet.worksheet("Portfolio")
    trades_ws = spreadsheet.worksheet("Trades")
    monthly_ws = spreadsheet.worksheet("Monthly")

    # Get cash and current holdings
    config = {r['Key']: r['Value'] for r in config_ws.get_all_records()}
    cash = float(config.get('cash', 200000))
    starting_capital = float(config.get('starting_capital', 200000))

    holdings = portfolio_ws.get_all_records()
    current_stocks = [h['Stock'] for h in holdings if h.get('Stock')]

    # Get new top 5
    print("Calculating momentum rankings...")
    top5 = get_momentum_ranking()
    new_stocks = [s['stock'] for s in top5]

    to_sell = [s for s in current_stocks if s not in new_stocks]
    to_buy = [s for s in new_stocks if s not in current_stocks]
    to_keep = [s for s in current_stocks if s in new_stocks]

    today_str = today.strftime('%Y-%m-%d')

    # Sell
    kept_holdings = []
    for h in holdings:
        if not h.get('Stock'):
            continue
        if h['Stock'] in to_sell:
            ticker = h['Stock'] + '.NS'
            try:
                df = yf.download(ticker, period='1d', interval='5m', progress=False)
                df.columns = df.columns.get_level_values(0)
                price = float(df['Close'].dropna().iloc[-1])
            except:
                price = float(h['Buy Price'])
            qty = int(h['Qty'])
            proceeds = qty * price
            sell_charges = round(proceeds * DELIVERY_CHARGE_PCT, 2)
            proceeds -= sell_charges
            pnl = proceeds - (qty * float(h['Buy Price']))
            cash += proceeds
            trades_ws.append_row([today_str, 'SELL', h['Stock'], qty, round(price, 2), round(proceeds, 2), round(pnl, 2)])
        else:
            kept_holdings.append(h)

    # Buy
    new_buys = []
    if to_buy:
        amount_per_stock = cash / len(to_buy)
        for s in top5:
            if s['stock'] in to_buy:
                live_p = get_live_price(s['ticker'])
                price = live_p if live_p else s['price']
                qty = int(amount_per_stock / price)
                if qty > 0:
                    cost = qty * price
                    buy_charges = round(cost * DELIVERY_CHARGE_PCT, 2)
                    cost += buy_charges
                    cash -= cost
                    new_buys.append({
                        'Stock': s['stock'], 'Qty': qty,
                        'Buy Price': round(price, 2),
                        'Buy Date': today_str,
                        'Current Price': round(price, 2),
                        'P&L %': 0
                    })
                    trades_ws.append_row([today_str, 'BUY', s['stock'], qty, round(price, 2), round(cost, 2), f'-{buy_charges}'])

    # Update portfolio
    all_holdings = kept_holdings + new_buys
    portfolio_ws.clear()
    portfolio_ws.update('A1:F1', [['Stock', 'Qty', 'Buy Price', 'Buy Date', 'Current Price', 'P&L %']])
    if all_holdings:
        rows = [[h['Stock'], h['Qty'], h['Buy Price'], h['Buy Date'], h['Current Price'], h['P&L %']] for h in all_holdings]
        portfolio_ws.update(f'A2:F{len(rows)+1}', rows)

    # Update cash
    config_ws.update('B2', [[str(round(cash, 2))]])

    # Monthly record
    total_value = cash + sum(int(h['Qty']) * float(h['Buy Price']) for h in all_holdings)
    ret_pct = (total_value / starting_capital - 1) * 100
    stocks_str = ', '.join(h['Stock'] for h in all_holdings)
    monthly_ws.append_row([today.strftime('%b %Y'), round(total_value, 0), round(ret_pct, 1), stocks_str])

    # Telegram
    msg = f"📈 <b>MOMENTUM REBALANCE v2 — {today.strftime('%b %Y')}</b>\n"
    msg += f"<i>Top 3 | 3/3 consistency | 52w high filter | 20% SL</i>\n\n"
    if to_keep:
        msg += f"✅ Keep: {', '.join(to_keep)}\n"
    if to_sell:
        msg += f"📤 Sold: {', '.join(to_sell)}\n"
    if to_buy:
        msg += f"📥 Bought: {', '.join(to_buy)}\n"
    msg += f"\n💰 Portfolio: ₹{total_value:,.0f} ({ret_pct:+.1f}%)\n"
    msg += f"💵 Cash: ₹{cash:,.0f}\n"
    msg += f"\n📋 Holdings: {stocks_str}"
    send_telegram(msg)

    # Send GTT reminder for new buys
    if new_buys:
        gtt_msg = f"⚠️ <b>PLACE GTT SELL ORDERS ON KITE:</b>\n\n"
        for b in new_buys:
            sl_price = round(float(b['Buy Price']) * (1 - SL_PCT), 2)
            gtt_msg += f"• <b>{b['Stock']}</b>: Qty {b['Qty']} | SL trigger ₹{sl_price}\n"
        gtt_msg += f"\n<i>GTT type: Single | Trigger: price ≤ SL | Order: Market Sell</i>"
        send_telegram(gtt_msg)

    print(f"Rebalance complete. Sold {len(to_sell)}, Bought {len(to_buy)}, Kept {len(to_keep)}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'sl_check':
        check_stop_losses()
    else:
        check_stop_losses()  # Always check SL first
        run()  # Then rebalance if last trading day
