import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import yfinance as yf
from datetime import datetime
import os, json
from strategy import get_top_picks, get_live_price, is_skip_month, SKIP_MONTHS
import sheets

st.set_page_config(page_title="Momentum Strategy", page_icon="📈", layout="wide")

# Initialize sheets on first run
try:
    sheets.init_sheets()
except Exception as e:
    st.error(f"Google Sheets connection failed: {e}")
    st.info("Make sure you've added your service account JSON to Streamlit secrets.")
    st.stop()


def show_header():
    st.title("📈 Momentum Strategy Dashboard")
    st.caption("Nifty 100 | Top 3 | 3-Month Lookback | 3/3 Consistency | 52w High | 20% SL")
    if is_skip_month():
        st.warning(f"⚠️ **SKIP MONTH** ({datetime.now().strftime('%B')}). Stay in cash. Come back in April.")


def show_portfolio():
    st.header("💼 Portfolio")

    cash = sheets.get_cash()
    holdings = sheets.get_holdings()

    if holdings.empty or len(holdings) == 0:
        col1, col2 = st.columns(2)
        col1.metric("Portfolio Value", f"₹{cash:,.0f}")
        col2.metric("Status", "All Cash 💵")
        return

    # Update live prices
    total_invested = 0
    total_current = 0
    rows = []

    for _, row in holdings.iterrows():
        ticker = row['Stock'] + '.NS'
        qty = int(row['Qty'])
        buy_price = float(row['Buy Price'])
        current_price = get_live_price(ticker) or buy_price
        invested = qty * buy_price
        current = qty * current_price
        pnl_pct = ((current_price / buy_price) - 1) * 100
        total_invested += invested
        total_current += current
        rows.append({
            'Stock': row['Stock'],
            'Qty': qty,
            'Buy Price': f"₹{buy_price:,.0f}",
            'Current': f"₹{current_price:,.0f}",
            'Invested': f"₹{invested:,.0f}",
            'Value': f"₹{current:,.0f}",
            'P&L': f"₹{current - invested:+,.0f}",
            'Return': f"{pnl_pct:+.1f}%",
        })

    total_portfolio = cash + total_current
    total_pnl = total_current - total_invested
    starting_cap = sheets.get_starting_capital()
    overall_return = (total_portfolio / starting_cap - 1) * 100

    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Portfolio Value", f"₹{total_portfolio:,.0f}", f"{overall_return:+.1f}%")
    col2.metric("Invested", f"₹{total_invested:,.0f}")
    col3.metric("P&L", f"₹{total_pnl:+,.0f}", f"{total_pnl/max(total_invested,1)*100:+.1f}%")
    col4.metric("Cash", f"₹{cash:,.0f}")

    # Holdings table
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def show_monthly_chart():
    st.header("📊 Monthly Performance")
    monthly = sheets.get_monthly()

    if monthly.empty:
        st.info("No monthly data yet. Rebalance to start tracking.")
        return

    monthly['Portfolio Value'] = pd.to_numeric(monthly['Portfolio Value'], errors='coerce')
    monthly['Return %'] = pd.to_numeric(monthly['Return %'], errors='coerce')

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=monthly['Month'], y=monthly['Portfolio Value'],
        mode='lines+markers', name='Portfolio Value',
        line=dict(color='#00d4aa', width=3),
        fill='tozeroy', fillcolor='rgba(0,212,170,0.1)'
    ))
    starting_cap_val = sheets.get_starting_capital()
    fig.add_hline(y=starting_cap_val, line_dash="dash", line_color="gray", annotation_text=f"Starting Capital ₹{starting_cap_val/100000:.0f}L")
    fig.update_layout(title="Portfolio Growth", yaxis_title="Value (₹)", xaxis_title="Month")
    st.plotly_chart(fig, use_container_width=True)

    # Monthly returns bar chart
    if 'Return %' in monthly.columns:
        colors = ['green' if x >= 0 else 'red' for x in monthly['Return %']]
        fig2 = go.Figure(go.Bar(x=monthly['Month'], y=monthly['Return %'], marker_color=colors))
        fig2.update_layout(title="Monthly Returns (%)", yaxis_title="Return %")
        st.plotly_chart(fig2, use_container_width=True)


