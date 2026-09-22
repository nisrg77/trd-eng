import sys
import os
import pandas as pd
from datetime import datetime, timezone
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

url = f"{config.ALPACA_DATA_URL}/stocks/TSLA/bars"
headers = {"APCA-API-KEY-ID": config.ALPACA_API_KEY, "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET}
end = datetime.now(timezone.utc)
start = end - pd.Timedelta(days=60)
params = {
    "timeframe": "1Day",
    "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "limit": 100,
    "feed": "iex"
}

print(f"Requesting: {url} with params {params}")
resp = requests.get(url, headers=headers, params=params)
print(f"Status Code: {resp.status_code}")
try:
    print(resp.json())
except Exception as e:
    print(resp.text)
