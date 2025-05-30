# from alpha_vantage.timeseries import TimeSeries

# ts = TimeSeries(key='KH09FUMTCWJPK0YI', output_format='pandas')

# data, meta = ts.get_daily(symbol='SPY', outputsize='compact')
# print(data.tail())

# from polygon import RESTClient


# client = RESTClient(api_key="dNTu7WmL18WNnTWh5pNtznspjULHHpbW")

# aggs = client.get_aggs("SPY", 1, "day", "2023-01-01", "2024-01-01")
# for bar in aggs:
#     print(bar.close)

import yfinance as yf

ticker = yf.Ticker("SPY")
hist = ticker.history(period="1mo")

print(hist.tail())
print(hist.columns)