def show_trades():
    st.header("📜 Trade History")
    trades = sheets.get_trades()

    if trades.empty:
        st.info("No trades yet.")
        return

    # Color code buys and sells
    st.dataframe(trades.sort_index(ascending=False), use_container_width=True, hide_index=True)


def show_momentum_ranking():
    st.header("🏆 Current Momentum Ranking")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        lookback = st.selectbox("Lookback Period", [1, 2, 3, 4, 5, 6, 8, 10, 12], index=2, format_func=lambda x: f"{x} month{'s' if x > 1 else ''}")
    with col_b:
        top_n = st.number_input("Top N Stocks", min_value=1, max_value=15, value=3)
    with col_c:
        st.write("")
        st.write("")
        refresh = st.button("🔄 Refresh Rankings")

    if refresh:
        st.cache_data.clear()

    with st.spinner(f"Calculating {lookback}-month momentum for 90+ stocks..."):
        picks = get_top_picks(top_n * 3, lookback)

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader(f"Top {top_n} (Buy These)")
        for i, row in picks.head(top_n).iterrows():
            st.success(f"**{i+1}. {row['Stock']}** — +{row['Momentum']:.1f}% | ₹{row['Price']:,.0f}")

    with col2:
        fig = px.bar(picks.head(top_n * 2), x='Stock', y='Momentum', color='Momentum',
                     color_continuous_scale='RdYlGn', title=f'Top {top_n * 2} Momentum Stocks ({lookback}m lookback)')
        st.plotly_chart(fig, use_container_width=True)


def do_rebalance():
    st.header("🔄 Rebalance")

    if is_skip_month():
        st.error(f"Cannot rebalance in {datetime.now().strftime('%B')}. Strategy skips Jan-Mar.")
        if st.button("🚨 Sell Everything (Go to Cash)"):
            holdings = sheets.get_holdings()
            cash = sheets.get_cash()
            for _, row in holdings.iterrows():
                price = get_live_price(row['Stock'] + '.NS') or float(row['Buy Price'])
                proceeds = int(row['Qty']) * price
                cash += proceeds
                sheets.add_trade(datetime.now().strftime('%Y-%m-%d'), 'SELL', row['Stock'],
                               int(row['Qty']), round(price, 2), round(proceeds, 2), 'Q1 exit')
            sheets.set_cash(cash)
            sheets.set_holdings(pd.DataFrame())
            st.success(f"✅ All sold. Cash: ₹{cash:,.0f}")
        return

    st.info("This will sell stocks that dropped out of top 3 and buy new entries. Stocks still in top 3 are kept. 20% SL monitored daily.")

    if st.button("⚡ Execute Rebalance", type="primary"):
        with st.spinner("Calculating picks and executing trades..."):
            picks = get_top_picks(5)
            holdings = sheets.get_holdings()
            cash = sheets.get_cash()
            today = datetime.now().strftime('%Y-%m-%d')

            new_top5 = picks['Stock'].tolist()
            current_stocks = holdings['Stock'].tolist() if not holdings.empty else []

            # Determine what to sell and buy
            to_sell = [s for s in current_stocks if s not in new_top5]
            to_buy = [s for s in new_top5 if s not in current_stocks]
            to_keep = [s for s in current_stocks if s in new_top5]

            st.write(f"**Keep:** {', '.join(to_keep) if to_keep else 'None'}")
            st.write(f"**Sell:** {', '.join(to_sell) if to_sell else 'None'}")
            st.write(f"**Buy:** {', '.join(to_buy) if to_buy else 'None'}")

            # Zerodha Delivery Charges per trade (buy or sell):
            # STT: 0.1% on both buy & sell
            # Stamp: 0.015% on buy
            # Transaction: 0.00307% both sides
            # GST: 18% on transaction
            # SEBI: ₹10/crore
            # Total ≈ 0.11% on buy, 0.11% on sell
            DELIVERY_CHARGE_PCT = 0.0011  # 0.11% per side

            # Sell stocks that dropped out
            kept_holdings = []
            if not holdings.empty:
                for _, row in holdings.iterrows():
                    if row['Stock'] in to_sell:
                        price = get_live_price(row['Stock'] + '.NS') or float(row['Buy Price'])
                        qty = int(row['Qty'])
                        proceeds = qty * price
                        sell_charges = round(proceeds * DELIVERY_CHARGE_PCT, 2)
                        proceeds -= sell_charges
                        pnl = proceeds - (qty * float(row['Buy Price']))
                        cash += proceeds
                        sheets.add_trade(today, 'SELL', row['Stock'], qty, round(price, 2),
                                       round(proceeds, 2), round(pnl, 2))
                    else:
                        kept_holdings.append(row.to_dict())

            # Buy new entries (split cash equally among new buys only)
            if to_buy:
                amount_per_stock = cash / len(to_buy)
                for _, row in picks.iterrows():
                    if row['Stock'] in to_buy:
                        qty = int(amount_per_stock / row['Price'])
                        if qty > 0:
                            cost = qty * row['Price']
                            buy_charges = round(cost * DELIVERY_CHARGE_PCT, 2)
                            cost += buy_charges
                            cash -= cost
                            kept_holdings.append({
                                'Stock': row['Stock'], 'Qty': qty,
                                'Buy Price': round(row['Price'], 2),
                                'Buy Date': today, 'Current Price': round(row['Price'], 2), 'P&L %': 0
                            })
                            sheets.add_trade(today, 'BUY', row['Stock'], qty,
                                           round(row['Price'], 2), round(cost, 2), f'-{buy_charges}')

            sheets.set_holdings(pd.DataFrame(kept_holdings))
            sheets.set_cash(cash)

            # Record monthly
            total_value = cash + sum(h['Qty'] * float(h['Buy Price']) for h in kept_holdings)
            ret_pct = (total_value / sheets.get_starting_capital() - 1) * 100
            stocks_str = ', '.join(h['Stock'] for h in kept_holdings)
            sheets.add_monthly_record(datetime.now().strftime('%b %Y'), round(total_value, 0),
                                     round(ret_pct, 1), stocks_str)

            if not to_sell and not to_buy:
                st.success("✅ No changes needed — same stocks remain in top 3!")
            else:
                st.success(f"✅ Rebalance complete! Sold {len(to_sell)}, Bought {len(to_buy)}, Kept {len(to_keep)}")
            st.balloons()


