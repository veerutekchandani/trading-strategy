"""
INTRADAY ORB STRATEGY — NIFTY 50
==================================
Opening Range Breakout on Nifty Futures (5-min candles)

Rules:
- 9:15-9:45 AM: Calculate Opening Range (30-min high/low)
- BUY if price breaks above OR high
- SHORT if price breaks below OR low
- Stop Loss: Opposite end of range
- Target: 1.5x range
- Max 1 trade per day
- Exit by 3:15 PM if neither SL nor target hit
- Skip if range < 30 pts or > 200 pts (too tight or too wide)

Run: python intraday_orb.py          → Show today's levels
     python intraday_orb.py backtest → Run 60-day backtest
     python intraday_orb.py live     → Live paper trading mode
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import json
import os
import sys
import warnings
warnings.filterwarnings('ignore')

SYMBOL = '^NSEI'  # Nifty 50 index (proxy for futures)
LOT_SIZE = 65     # Nifty futures lot size
CAPITAL = 175000
ORB_MINUTES = 30  # First 30 minutes
MIN_RANGE = 50    # Skip if range < 50 pts
MAX_RANGE = 200   # Skip if range > 200 pts
TARGET_MULT = 1.5 # Target = 1.5x range
TRADE_LOG = 'intraday_trades.json'


def load_trades():
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG) as f:
            return json.load(f)
    return []


def save_trades(trades):
    with open(TRADE_LOG, 'w') as f:
        json.dump(trades, f, indent=2)


def get_today_data():
    """Get today's 5-min data."""
    df = yf.download(SYMBOL, period='5d', interval='5m', progress=False)
    df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    # Filter today only
    today = df.index[-1].date()
    today_data = df[df.index.date == today]
    return today_data, df


def calculate_orb(day_data):
    """Calculate Opening Range from first 30 min."""
    first_30 = day_data.iloc[:6]  # 6 candles of 5-min = 30 min
    orb_high = float(first_30['High'].max())
    orb_low = float(first_30['Low'].min())
    orb_range = orb_high - orb_low
    return orb_high, orb_low, orb_range


def check_breakout(day_data, orb_high, orb_low):
    """Check if breakout happened after ORB period."""
    after_orb = day_data.iloc[6:]  # After 9:45 AM
    for idx, row in after_orb.iterrows():
        if row['Close'] > orb_high:
            return 'LONG', float(row['Close']), idx
        elif row['Close'] < orb_low:
            return 'SHORT', float(row['Close']), idx
    return None, None, None


def simulate_trade(day_data, direction, entry_price, entry_time, orb_high, orb_low, orb_range):
    """Simulate a single trade with SL, target, and EOD exit."""
    if direction == 'LONG':
        stop_loss = orb_low
        target = entry_price + orb_range * TARGET_MULT
    else:
        stop_loss = orb_high
        target = entry_price - orb_range * TARGET_MULT

    after_entry = day_data[day_data.index > entry_time]
    # Remove last 3 candles (exit by 3:15 PM)
    if len(after_entry) > 3:
        after_entry = after_entry.iloc[:-3]

    for idx, row in after_entry.iterrows():
        if direction == 'LONG':
            if row['Low'] <= stop_loss:
                return stop_loss, 'SL HIT', (stop_loss - entry_price) * LOT_SIZE
            if row['High'] >= target:
                return target, 'TARGET', (target - entry_price) * LOT_SIZE
        else:
            if row['High'] >= stop_loss:
                return stop_loss, 'SL HIT', (entry_price - stop_loss) * LOT_SIZE
            if row['Low'] <= target:
                return target, 'TARGET', (entry_price - target) * LOT_SIZE

    # EOD exit
    exit_price = float(day_data.iloc[-4]['Close'])  # Exit at 3:15 PM
    if direction == 'LONG':
        pnl = (exit_price - entry_price) * LOT_SIZE
    else:
        pnl = (entry_price - exit_price) * LOT_SIZE
    return exit_price, 'EOD EXIT', pnl


def show_today():
    """Show today's ORB levels and signal."""
    today_data, _ = get_today_data()

    if len(today_data) < 6:
        print("\n  ⏳ Market hasn't completed 30 minutes yet. Wait until 9:45 AM IST.")
        return

    orb_high, orb_low, orb_range = calculate_orb(today_data)

    print(f"""
{'='*50}
  📊 TODAY'S ORB LEVELS — {datetime.now().strftime('%d %b %Y')}
{'='*50}

  Opening Range (9:15-9:45 AM):
  ┌─────────────────────────────────┐
  │  OR HIGH:  {orb_high:>10,.1f}              │
  │  OR LOW:   {orb_low:>10,.1f}              │
  │  RANGE:    {orb_range:>10,.1f} pts          │
  └─────────────────────────────────┘
""")

    if orb_range < MIN_RANGE:
        print(f"  ⚠️  Range too tight ({orb_range:.0f} < {MIN_RANGE}). NO TRADE TODAY.")
        return
    if orb_range > MAX_RANGE:
        print(f"  ⚠️  Range too wide ({orb_range:.0f} > {MAX_RANGE}). NO TRADE TODAY.")
        return

    target_long = orb_high + orb_range * TARGET_MULT
    target_short = orb_low - orb_range * TARGET_MULT

    print(f"""  📈 LONG Setup (if price breaks {orb_high:.1f}):
     Entry:   {orb_high:.1f}
     SL:      {orb_low:.1f} (risk: {orb_range:.0f} pts = ₹{orb_range * LOT_SIZE:,.0f})
     Target:  {target_long:.1f} (reward: {orb_range * TARGET_MULT:.0f} pts = ₹{orb_range * TARGET_MULT * LOT_SIZE:,.0f})

  📉 SHORT Setup (if price breaks {orb_low:.1f}):
     Entry:   {orb_low:.1f}
     SL:      {orb_high:.1f} (risk: {orb_range:.0f} pts = ₹{orb_range * LOT_SIZE:,.0f})
     Target:  {target_short:.1f} (reward: {orb_range * TARGET_MULT:.0f} pts = ₹{orb_range * TARGET_MULT * LOT_SIZE:,.0f})

  💰 Position: {LOT_SIZE} units (1 lot Nifty Futures)
  ⏰ Exit by: 3:15 PM IST
""")

    # Check if breakout already happened
    direction, entry, entry_time = check_breakout(today_data, orb_high, orb_low)
    if direction:
        print(f"  🚨 BREAKOUT ALREADY HAPPENED: {direction} at {entry:.1f}")
        exit_price, result, pnl = simulate_trade(today_data, direction, entry, entry_time, orb_high, orb_low, orb_range)
        if result:
            emoji = '🟢' if pnl > 0 else '🔴'
            print(f"  {emoji} Result: {result} | Exit: {exit_price:.1f} | P&L: ₹{pnl:+,.0f}")


