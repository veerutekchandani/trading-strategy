import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
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

    if st.button("🔄 Refresh Rankings"):
        st.cache_data.clear()

    with st.spinner("Calculating momentum for 90+ stocks..."):
        picks = get_top_picks(20)

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Top 5 (Buy These)")
        for i, row in picks.head(5).iterrows():
            st.success(f"**{i+1}. {row['Stock']}** — +{row['Momentum']:.1f}% | ₹{row['Price']:,.0f}")

    with col2:
        fig = px.bar(picks.head(15), x='Stock', y='Momentum', color='Momentum',
                     color_continuous_scale='RdYlGn', title='Top 15 Momentum Stocks')
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

    st.info("This will sell current holdings and buy the new top 5 momentum stocks.")

    if st.button("⚡ Execute Rebalance", type="primary"):
        with st.spinner("Calculating picks and executing trades..."):
            picks = get_top_picks(5)
            holdings = sheets.get_holdings()
            cash = sheets.get_cash()
            today = datetime.now().strftime('%Y-%m-%d')

            # Sell current holdings
            if not holdings.empty:
                for _, row in holdings.iterrows():
                    price = get_live_price(row['Stock'] + '.NS') or float(row['Buy Price'])
                    qty = int(row['Qty'])
                    proceeds = qty * price
                    pnl = proceeds - (qty * float(row['Buy Price']))
                    cash += proceeds
                    sheets.add_trade(today, 'SELL', row['Stock'], qty, round(price, 2),
                                   round(proceeds, 2), round(pnl, 2))

            # Buy new picks
            amount_per_stock = cash / 5
            new_holdings = []
            for _, row in picks.iterrows():
                qty = int(amount_per_stock / row['Price'])
                if qty > 0:
                    cost = qty * row['Price']
                    cash -= cost
                    new_holdings.append({
                        'Stock': row['Stock'], 'Qty': qty,
                        'Buy Price': round(row['Price'], 2),
                        'Buy Date': today, 'Current Price': round(row['Price'], 2), 'P&L %': 0
                    })
                    sheets.add_trade(today, 'BUY', row['Stock'], qty,
                                   round(row['Price'], 2), round(cost, 2), '')

            sheets.set_holdings(pd.DataFrame(new_holdings))
            sheets.set_cash(cash)

            # Record monthly
            total_value = cash + sum(r['Qty'] * r['Buy Price'] for r in new_holdings)
            ret_pct = (total_value / 100000 - 1) * 100
            stocks_str = ', '.join(r['Stock'] for r in new_holdings)
            sheets.add_monthly_record(datetime.now().strftime('%b %Y'), round(total_value, 0),
                                     round(ret_pct, 1), stocks_str)

            st.success("✅ Rebalance complete!")
            st.balloons()


# --- MAIN APP ---
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