# --- INTRADAY ORB FUNCTIONS ---
def show_intraday():
    import plotly.graph_objects as go

    STOCKS = ['RELIANCE','HDFCBANK','ICICIBANK','SBIN','INFY','BAJFINANCE','BHARTIARTL','AXISBANK','ITC','TCS']
    ORB_CAPITAL = 175000
    ORB_LEVERAGE = 5
    ORB_POSITION = ORB_CAPITAL * ORB_LEVERAGE
    ORB_SL_MULT = 2.0
    ORB_TARGET_MULT = 3.0
    ORB_CHARGES = 358

    st.title("⚡ Stock ORB — Intraday")
    st.caption("Top 10 Nifty Stocks | 15-min OR | SL 2× | TGT 3× | Range 0.5-3% | Capital ₹1.75L")

    # Show live trade status from Google Sheets
    try:
        import sheets as sh
        intraday_ws = sh.get_sheet().worksheet("Intraday")
        all_rows = intraday_ws.get_all_records()
        if all_rows:
            last_row = all_rows[-1]
            status = last_row.get('Status', '')
            stock_name = last_row.get('Stock', 'N/A')
            if status == 'IN TRADE':
                st.error(f"""
                ### 🔴 LIVE TRADE — {stock_name}
                **Date:** {last_row['Date']} | **Direction:** {last_row['Signal']} | **Entry:** {last_row['Entry']}  
                **SL:** {last_row['SL']} | **Target:** {last_row['Target']}
                """)
            elif status == 'WATCHING':
                st.warning(f"""
                ### ⏳ WATCHING — {stock_name}
                **Date:** {last_row['Date']} | **OR High:** {last_row['OR High']} | **OR Low:** {last_row['OR Low']} | **Range%:** {last_row.get('Range%', '')}
                """)
            elif status == 'CLOSED' and last_row.get('Signal'):
                pnl = last_row.get('Net P&L', 0)
                try:
                    pnl_val = float(pnl)
                except:
                    pnl_val = 0
                emoji = '🟢' if pnl_val > 0 else '🔴' if pnl_val < 0 else '⚪'
                st.info(f"""
                ### {emoji} Last Trade: {stock_name} — {last_row['Result']}
                **Date:** {last_row['Date']} | **{last_row['Signal']}** | Entry: {last_row['Entry']} → Exit: {last_row['Exit']}  
                **Net P&L:** ₹{pnl_val:+,.0f}
                """)
    except:
        pass

    # Trade history from sheet
    st.divider()
    st.subheader("📅 Trade History")
    try:
        import sheets as sh
        intraday_ws = sh.get_sheet().worksheet("Intraday")
        all_rows = intraday_ws.get_all_records()
        if all_rows:
            tdf = pd.DataFrame(all_rows)
            traded = tdf[tdf.get('Signal', tdf.get('signal', pd.Series())).isin(['LONG', 'SHORT'])] if 'Signal' in tdf.columns else tdf[tdf['Status'] == 'CLOSED']
            if not traded.empty:
                traded['pnl'] = pd.to_numeric(traded['Net P&L'], errors='coerce').fillna(0)
                wins = (traded['pnl'] > 0).sum()
                total_pnl = traded['pnl'].sum()

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("💰 Total P&L", f"₹{total_pnl:+,.0f}")
                col2.metric("📊 Trades", len(traded))
                col3.metric("🟢 Win Rate", f"{100*wins/len(traded):.0f}%")
                col4.metric("📈 Avg P&L", f"₹{total_pnl/len(traded):+,.0f}")

                # Equity curve
                traded_sorted = traded.sort_values('Date')
                traded_sorted['cumulative'] = ORB_CAPITAL + traded_sorted['pnl'].cumsum()
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=traded_sorted['Date'], y=traded_sorted['cumulative'],
                    mode='lines+markers', line=dict(color='#2196F3', width=2),
                    fill='tozeroy', fillcolor='rgba(33,150,243,0.1)'))
                fig.add_hline(y=ORB_CAPITAL, line_dash="dash", line_color="gray", annotation_text="Capital ₹1.75L")
                fig.update_layout(height=300, title="Equity Curve", yaxis_title="₹")
                st.plotly_chart(fig, use_container_width=True)

                # Show available columns
                display_cols = [c for c in ['Date','Stock','Signal','Entry','SL','Target','Exit','Net P&L','Result'] if c in traded.columns]
                st.dataframe(traded[display_cols].sort_values('Date', ascending=False),
                           use_container_width=True, hide_index=True)
            else:
                st.info("No completed trades yet.")
        else:
            st.info("No trade data yet. ORB cron will populate this.")
    except Exception as e:
        st.warning(f"Could not load data: {e}")


