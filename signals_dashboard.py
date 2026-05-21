"""
MARKET SIGNALS DASHBOARD
=========================
All-in-one view of market signals for trading decisions.
Combines free + premium signal logic.

Run: streamlit run signals_dashboard.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="Market Signals", page_icon="🎯", layout="wide")
st.title("🎯 Market Signals Dashboard — India")

# --- DATA FETCHING ---
@st.cache_data(ttl=300)
def get_vix():
    df = yf.download('^INDIAVIX', period='90d', progress=False)
    df.columns = df.columns.get_level_values(0)
    return df

@st.cache_data(ttl=300)
def get_nifty():
    df = yf.download('^NSEI', period='200d', progress=False)
    df.columns = df.columns.get_level_values(0)
    return df

@st.cache_data(ttl=300)
def get_sectors():
    sectors = {
        'IT': '^CNXIT', 'Bank': '^NSEBANK', 'Pharma': '^CNXPHARMA',
        'Auto': '^CNXAUTO', 'Metal': '^CNXMETAL', 'FMCG': '^CNXFMCG',
        'Energy': '^CNXENERGY', 'Realty': '^CNXREALTY',
    }
    results = {}
    for name, ticker in sectors.items():
        try:
            df = yf.download(ticker, period='90d', progress=False)
            df.columns = df.columns.get_level_values(0)
            if len(df) > 20:
                results[name] = df['Close']
        except:
            pass
    return results

# --- SIGNAL CALCULATIONS ---
def calc_market_regime(nifty):
    """Determine if market is trending or range-bound."""
    close = nifty['Close']
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    current = float(close.iloc[-1])
    ma50 = float(sma50.iloc[-1])
    ma200 = float(sma200.iloc[-1]) if len(sma200.dropna()) > 0 else ma50

    if current > ma50 > ma200:
        return "STRONG UPTREND", "🟢"
    elif current > ma50:
        return "UPTREND", "🟢"
    elif current < ma50 < ma200:
        return "STRONG DOWNTREND", "🔴"
    elif current < ma50:
        return "DOWNTREND", "🔴"
    else:
        return "SIDEWAYS", "🟡"

def calc_vix_signal(vix):
    """VIX-based signal."""
    current = float(vix['Close'].iloc[-1])
    avg = float(vix['Close'].rolling(20).mean().iloc[-1])
    if current < 13:
        return "LOW FEAR (Complacent)", "🟢", current
    elif current < 18:
        return "NORMAL", "🟡", current
    elif current < 25:
        return "ELEVATED FEAR", "🟠", current
    else:
        return "HIGH FEAR (Panic)", "🔴", current

def calc_momentum_signal(nifty):
    """Nifty momentum."""
    close = nifty['Close']
    ret_1w = (float(close.iloc[-1]) / float(close.iloc[-5]) - 1) * 100
    ret_1m = (float(close.iloc[-1]) / float(close.iloc[-21]) - 1) * 100
    ret_3m = (float(close.iloc[-1]) / float(close.iloc[-63]) - 1) * 100 if len(close) > 63 else 0
    return ret_1w, ret_1m, ret_3m

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def generate_overall_signal(regime, vix_level, nifty_rsi, sector_breadth):
    """Combine all signals into one recommendation."""
    score = 0
    # Regime
    if "UPTREND" in regime: score += 2
    elif "DOWNTREND" in regime: score -= 2
    # VIX
    if vix_level < 15: score += 1
    elif vix_level > 25: score -= 2
    # RSI
    if 40 < nifty_rsi < 60: score += 1
    elif nifty_rsi > 75: score -= 1
    elif nifty_rsi < 30: score += 1  # oversold bounce
    # Breadth
    if sector_breadth > 5: score += 1
    elif sector_breadth < 3: score -= 1

    if score >= 3: return "STRONG BUY", "🟢🟢🟢"
    elif score >= 1: return "BUY", "🟢"
    elif score <= -3: return "STRONG SELL", "🔴🔴🔴"
    elif score <= -1: return "SELL / STAY CASH", "🔴"
    else: return "NEUTRAL / WAIT", "🟡"


# --- DISPLAY ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "📈 Sectors", "🎯 Strategy Signals", "📋 Premium Signals"])

with tab1:
    st.header("Market Overview")

    nifty = get_nifty()
    vix = get_vix()

    col1, col2, col3, col4 = st.columns(4)

    # Nifty
    nifty_price = float(nifty['Close'].iloc[-1])
    nifty_change = (nifty_price / float(nifty['Close'].iloc[-2]) - 1) * 100
    col1.metric("Nifty 50", f"{nifty_price:,.0f}", f"{nifty_change:+.1f}%")

    # VIX
    vix_signal, vix_emoji, vix_val = calc_vix_signal(vix)
    col2.metric("India VIX", f"{vix_val:.1f}", vix_signal)

    # Regime
    regime, regime_emoji = calc_market_regime(nifty)
    col3.metric("Market Regime", f"{regime_emoji} {regime}")

    # RSI
    nifty_rsi = float(calc_rsi(nifty['Close']).iloc[-1])
    col4.metric("Nifty RSI(14)", f"{nifty_rsi:.0f}", "Overbought" if nifty_rsi > 70 else "Oversold" if nifty_rsi < 30 else "Normal")

    # Nifty chart with MAs
    st.subheader("Nifty 50 — Last 6 Months")
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=nifty.index, open=nifty['Open'], high=nifty['High'],
                                  low=nifty['Low'], close=nifty['Close'], name='Nifty'))
    sma50 = nifty['Close'].rolling(50).mean()
    fig.add_trace(go.Scatter(x=nifty.index, y=sma50, name='50 MA', line=dict(color='orange', width=1)))
    fig.update_layout(height=400, xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

    # VIX chart
    st.subheader("India VIX — Fear Gauge")
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=vix.index, y=vix['Close'], fill='tozeroy', name='VIX'))
    fig2.add_hline(y=15, line_dash="dash", line_color="green", annotation_text="Low Fear")
    fig2.add_hline(y=25, line_dash="dash", line_color="red", annotation_text="High Fear")
    fig2.update_layout(height=250)
    st.plotly_chart(fig2, use_container_width=True)

with tab2:
    st.header("📈 Sector Rotation")
    sectors = get_sectors()

    if sectors:
        st.subheader("Sector Momentum (1-week / 1-month / 3-month)")
        sector_data = []
        for name, prices in sectors.items():
            prices = prices.dropna()
            if len(prices) > 63:
                r1w = (float(prices.iloc[-1]) / float(prices.iloc[-5]) - 1) * 100
                r1m = (float(prices.iloc[-1]) / float(prices.iloc[-21]) - 1) * 100
                r3m = (float(prices.iloc[-1]) / float(prices.iloc[-63]) - 1) * 100
                sector_data.append({'Sector': name, '1 Week': r1w, '1 Month': r1m, '3 Month': r3m})

        sdf = pd.DataFrame(sector_data).sort_values('1 Month', ascending=False)

        # Color-coded table
        st.dataframe(sdf.style.format({'1 Week': '{:+.1f}%', '1 Month': '{:+.1f}%', '3 Month': '{:+.1f}%'})
                     .background_gradient(cmap='RdYlGn', subset=['1 Week', '1 Month', '3 Month']),
                     use_container_width=True, hide_index=True)

        # Sector bar chart
        import plotly.express as px
        fig = px.bar(sdf, x='Sector', y='1 Month', color='1 Month',
                     color_continuous_scale='RdYlGn', title='Sector 1-Month Returns')
        st.plotly_chart(fig, use_container_width=True)

        # Breadth
        positive_sectors = len(sdf[sdf['1 Month'] > 0])
        st.metric("Market Breadth", f"{positive_sectors}/{len(sdf)} sectors positive")

with tab3:
    st.header("🎯 Strategy Signals")

    nifty = get_nifty()
    vix = get_vix()
    sectors = get_sectors()

    # Calculate all signals
    regime, _ = calc_market_regime(nifty)
    _, _, vix_val = calc_vix_signal(vix)
    nifty_rsi = float(calc_rsi(nifty['Close']).iloc[-1])
    ret_1w, ret_1m, ret_3m = calc_momentum_signal(nifty)

    sector_data = []
    for name, prices in sectors.items():
        prices = prices.dropna()
        if len(prices) > 21:
            r1m = (float(prices.iloc[-1]) / float(prices.iloc[-21]) - 1) * 100
            sector_data.append(r1m)
    breadth = sum(1 for r in sector_data if r > 0)

    # Overall signal
    signal, signal_emoji = generate_overall_signal(regime, vix_val, nifty_rsi, breadth)

    st.markdown(f"## Overall Signal: {signal_emoji} **{signal}**")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("✅ Bullish Signals")
        checks = []
        if "UPTREND" in regime: checks.append("✅ Market in uptrend")
        if vix_val < 18: checks.append("✅ VIX low (calm market)")
        if nifty_rsi < 60: checks.append("✅ RSI not overbought")
        if ret_1m > 0: checks.append("✅ Nifty positive 1-month")
        if breadth >= 5: checks.append("✅ Majority sectors positive")
        if not checks: checks.append("❌ No bullish signals")
        for c in checks: st.write(c)

    with col2:
        st.subheader("⚠️ Bearish Signals")
        checks = []
        if "DOWNTREND" in regime: checks.append("🔴 Market in downtrend")
        if vix_val > 20: checks.append("🔴 VIX elevated (fear)")
        if nifty_rsi > 70: checks.append("🔴 RSI overbought")
        if ret_1m < -3: checks.append("🔴 Nifty falling")
        if breadth <= 2: checks.append("🔴 Most sectors negative")
        if not checks: checks.append("✅ No bearish signals")
        for c in checks: st.write(c)

    st.divider()
    st.subheader("📋 Action Plan")

    if "BUY" in signal:
        st.success("""
        **ACTION: Deploy momentum strategy this month**
        - Market conditions favor momentum
        - Buy top 5 stocks as per ranking
        - Use full allocation
        """)
    elif "SELL" in signal:
        st.error("""
        **ACTION: Stay in CASH this month**
        - Market conditions are unfavorable
        - Skip this month's rebalance
        - Wait for signals to improve
        """)
    else:
        st.warning("""
        **ACTION: Reduce position size**
        - Mixed signals — use 50% allocation
        - Or wait a few days for clarity
        """)

with tab4:
    st.header("📋 Premium Signal Ideas")
    st.info("These signals require paid data sources. Below is the logic — you'd need to manually input the data or connect to a paid API.")

    st.subheader("1. FII/DII Flow Signal")
    st.markdown("""
    **Source:** NSE website (free, but manual) or Trendlyne (₹500/mo for API)

    **Logic:**
    - If FII net buyers > ₹1000 Cr in last 5 days → BULLISH
    - If FII net sellers > ₹2000 Cr in last 5 days → BEARISH
    - Combine with our momentum strategy: only buy when FII are buying
    """)

    fii_input = st.number_input("FII Net Flow (last 5 days, in ₹ Crores)", value=0, step=100)
    if fii_input > 1000:
        st.success(f"🟢 FII buying ₹{fii_input} Cr — BULLISH. Safe to deploy momentum strategy.")
    elif fii_input < -2000:
        st.error(f"🔴 FII selling ₹{abs(fii_input)} Cr — BEARISH. Consider staying in cash.")
    else:
        st.warning(f"🟡 FII flow neutral (₹{fii_input} Cr). Proceed with caution.")

    st.divider()
    st.subheader("2. Put-Call Ratio (PCR)")
    st.markdown("""
    **Source:** NSE options data (free) or Sensibull/Opstra

    **Logic:**
    - PCR > 1.2 → Too many puts = market oversold = BULLISH
    - PCR < 0.7 → Too many calls = market overbought = BEARISH
    - PCR 0.8-1.1 → Neutral
    """)

    pcr_input = st.number_input("Current Nifty PCR", value=1.0, step=0.1, format="%.1f")
    if pcr_input > 1.2:
        st.success(f"🟢 PCR {pcr_input} — Oversold. Good time to buy.")
    elif pcr_input < 0.7:
        st.error(f"🔴 PCR {pcr_input} — Overbought. Risky to buy.")
    else:
        st.info(f"🟡 PCR {pcr_input} — Neutral.")

    st.divider()
    st.subheader("3. Max Pain Level")
    st.markdown("""
    **Source:** Sensibull, Opstra (free tier available)

    **Logic:** Nifty tends to expire near Max Pain on expiry day.
    - If Nifty is below Max Pain → likely to go UP
    - If Nifty is above Max Pain → likely to come DOWN
    """)

    max_pain = st.number_input("Current Max Pain Level", value=23500, step=50)
    nifty_now = float(get_nifty()['Close'].iloc[-1])
    diff = nifty_now - max_pain
    if diff < -100:
        st.success(f"🟢 Nifty ({nifty_now:.0f}) is {abs(diff):.0f} pts BELOW Max Pain ({max_pain}). Likely to pull UP.")
    elif diff > 100:
        st.error(f"🔴 Nifty ({nifty_now:.0f}) is {diff:.0f} pts ABOVE Max Pain ({max_pain}). Likely to pull DOWN.")
    else:
        st.info(f"🟡 Nifty near Max Pain. Expiry likely flat.")

    st.divider()
    st.subheader("4. Insider/Promoter Buying")
    st.markdown("""
    **Source:** Trendlyne (₹500/mo) or BSE SAST filings (free, manual)

    **Logic:** When promoters buy their own stock, it's the strongest bullish signal.
    - Check if any of your momentum picks have recent promoter buying
    - Promoter buying + high momentum = highest conviction trade
    """)
