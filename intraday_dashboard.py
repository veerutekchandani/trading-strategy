"""
INTRADAY ORB — LIVE PAPER TRADING DASHBOARD
=============================================
Shows today's ORB levels, live price, signal status, and trade history.
Run: streamlit run intraday_dashboard.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import json, os
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="ORB Intraday", page_icon="⚡", layout="wide")

LOT_SIZE = 65
CAPITAL = 175000
MIN_RANGE = 50
MAX_RANGE = 200
TARGET_MULT = 1.5
TRADE_FILE = 'orb_trades.json'


def load_trades():
    if os.path.exists(TRADE_FILE):
        with open(TRADE_FILE) as f:
            return json.load(f)
    return []


def save_trades(trades):
    with open(TRADE_FILE, 'w') as f:
        json.dump(trades, f, indent=2)


@st.cache_data(ttl=60)
def get_today_data():
    df = yf.download('^NSEI', period='5d', interval='5m', progress=False)
    df.columns = df.columns.get_level_values(0)
    df = df.dropna()
    today = df.index[-1].date()
    today_data = df[df.index.date == today]
    return today_data, df


def get_orb_levels(today_data):
    if len(today_data) < 6:
        return None, None, None
    first_30 = today_data.iloc[:6]
    orb_high = float(first_30['High'].max())
    orb_low = float(first_30['Low'].min())
    orb_range = orb_high - orb_low
    return orb_high, orb_low, orb_range


# --- MAIN APP ---
st.title("⚡ Intraday ORB — Live Paper Trading")
st.caption("Nifty Futures | Opening Range Breakout | Lot Size: 65")

today_data, all_data = get_today_data()
orb_high, orb_low, orb_range = get_orb_levels(today_data)

tab1, tab2, tab3 = st.tabs(["📊 Live Signal", "📜 Trade History", "📈 Performance"])

with tab1:
    if orb_high is None:
        st.warning("⏳ Market hasn't completed 30 minutes yet. Wait until 9:45 AM IST.")
    else:
        current_price = float(today_data['Close'].iloc[-1])
        last_update = today_data.index[-1].strftime('%H:%M')

        # Status
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Nifty Now", f"{current_price:,.1f}", f"Updated {last_update}")
        col2.metric("OR High", f"{orb_high:,.1f}")
        col3.metric("OR Low", f"{orb_low:,.1f}")
        col4.metric("Range", f"{orb_range:,.0f} pts")

        # Signal
        st.divider()

        if orb_range < MIN_RANGE:
            st.error(f"❌ NO TRADE TODAY — Range too tight ({orb_range:.0f} pts < {MIN_RANGE})")
        elif orb_range > MAX_RANGE:
            st.error(f"❌ NO TRADE TODAY — Range too wide ({orb_range:.0f} pts > {MAX_RANGE})")
        else:
            target_long = orb_high + orb_range * TARGET_MULT
            target_short = orb_low - orb_range * TARGET_MULT
            risk = orb_range * LOT_SIZE
            reward = orb_range * TARGET_MULT * LOT_SIZE

            if current_price > orb_high:
                st.success(f"""
                ### 🟢 BREAKOUT UP — BUY SIGNAL ACTIVE
                **Entry:** {orb_high:.1f} (already broken)  
                **Current:** {current_price:.1f} (+{current_price - orb_high:.0f} pts from entry)  
                **Stop Loss:** {orb_low:.1f}  
                **Target:** {target_long:.1f}  
                **Risk:** ₹{risk:,.0f} | **Reward:** ₹{reward:,.0f}
                """)
            elif current_price < orb_low:
                st.error(f"""
                ### 🔴 BREAKOUT DOWN — SHORT SIGNAL ACTIVE
                **Entry:** {orb_low:.1f} (already broken)  
                **Current:** {current_price:.1f} ({orb_low - current_price:.0f} pts in profit)  
                **Stop Loss:** {orb_high:.1f}  
                **Target:** {target_short:.1f}  
                **Risk:** ₹{risk:,.0f} | **Reward:** ₹{reward:,.0f}
                """)
            else:
                st.info(f"""
                ### ⏳ WAITING FOR BREAKOUT
                **BUY** if price breaks above **{orb_high:.1f}** → Target: {target_long:.1f}  
                **SHORT** if price breaks below **{orb_low:.1f}** → Target: {target_short:.1f}  
                **Risk per trade:** ₹{risk:,.0f} | **Reward:** ₹{reward:,.0f}
                """)

            # Chart
            st.subheader("Today's Price Action")
            fig = go.Figure()
            fig.add_trace(go.Candlestick(x=today_data.index, open=today_data['Open'],
                                          high=today_data['High'], low=today_data['Low'],
                                          close=today_data['Close'], name='Nifty'))
            fig.add_hline(y=orb_high, line_dash="dash", line_color="green",
                         annotation_text=f"OR High: {orb_high:.0f}")
            fig.add_hline(y=orb_low, line_dash="dash", line_color="red",
                         annotation_text=f"OR Low: {orb_low:.0f}")
            fig.add_hline(y=target_long, line_dash="dot", line_color="green",
                         annotation_text=f"Target: {target_long:.0f}")
            fig.add_hline(y=target_short, line_dash="dot", line_color="red",
                         annotation_text=f"Target: {target_short:.0f}")
            fig.update_layout(height=400, xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        # Manual trade logging
        st.divider()
        st.subheader("📝 Log Today's Trade")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            direction = st.selectbox("Direction", ["LONG", "SHORT", "NO TRADE"])
        with col2:
            entry_price = st.number_input("Entry Price", value=int(orb_high) if orb_high else 0)
        with col3:
            exit_price = st.number_input("Exit Price", value=0)
        with col4:
            result = st.selectbox("Result", ["TARGET", "SL HIT", "EOD EXIT"])

        if st.button("💾 Save Trade"):
            if direction != "NO TRADE" and exit_price > 0:
                if direction == "LONG":
                    pnl = (exit_price - entry_price) * LOT_SIZE
                else:
                    pnl = (entry_price - exit_price) * LOT_SIZE
                pnl -= 400  # charges

                trades = load_trades()
                trades.append({
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'direction': direction,
                    'entry': entry_price,
                    'exit': exit_price,
                    'pnl': round(pnl),
                    'result': result,
                    'range': round(orb_range) if orb_range else 0
                })
                save_trades(trades)
                st.success(f"✅ Trade saved! P&L: ₹{pnl:+,.0f}")
            else:
                trades = load_trades()
                trades.append({
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'direction': 'NO TRADE',
                    'entry': 0, 'exit': 0, 'pnl': 0, 'result': 'SKIPPED', 'range': 0
                })
                save_trades(trades)
                st.info("📝 No trade logged for today.")

with tab2:
    st.header("📜 Trade History")
    trades = load_trades()

    if not trades:
        st.info("No trades yet. Log your first trade in the Live Signal tab.")
    else:
        tdf = pd.DataFrame(trades)
        tdf_display = tdf[tdf['direction'] != 'NO TRADE'].copy()

        if not tdf_display.empty:
            st.dataframe(tdf_display.sort_index(ascending=False), use_container_width=True, hide_index=True)

            st.subheader("Summary")
            total = len(tdf_display)
            winners = tdf_display[tdf_display['pnl'] > 0]
            losers = tdf_display[tdf_display['pnl'] <= 0]
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Trades", total)
            col2.metric("Win Rate", f"{len(winners)/total*100:.0f}%")
            col3.metric("Total P&L", f"₹{tdf_display['pnl'].sum():+,.0f}")
            col4.metric("Avg P&L/Trade", f"₹{tdf_display['pnl'].mean():+,.0f}")

with tab3:
    st.header("📈 Performance")
    trades = load_trades()

    if not trades:
        st.info("No trades yet.")
    else:
        tdf = pd.DataFrame(trades)
        tdf_active = tdf[tdf['direction'] != 'NO TRADE'].copy()

        if not tdf_active.empty:
            # Equity curve
            tdf_active['cumulative'] = CAPITAL + tdf_active['pnl'].cumsum()

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=tdf_active['date'], y=tdf_active['cumulative'],
                                     mode='lines+markers', name='Portfolio',
                                     line=dict(color='#00d4aa', width=3),
                                     fill='tozeroy', fillcolor='rgba(0,212,170,0.1)'))
            fig.add_hline(y=CAPITAL, line_dash="dash", line_color="gray",
                         annotation_text=f"Starting Capital ₹{CAPITAL:,.0f}")
            fig.update_layout(title="Equity Curve", yaxis_title="Portfolio Value (₹)")
            st.plotly_chart(fig, use_container_width=True)

            # Daily P&L bar chart
            colors = ['green' if p > 0 else 'red' for p in tdf_active['pnl']]
            fig2 = go.Figure(go.Bar(x=tdf_active['date'], y=tdf_active['pnl'], marker_color=colors))
            fig2.update_layout(title="Daily P&L", yaxis_title="P&L (₹)")
            st.plotly_chart(fig2, use_container_width=True)

            # Stats
            col1, col2, col3 = st.columns(3)
            col1.metric("Portfolio Value", f"₹{float(tdf_active['cumulative'].iloc[-1]):,.0f}")
            col2.metric("Max Drawdown", f"₹{(tdf_active['cumulative'].cummax() - tdf_active['cumulative']).max():,.0f}")
            col3.metric("Best Trade", f"₹{tdf_active['pnl'].max():+,.0f}")