st.sidebar.title("📱 Strategy")
page = st.sidebar.radio("Select", ["🏠 Overview", "📈 Monthly Momentum", "🔥 Swing Futures", "🎯 Multi-Stock ORB"])

if page == "🏠 Overview":
    st.title("🏠 Strategy Portfolio — Overview")
    st.caption("3 uncorrelated strategies | Total capital: ₹12.2L")
    st.markdown("""
---
## 1. 📈 Monthly Momentum (Delivery) — +29% CAGR
| Parameter | Value |
|-----------|-------|
| **Instrument** | Delivery (CNC), no leverage |
| **Capital** | ₹5,00,000 |
| **Universe** | Nifty 100 stocks |

**Entry:** Last trading day of month. Top 3 by 3-month momentum. Filters: 3/3 consistency + within 10% of 52w high.

**Exit:** Hold till next month-end. 20% SL (GTT order).

---
## 2. 🎯 Multi-Stock ORB (Intraday) — +44% CAGR
| Parameter | Value |
|-----------|-------|
| **Instrument** | Intraday (MIS), 5x leverage |
| **Capital** | ₹1,20,000 |
| **Universe** | 87 F&O stocks (9 sector indices) |

**Entry:** Scan all 87 stocks at 9:30. Filter OR range 0.7-1.5%. OR close filter (LONG if >70%, SHORT if <30%). Pick top 3. SL-M order at OR level.

**Exit:** SL: 0.75× OR range | Target: 3× OR range | EOD: 3:15 PM

---
## 3. 🔥 EMA Stack Swing (Delivery) — +94% CAGR
| Parameter | Value |
|-----------|-------|
| **Instrument** | Delivery (CNC), no leverage |
| **Capital** | ₹6,00,000 (3 slots × ₹2L) |
| **Universe** | 87 F&O stocks |

**Entry:** EMA 5>10>20>50 + Vol>1.5x + 5d return>3%. Buy at 3:25 PM close.

**Exit:** Sell at close after 5 trading days. No SL. Max 3 positions.
    """)
