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
    st.caption("Nifty 100 | Top 5 | 3-Month Lookback | Skip Jan-Mar")
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
    overall_return = (total_portfolio / 100000 - 1) * 100

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
    fig.add_hline(y=100000, line_dash="dash", line_color="gray", annotation_text="Starting Capital ₹1L")
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
        top_n = st.number_input("Top N Stocks", min_value=1, max_value=15, value=5)
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

    st.info("This will sell stocks that dropped out of top 5 and buy new entries. Stocks still in top 5 are kept.")

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

            # Sell stocks that dropped out
            kept_holdings = []
            if not holdings.empty:
                for _, row in holdings.iterrows():
                    if row['Stock'] in to_sell:
                        price = get_live_price(row['Stock'] + '.NS') or float(row['Buy Price'])
                        qty = int(row['Qty'])
                        proceeds = qty * price
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
                            cash -= cost
                            kept_holdings.append({
                                'Stock': row['Stock'], 'Qty': qty,
                                'Buy Price': round(row['Price'], 2),
                                'Buy Date': today, 'Current Price': round(row['Price'], 2), 'P&L %': 0
                            })
                            sheets.add_trade(today, 'BUY', row['Stock'], qty,
                                           round(row['Price'], 2), round(cost, 2), '')

            sheets.set_holdings(pd.DataFrame(kept_holdings))
            sheets.set_cash(cash)

            # Record monthly
            total_value = cash + sum(h['Qty'] * float(h['Buy Price']) for h in kept_holdings)
            ret_pct = (total_value / 100000 - 1) * 100
            stocks_str = ', '.join(h['Stock'] for h in kept_holdings)
            sheets.add_monthly_record(datetime.now().strftime('%b %Y'), round(total_value, 0),
                                     round(ret_pct, 1), stocks_str)

            if not to_sell and not to_buy:
                st.success("✅ No changes needed — same stocks remain in top 5!")
            else:
                st.success(f"✅ Rebalance complete! Sold {len(to_sell)}, Bought {len(to_buy)}, Kept {len(to_keep)}")
            st.balloons()


