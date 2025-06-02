# from alpha_vantage.timeseries import TimeSeries

# ts = TimeSeries(key='KH09FUMTCWJPK0YI', output_format='pandas')

# data, meta = ts.get_daily(symbol='SPY', outputsize='compact')
# print(data.tail())

# from polygon import RESTClient


# client = RESTClient(api_key="dNTu7WmL18WNnTWh5pNtznspjULHHpbW")

# aggs = client.get_aggs("SPY", 1, "day", "2023-01-01", "2024-01-01")
# for bar in aggs:
#     print(bar.close)

# import yfinance as yf

# ticker = yf.Ticker("SPY")
# hist = ticker.history(period="1mo")

# print(hist.tail())
# # print(hist.columns)
# import requests
# symbol = "TA125"
# API_KEY = "1c3ae9e70c164149b6520067489dc5b5"
# url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1day&apikey={API_KEY}"
# response = requests.get(url)
# data = response.json()

# print(data)
# import yfinance as yf
# ticker = yf.Ticker("EIS")
# print(ticker.history(period="1mo"))

import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import numpy as np

# Israeli ETF tickers (these are the likely ticker symbols)
etf_tickers = {
    'Tel Aviv 125': 'TASE125.TA',  # TA-125 Index ETF
    'Tel Aviv 35': 'TA35.TA',     # TA-35 Index ETF  
    'Tel Aviv Banks': 'BANK.TA'   # Banking sector ETF
}

# Alternative tickers to try if the above don't work
alternative_tickers = {
    'Tel Aviv 125': ['T125.TA', 'TASE.TA'],
    'Tel Aviv 35': ['T35.TA', 'TA-35.TA'],
    'Tel Aviv Banks': ['BANKS.TA', 'BNKS.TA']
}

def fetch_etf_data(ticker, period='1mo'):
    """Fetch ETF data with error handling"""
    try:
        etf = yf.Ticker(ticker)
        data = etf.history(period=period)
        info = etf.info
        return data, info
    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return None, None

def display_etf_summary(name, ticker, data, info):
    """Display summary information for an ETF"""
    if data is None or data.empty:
        print(f"\n❌ {name} ({ticker}): No data available")
        return
    
    print(f"\n📊 {name} ({ticker})")
    print("=" * 50)
    
    # Basic info
    if info:
        print(f"Full Name: {info.get('longName', 'N/A')}")
        print(f"Currency: {info.get('currency', 'N/A')}")
        print(f"Exchange: {info.get('exchange', 'N/A')}")
    
    # Price data
    current_price = data['Close'].iloc[-1]
    prev_close = data['Close'].iloc[-2] if len(data) > 1 else current_price
    change = current_price - prev_close
    change_pct = (change / prev_close) * 100
    
    print(f"Current Price: ₪{current_price:.2f}")
    print(f"Previous Close: ₪{prev_close:.2f}")
    print(f"Change: ₪{change:.2f} ({change_pct:+.2f}%)")
    
    # Volume and range
    print(f"Volume: {data['Volume'].iloc[-1]:,.0f}")
    print(f"Day High: ₪{data['High'].iloc[-1]:.2f}")
    print(f"Day Low: ₪{data['Low'].iloc[-1]:.2f}")
    
    # Period statistics
    period_high = data['High'].max()
    period_low = data['Low'].min()
    avg_volume = data['Volume'].mean()
    
    print(f"\n📈 Period Statistics:")
    print(f"Period High: ₪{period_high:.2f}")
    print(f"Period Low: ₪{period_low:.2f}")
    print(f"Average Volume: {avg_volume:,.0f}")

def plot_etf_comparison(etf_data_dict):
    """Plot price comparison of ETFs"""
    plt.figure(figsize=(12, 8))
    
    for name, (data, _) in etf_data_dict.items():
        if data is not None and not data.empty:
            # Normalize prices to show percentage change
            normalized = (data['Close'] / data['Close'].iloc[0] - 1) * 100
            plt.plot(normalized.index, normalized.values, label=name, linewidth=2)
    
    plt.title('ETF Performance Comparison (% Change)', fontsize=16, fontweight='bold')
    plt.xlabel('Date', fontsize=12)
    plt.ylabel('Percentage Change (%)', fontsize=12)
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

def main():
    print("🔍 Checking Israeli ETFs...")
    print("=" * 60)
    
    etf_data_dict = {}
    
    # Fetch data for each ETF
    for name, ticker in etf_tickers.items():
        print(f"\nFetching data for {name}...")
        data, info = fetch_etf_data(ticker)
        
        # If primary ticker fails, try alternatives
        if data is None and name in alternative_tickers:
            print(f"Primary ticker failed, trying alternatives...")
            for alt_ticker in alternative_tickers[name]:
                data, info = fetch_etf_data(alt_ticker)
                if data is not None:
                    ticker = alt_ticker
                    break
        
        etf_data_dict[name] = (data, info)
        display_etf_summary(name, ticker, data, info)
    
    # Plot comparison if we have data
    valid_data = {name: data for name, data in etf_data_dict.items() 
                  if data[0] is not None and not data[0].empty}
    
    if len(valid_data) > 1:
        print(f"\n📊 Plotting comparison chart...")
        plot_etf_comparison(valid_data)
    elif len(valid_data) == 1:
        print(f"\n📊 Plotting single ETF chart...")
        name, (data, _) = list(valid_data.items())[0]
        plt.figure(figsize=(10, 6))
        plt.plot(data.index, data['Close'], linewidth=2)
        plt.title(f'{name} - Price Chart', fontsize=16, fontweight='bold')
        plt.xlabel('Date')
        plt.ylabel('Price (₪)')
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.show()

# Additional function to get real-time quotes
def get_realtime_quotes():
    """Get real-time quotes for the ETFs"""
    print("\n💱 Real-time Quotes:")
    print("=" * 40)
    
    for name, ticker in etf_tickers.items():
        try:
            etf = yf.Ticker(ticker)
            info = etf.fast_info
            print(f"{name}: ₪{info.last_price:.2f}")
        except:
            print(f"{name}: Quote unavailable")

if __name__ == "__main__":
    # Install required packages first
    print("📦 Required packages: yfinance, pandas, matplotlib")
    print("Install with: pip install yfinance pandas matplotlib")
    print()
    
    main()
    
    # Uncomment the line below for real-time quotes
    # get_realtime_quotes()