elif page == "📈 Monthly Momentum":
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Portfolio", "📈 Chart", "🔍 Ranking", "🔄 Rebalance"])
    with tab1:
        show_portfolio()
    with tab2:
        show_monthly_chart()
    with tab3:
        show_momentum_ranking()
    with tab4:
        do_rebalance()
elif page == "⚡ Intraday ORB":
    show_intraday()
elif page == "🔥 Swing Futures":
    # Swing page
    st.title("🔥 EMA Stack Swing — Delivery")
    st.caption("87 F&O Stocks | EMA 5>10>20>50 | Vol>1.5x | 5d ret>3% | Hold 5 days | No SL | 94% CAGR")

    # Live trade status from Google Sheet
    try:
        import sheets as sh
        swing_ws = sh.get_sheet().worksheet("Swing")
        swing_records = swing_ws.get_all_records()
        if swing_records:
            open_trades = [r for r in swing_records if r.get('Status') == 'OPEN']
            if open_trades:
                st.error(f"### 🔴 {len(open_trades)} OPEN POSITION(S)")
                for t in open_trades:
                    live_p = get_live_price(t['Stock'] + '.NS')
                    pnl_pct = ((live_p - float(t['Entry'])) / float(t['Entry']) * 100) if live_p else 0
                    st.write(f"**{t['Stock']}** | Entry: ₹{t['Entry']} | SL: ₹{t['SL']} | TGT: ₹{t['Target']} | Day {t.get('Day','')} | Live: ₹{live_p or '?'} ({pnl_pct:+.1f}%)")
            else:
                last = swing_records[-1]
                pnl = float(last.get('P&L', 0)) if last.get('P&L') else 0
                emoji = '🟢' if pnl > 0 else '🔴'
                st.info(f"### {emoji} Last Trade: {last['Stock']} | ₹{pnl:+,.0f} | {last.get('Exit Reason','')}")
    except:
        pass

    # Nifty regime check
    st.divider()
    st.subheader("📊 Market Regime")
    try:
        nifty = yf.download('^NSEI', period='3mo', progress=False)
        nifty.columns = nifty.columns.get_level_values(0)
        nifty['EMA50'] = nifty['Close'].ewm(span=50).mean()
        nifty_above = float(nifty['Close'].iloc[-1]) > float(nifty['EMA50'].iloc[-1])
        if nifty_above:
            st.success(f"✅ Nifty ({nifty['Close'].iloc[-1]:,.0f}) is ABOVE 50 EMA ({nifty['EMA50'].iloc[-1]:,.0f}) — TRADING ACTIVE")
        else:
            st.error(f"🛑 Nifty ({nifty['Close'].iloc[-1]:,.0f}) is BELOW 50 EMA ({nifty['EMA50'].iloc[-1]:,.0f}) — NO NEW TRADES")
    except:
        st.warning("Could not fetch Nifty data")

    # Trade history
    st.divider()
    st.subheader("📅 Trade History")
    try:
        import sheets as sh
        swing_ws = sh.get_sheet().worksheet("Swing")
        all_records = swing_ws.get_all_records()
        if all_records:
            sdf = pd.DataFrame(all_records)
            sdf['pnl'] = pd.to_numeric(sdf.get('P&L', 0), errors='coerce').fillna(0)
            closed = sdf[sdf['Status'] == 'CLOSED']
            if not closed.empty:
                total_pnl = closed['pnl'].sum()
                wins = (closed['pnl'] > 0).sum()
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("💰 Total P&L", f"₹{total_pnl:+,.0f}")
                col2.metric("📊 Trades", len(closed))
                col3.metric("🟢 Win Rate", f"{100*wins/len(closed):.0f}%")
                col4.metric("📈 Avg P&L", f"₹{total_pnl/len(closed):+,.0f}")

                # Equity curve
                closed_sorted = closed.sort_values('Date')
                closed_sorted['cumulative'] = 500000 + closed_sorted['pnl'].cumsum()
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=closed_sorted['Date'], y=closed_sorted['cumulative'],
                    mode='lines+markers', line=dict(color='#ff6b35', width=2),
                    fill='tozeroy', fillcolor='rgba(255,107,53,0.1)'))
                fig.add_hline(y=500000, line_dash="dash", line_color="gray", annotation_text="Capital ₹5L")
                fig.update_layout(height=300, title="Equity Curve", yaxis_title="₹")
                st.plotly_chart(fig, use_container_width=True)

                st.dataframe(closed[['Date','Stock','Entry','SL','Target','Exit','Exit Date','Exit Reason','P&L']].sort_values('Date', ascending=False), use_container_width=True, hide_index=True)
            else:
                st.info("No closed trades yet.")
        else:
            st.info("No swing trade data yet. Scanner will populate this.")
    except Exception as e:
        st.warning(f"Could not load Swing data: {e}")