# --- INTRADAY ORB FUNCTIONS ---
def show_intraday():
    import plotly.graph_objects as go
    import json

    ORB_LOT = 65
    ORB_CAPITAL = 175000
    ORB_MIN_RANGE = 50
    ORB_MAX_RANGE = 200
    ORB_TARGET_MULT = 1.5
    ORB_TRADE_FILE = 'orb_trades.json'

    def load_orb_trades():
        if os.path.exists(ORB_TRADE_FILE):
            with open(ORB_TRADE_FILE) as f:
                return json.load(f)
        return []

    def save_orb_trades(trades):
        with open(ORB_TRADE_FILE, 'w') as f:
            json.dump(trades, f, indent=2)

    @st.cache_data(ttl=60)
    def get_nifty_today():
        df = yf.download('^NSEI', period='5d', interval='5m', progress=False)
        df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        today = df.index[-1].date()
        return df[df.index.date == today], df

    st.title("⚡ Intraday ORB — Live Paper Trading")
    st.caption("Nifty Futures | Lot: 65 | Capital: ₹1,75,000")

    today_data, all_data = get_nifty_today()

    if len(today_data) < 6:
        st.warning("⏳ Market is closed or hasn't completed 30 minutes yet. Showing last trading day's data.")
        # Show last complete trading day
        all_data_copy = all_data.copy()
        all_data_copy['date'] = all_data_copy.index.date
        dates = sorted(all_data_copy['date'].unique())
        for d in reversed(dates):
            day = all_data_copy[all_data_copy['date'] == d]
            if len(day) >= 6:
                today_data = day
                st.info(f"📅 Showing data for: **{d}**")
                break

    if len(today_data) < 6:
        st.error("No data available.")
        return

    first_30 = today_data.iloc[:6]
    orb_high = float(first_30['High'].max())
    orb_low = float(first_30['Low'].min())
    orb_range = orb_high - orb_low
    current_price = float(today_data['Close'].iloc[-1])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Nifty Now", f"{current_price:,.1f}")
    col2.metric("OR High", f"{orb_high:,.1f}")
    col3.metric("OR Low", f"{orb_low:,.1f}")
    col4.metric("Range", f"{orb_range:,.0f} pts")

    st.divider()

    if orb_range < ORB_MIN_RANGE:
        st.error(f"❌ NO TRADE — Range too tight ({orb_range:.0f} < {ORB_MIN_RANGE})")
    elif orb_range > ORB_MAX_RANGE:
        st.error(f"❌ NO TRADE — Range too wide ({orb_range:.0f} > {ORB_MAX_RANGE})")
    else:
        target_long = orb_high + orb_range * ORB_TARGET_MULT
        target_short = orb_low - orb_range * ORB_TARGET_MULT
        risk = orb_range * ORB_LOT
        reward = orb_range * ORB_TARGET_MULT * ORB_LOT

        if current_price > orb_high:
            st.success(f"### 🟢 BUY SIGNAL — Entry: {orb_high:.1f} | SL: {orb_low:.1f} | Target: {target_long:.1f}\nRisk: ₹{risk:,.0f} | Reward: ₹{reward:,.0f}")
        elif current_price < orb_low:
            st.error(f"### 🔴 SHORT SIGNAL — Entry: {orb_low:.1f} | SL: {orb_high:.1f} | Target: {target_short:.1f}\nRisk: ₹{risk:,.0f} | Reward: ₹{reward:,.0f}")
        else:
            st.info(f"### ⏳ WAITING — BUY above {orb_high:.1f} | SHORT below {orb_low:.1f}\nRisk: ₹{risk:,.0f} | Reward: ₹{reward:,.0f}")

        # Chart
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=today_data.index, open=today_data['Open'],
                                      high=today_data['High'], low=today_data['Low'],
                                      close=today_data['Close'], name='Nifty'))
        fig.add_hline(y=orb_high, line_dash="dash", line_color="green", annotation_text=f"OR High: {orb_high:.0f}")
        fig.add_hline(y=orb_low, line_dash="dash", line_color="red", annotation_text=f"OR Low: {orb_low:.0f}")
        fig.update_layout(height=400, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    # Log trade
    st.divider()
    st.subheader("📝 Log Trade")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        direction = st.selectbox("Direction", ["LONG", "SHORT", "NO TRADE"])
    with col2:
        entry_p = st.number_input("Entry", value=int(orb_high) if orb_high else 0)
    with col3:
        exit_p = st.number_input("Exit", value=0)
    with col4:
        result = st.selectbox("Result", ["TARGET", "SL HIT", "EOD EXIT"])

    if st.button("💾 Save Trade"):
        if direction != "NO TRADE" and exit_p > 0:
            pnl = ((exit_p - entry_p) if direction == "LONG" else (entry_p - exit_p)) * ORB_LOT - 400
            trades = load_orb_trades()
            trades.append({'date': datetime.now().strftime('%Y-%m-%d'), 'direction': direction,
                          'entry': entry_p, 'exit': exit_p, 'pnl': round(pnl), 'result': result})
            save_orb_trades(trades)
            st.success(f"✅ Saved! P&L: ₹{pnl:+,.0f}")

    # History
    trades = load_orb_trades()
    if trades:
        st.divider()
        st.subheader("📜 Trade History")
        tdf = pd.DataFrame(trades)
        st.dataframe(tdf, use_container_width=True, hide_index=True)
        active = tdf[tdf['direction'] != 'NO TRADE']
        if not active.empty:
            col1, col2, col3 = st.columns(3)
            col1.metric("Total P&L", f"₹{active['pnl'].sum():+,.0f}")
            col2.metric("Win Rate", f"{len(active[active['pnl']>0])}/{len(active)} ({len(active[active['pnl']>0])/len(active)*100:.0f}%)")
            col3.metric("Portfolio", f"₹{ORB_CAPITAL + active['pnl'].sum():,.0f}")

    # Backtest Calendar
    st.divider()
    st.subheader("📅 Backtest Calendar (Last 2 Months)")

    import plotly.express as px
    if os.path.exists('backtest_calendar.json'):
        with open('backtest_calendar.json') as f:
            cal_data = json.load(f)
        cal_df = pd.DataFrame(cal_data)
        cal_df['date'] = pd.to_datetime(cal_df['date'])
        cal_df['day'] = cal_df['date'].dt.strftime('%a')
        cal_df['week'] = cal_df['date'].dt.isocalendar().week.astype(int)
        cal_df['weekday_num'] = cal_df['date'].dt.weekday

        # Summary metrics
        profit_days = len(cal_df[cal_df['pnl'] > 0])
        loss_days = len(cal_df[cal_df['pnl'] < 0])
        no_trade = len(cal_df[cal_df['pnl'] == 0])

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🟢 Profit Days", profit_days)
        col2.metric("🔴 Loss Days", loss_days)
        col3.metric("⚪ No Trade", no_trade)
        col4.metric("💰 Total P&L", f"₹{cal_df['pnl'].sum():+,.0f}")

        # Heatmap
        cal_df['color'] = cal_df['pnl'].apply(lambda x: 'Profit' if x > 0 else ('Loss' if x < 0 else 'No Trade'))
        cal_df['label'] = cal_df.apply(lambda r: f"{r['date'].strftime('%d %b')}\n₹{r['pnl']:+,.0f}\n{r['result']}", axis=1)

        fig = px.scatter(cal_df, x='week', y='weekday_num', color='pnl',
                        color_continuous_scale='RdYlGn', color_continuous_midpoint=0,
                        size=[20]*len(cal_df), hover_data=['date', 'pnl', 'result', 'direction'],
                        title='Daily P&L Calendar (Green=Profit, Red=Loss)')
        fig.update_yaxes(tickvals=[0,1,2,3,4], ticktext=['Mon','Tue','Wed','Thu','Fri'], autorange='reversed')
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)

        # Table view
        st.dataframe(cal_df[['date','day','direction','pnl','result','range']].sort_values('date', ascending=False),
                    use_container_width=True, hide_index=True)


# --- MAIN APP ---
import os

st.sidebar.title("📱 Strategy")
page = st.sidebar.radio("Select", ["📈 Monthly Momentum", "⚡ Intraday ORB"])

if page == "📈 Monthly Momentum":
    show_header()
    tab1, tab2, tab3, tab4 = st.tabs(["💼 Portfolio", "📊 Performance", "🏆 Rankings", "🔄 Rebalance"])
    with tab1:
        show_portfolio()
        show_trades()
    with tab2:
        show_monthly_chart()
    with tab3:
        show_momentum_ranking()
    with tab4:
        do_rebalance()
else:
    show_intraday()
