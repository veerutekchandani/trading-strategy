import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

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
]

LOOKBACK_DAYS = 63
TOP_N = 3
SKIP_MONTHS = []  # Trade all months now
SL_PCT = 0.20  # 20% stop loss


def is_skip_month():
    return datetime.now().month in SKIP_MONTHS


def get_momentum_ranking(lookback_months=3):
    """Calculate momentum for all Nifty 100 stocks with filters."""
    lookback_days = lookback_months * 21
    end_date = datetime.now()
    start_date = end_date - timedelta(days=300)

    results = []
    for ticker in NIFTY_100:
        try:
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Close'])
            if len(df) < 63:
                continue

            current = float(df['Close'].iloc[-1])
            past = float(df['Close'].iloc[-lookback_days]) if len(df) > lookback_days else float(df['Close'].iloc[0])
            if past <= 0:
                continue
            momentum = ((current / past) - 1) * 100

            # Filter 1: 3/3 consistency
            m1_ret = float(df['Close'].iloc[-1]) / float(df['Close'].iloc[-21]) - 1
            m2_ret = float(df['Close'].iloc[-21]) / float(df['Close'].iloc[-42]) - 1
            m3_ret = float(df['Close'].iloc[-42]) / float(df['Close'].iloc[-63]) - 1
            consistent = m1_ret > 0 and m2_ret > 0 and m3_ret > 0

            # Filter 2: Within 10% of 52-week high
            high_52w = float(df['High'].tail(252).max())
            dist_from_high = (current / high_52w - 1) * 100
            near_high = dist_from_high >= -10

            results.append({
                'Stock': ticker.replace('.NS', ''),
                'Ticker': ticker,
                'Price': current,
                'Momentum': momentum,
                'Consistent': consistent,
                'Dist_52w': round(dist_from_high, 1),
                'Near_High': near_high,
            })
        except:
            pass

    df = pd.DataFrame(results)
    if df.empty:
        return pd.DataFrame(columns=['Stock', 'Ticker', 'Price', 'Momentum', 'Consistent', 'Dist_52w', 'Near_High'])
    return df.sort_values('Momentum', ascending=False).reset_index(drop=True)


def get_top_picks(n=TOP_N, lookback_months=3):
    """Get top N momentum stocks with filters applied."""
    ranking = get_momentum_ranking(lookback_months)
    # Apply filters: 3/3 consistency + near 52w high
    filtered = ranking[(ranking['Consistent'] == True) & (ranking['Near_High'] == True)]
    if len(filtered) < n:
        # Fallback: relax to just consistency
        filtered = ranking[ranking['Consistent'] == True]
    return filtered.head(n)


def get_live_price(ticker):
    """Get latest price for a single stock."""
    try:
        df = yf.download(ticker if '.NS' in ticker else ticker + '.NS', period='5d', progress=False)
        df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=['Close'])
        if len(df) > 0:
            return float(df['Close'].iloc[-1])
    except:
        pass
    return None
