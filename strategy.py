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
TOP_N = 5
SKIP_MONTHS = [1, 2, 3]


def is_skip_month():
    return datetime.now().month in SKIP_MONTHS


def get_momentum_ranking(lookback_months=3):
    """Calculate momentum for all Nifty 100 stocks."""
    lookback_days = lookback_months * 21
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days * 2)

    results = []
    for ticker in NIFTY_100:
        try:
            df = yf.download(ticker, start=start_date, end=end_date, progress=False)
            df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=['Close'])
            if len(df) > 40:
                current = float(df['Close'].iloc[-1])
                past = float(df['Close'].iloc[-lookback_days]) if len(df) > lookback_days else float(df['Close'].iloc[0])
                if past > 0:
                    momentum = ((current / past) - 1) * 100
                    results.append({
                        'Stock': ticker.replace('.NS', ''),
                        'Ticker': ticker,
                        'Price': current,
                        'Momentum': momentum
                    })
        except:
            pass

    df = pd.DataFrame(results)
    if df.empty:
        return pd.DataFrame(columns=['Stock', 'Ticker', 'Price', 'Momentum'])
    return df.sort_values('Momentum', ascending=False).reset_index(drop=True)


def get_top_picks(n=TOP_N, lookback_months=3):
    """Get top N momentum stocks."""
    ranking = get_momentum_ranking(lookback_months)
    return ranking.head(n)


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