def backtest():
    """Run backtest on last 60 days."""
    print("\n  Running 60-day backtest...")
    df = yf.download(SYMBOL, period='60d', interval='5m', progress=False)
    df.columns = df.columns.get_level_values(0)
    df = df.dropna()

    df['date'] = df.index.date
    dates = sorted(df['date'].unique())

    trades = []
    portfolio = CAPITAL

    for date in dates:
        day_data = df[df['date'] == date]
        if len(day_data) < 20:
            continue

        orb_high, orb_low, orb_range = calculate_orb(day_data)

        if orb_range < MIN_RANGE or orb_range > MAX_RANGE:
            continue

        direction, entry, entry_time = check_breakout(day_data, orb_high, orb_low)
        if not direction:
            continue

        exit_price, result, pnl = simulate_trade(day_data, direction, entry, entry_time, orb_high, orb_low, orb_range)
        portfolio += pnl
        trades.append({
            'date': str(date), 'direction': direction, 'entry': entry,
            'exit': exit_price, 'pnl': round(pnl), 'result': result, 'range': round(orb_range)
        })

    # Results
    trades_df = pd.DataFrame(trades)
    total = len(trades_df)
    winners = trades_df[trades_df['pnl'] > 0]
    losers = trades_df[trades_df['pnl'] <= 0]

    print(f"""
{'='*55}
  ORB INTRADAY — 60 DAY BACKTEST RESULTS
{'='*55}

  Capital:     ₹{CAPITAL:,.0f} → ₹{portfolio:,.0f}
  Net P&L:     ₹{portfolio - CAPITAL:+,.0f} ({(portfolio/CAPITAL-1)*100:+.1f}%)
  Trades:      {total} ({total/len(dates):.1f}/day avg)
  Win Rate:    {len(winners)}/{total} ({len(winners)/total*100:.0f}%)
  Avg Win:     ₹{winners['pnl'].mean():+,.0f}
  Avg Loss:    ₹{losers['pnl'].mean():+,.0f}
  Max Win:     ₹{trades_df['pnl'].max():+,.0f}
  Max Loss:    ₹{trades_df['pnl'].min():+,.0f}

  Last 10 trades:
  {'Date':<12} {'Dir':<6} {'Entry':>7} {'Exit':>7} {'P&L':>9} {'Result':<8}
  {'-'*52}""")

    for _, t in trades_df.tail(10).iterrows():
        emoji = '🟢' if t['pnl'] > 0 else '🔴'
        print(f"  {t['date']:<12} {t['direction']:<6} {t['entry']:>7.0f} {t['exit']:>7.0f} {emoji}₹{t['pnl']:>+7,} {t['result']:<8}")


def live_mode():
    """Live paper trading — run this during market hours."""
    print(f"""
{'='*50}
  🔴 LIVE PAPER TRADING MODE
  Run this between 9:15 AM - 3:30 PM IST
{'='*50}
""")
    import time as tm

    today_data, _ = get_today_data()
    if len(today_data) < 6:
        print("  ⏳ Waiting for opening range to form (9:45 AM)...")
        return

    orb_high, orb_low, orb_range = calculate_orb(today_data)
    print(f"  OR High: {orb_high:.1f} | OR Low: {orb_low:.1f} | Range: {orb_range:.0f}")

    if orb_range < MIN_RANGE or orb_range > MAX_RANGE:
        print(f"  ❌ No trade today (range {orb_range:.0f} outside {MIN_RANGE}-{MAX_RANGE})")
        return

    # Check for breakout
    direction, entry, entry_time = check_breakout(today_data, orb_high, orb_low)

    if direction:
        exit_price, result, pnl = simulate_trade(today_data, direction, entry, entry_time, orb_high, orb_low, orb_range)
        emoji = '🟢' if pnl > 0 else '🔴'
        print(f"\n  {emoji} TRADE: {direction} @ {entry:.1f} → {exit_price:.1f} | {result} | P&L: ₹{pnl:+,.0f}")

        # Save trade
        trades = load_trades()
        trades.append({
            'date': str(datetime.now().date()),
            'direction': direction,
            'entry': entry,
            'exit': exit_price,
            'pnl': round(pnl),
            'result': result
        })
        save_trades(trades)
        print(f"  ✅ Trade logged. Total trades: {len(trades)}")
    else:
        print(f"\n  ⏳ No breakout yet. Waiting for price to break {orb_high:.1f} or {orb_low:.1f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'today'

    if cmd == 'backtest':
        backtest()
    elif cmd == 'live':
        live_mode()
    else:
        show_today()
