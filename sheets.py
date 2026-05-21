import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import json
import streamlit as st

SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']


def get_client():
    """Connect to Google Sheets using service account from Streamlit secrets."""
    creds_dict = json.loads(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def get_sheet(sheet_name="Momentum Strategy"):
    """Get the Google Sheet by name."""
    client = get_client()
    return client.open(sheet_name)


def init_sheets(sheet_name="Momentum Strategy"):
    """Initialize sheets if they don't exist."""
    spreadsheet = get_sheet(sheet_name)
    existing = [ws.title for ws in spreadsheet.worksheets()]

    if "Portfolio" not in existing:
        ws = spreadsheet.add_worksheet("Portfolio", rows=10, cols=6)
        ws.update('A1:F1', [['Stock', 'Qty', 'Buy Price', 'Buy Date', 'Current Price', 'P&L %']])

    if "Trades" not in existing:
        ws = spreadsheet.add_worksheet("Trades", rows=500, cols=7)
        ws.update('A1:G1', [['Date', 'Action', 'Stock', 'Qty', 'Price', 'Value', 'P&L']])

    if "Monthly" not in existing:
        ws = spreadsheet.add_worksheet("Monthly", rows=200, cols=4)
        ws.update('A1:D1', [['Month', 'Portfolio Value', 'Return %', 'Stocks Held']])

    if "Config" not in existing:
        ws = spreadsheet.add_worksheet("Config", rows=5, cols=2)
        ws.update('A1:B3', [['Key', 'Value'], ['cash', '100000'], ['start_date', '']])

    # Remove default Sheet1 if it exists
    if "Sheet1" in existing:
        spreadsheet.del_worksheet(spreadsheet.worksheet("Sheet1"))


def get_cash():
    ws = get_sheet().worksheet("Config")
    records = ws.get_all_records()
    for r in records:
        if r['Key'] == 'cash':
            return float(r['Value'])
    return 100000


def set_cash(amount):
    ws = get_sheet().worksheet("Config")
    ws.update('B2', [[str(round(amount, 2))]])


def get_holdings():
    ws = get_sheet().worksheet("Portfolio")
    records = ws.get_all_records()
    return pd.DataFrame(records) if records else pd.DataFrame(columns=['Stock', 'Qty', 'Buy Price', 'Buy Date', 'Current Price', 'P&L %'])


def set_holdings(holdings_df):
    ws = get_sheet().worksheet("Portfolio")
    ws.clear()
    ws.update('A1:F1', [['Stock', 'Qty', 'Buy Price', 'Buy Date', 'Current Price', 'P&L %']])
    if not holdings_df.empty:
        rows = holdings_df.values.tolist()
        ws.update(f'A2:F{len(rows)+1}', rows)


def add_trade(date, action, stock, qty, price, value, pnl=""):
    ws = get_sheet().worksheet("Trades")
    ws.append_row([date, action, stock, qty, price, value, pnl])


def get_trades():
    ws = get_sheet().worksheet("Trades")
    records = ws.get_all_records()
    return pd.DataFrame(records) if records else pd.DataFrame(columns=['Date', 'Action', 'Stock', 'Qty', 'Price', 'Value', 'P&L'])


def add_monthly_record(month, portfolio_value, return_pct, stocks):
    ws = get_sheet().worksheet("Monthly")
    ws.append_row([month, portfolio_value, return_pct, stocks])


def get_monthly():
    ws = get_sheet().worksheet("Monthly")
    records = ws.get_all_records()
    return pd.DataFrame(records) if records else pd.DataFrame(columns=['Month', 'Portfolio Value', 'Return %', 'Stocks Held'])


def get_starting_capital():
    ws = get_sheet().worksheet("Config")
    records = ws.get_all_records()
    for r in records:
        if r['Key'] == 'starting_capital':
            return float(r['Value'])
    return 200000  # default