elif page == "🎯 Multi-Stock ORB":
    st.title("🎯 Multi-Stock ORB — Intraday")
    st.caption("87 F&O Stocks | OR 0.7-1.5% | Top 3 | Entry 9:36-10:00 | Exit 3:15 PM | 88% CAGR")

    # Backtest results
    st.subheader("📊 Backtest Results (2018-2024)")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("CAGR", "87.7%")
    col2.metric("Max Drawdown", "-27.2%")
    col3.metric("Win Rate", "~49%")
    col4.metric("Trades/Day", "3")

    yearly_data = {
        "Year": [2018, 2019, 2020, 2021, 2022, 2023, 2024],
        "Return": [131.9, 29.9, 145.5, 137.3, 134.1, 14.4, 74.7],
        "Trades": [735, 732, 712, 741, 738, 735, 744],
        "Win%": [49.0, 46.6, 49.0, 50.2, 51.2, 49.3, 46.1],
    }
    ydf = pd.DataFrame(yearly_data)

    fig = go.Figure()
    colors = ['#00cc96' if r > 0 else '#ef553b' for r in ydf["Return"]]
    fig.add_trace(go.Bar(x=ydf["Year"], y=ydf["Return"], marker_color=colors, text=[f"+{r:.0f}%" for r in ydf["Return"]], textposition="outside"))
    fig.update_layout(height=350, title="Yearly Returns", yaxis_title="%", showlegend=False)
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(ydf, use_container_width=True, hide_index=True)

    # Strategy rules
    st.divider()
    st.subheader("📋 Strategy Rules")
    st.markdown("""
**Universe:** 87 F&O stocks across 9 Nifty sector indices

**Scan (9:30 AM):**
1. Calculate 15-min Opening Range (9:15–9:30) for each stock
2. Filter: OR range = 0.7% to 1.5% of price
3. Rank by OR range (biggest first), pick top 3

**Entry (9:36–10:00 AM):**
- Stock breaks above OR high → BUY (LONG)
- Stock breaks below OR low → SELL (SHORT)
- No breakout by 10:00 → skip

**Exit:**
- SL: opposite side of OR
- Target: 3× OR range
- Time: 3:15 PM (if no SL/TGT hit)

**Capital:** ₹1.2L (with 5x intraday margin = ₹6L exposure)
    """)

    # Live trades from Google Sheet (future)
    st.divider()
    st.subheader("📅 Paper Trades")
    try:
        import sheets as sh
        ms_ws = sh.get_sheet().worksheet("MultiORB")
        records = ms_ws.get_all_records()
        if records:
            msdf = pd.DataFrame(records)
            msdf['pnl'] = pd.to_numeric(msdf.get('P&L', 0), errors='coerce').fillna(0)
            closed = msdf[msdf.get('Status', '') == 'CLOSED'] if 'Status' in msdf.columns else msdf
            if not closed.empty and closed['pnl'].sum() != 0:
                total_pnl = closed['pnl'].sum()
                wins = (closed['pnl'] > 0).sum()
                c1, c2, c3 = st.columns(3)
                c1.metric("💰 Total P&L", f"₹{total_pnl:+,.0f}")
                c2.metric("📊 Trades", len(closed))
                c3.metric("🟢 Win Rate", f"{100*wins/len(closed):.0f}%")
                st.dataframe(closed.sort_values('Date', ascending=False).head(20), use_container_width=True, hide_index=True)
            else:
                st.info("No closed trades yet. Cron will populate this.")
        else:
            st.info("No trade data yet. Waiting for cron to start.")
    except:
        st.info("📌 MultiORB worksheet not created yet. Will be populated when cron starts.")
