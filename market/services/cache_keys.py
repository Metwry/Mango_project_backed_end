from datetime import timedelta
from zoneinfo import ZoneInfo

WATCHLIST_QUOTES_KEY = "watchlist:quotes:latest"
WATCHLIST_QUOTES_MARKET_KEY_PREFIX = "watchlist:quotes:market:"
WATCHLIST_QUOTES_ORPHAN_KEY_PREFIX = "watchlist:quotes:orphan:"
USD_EXCHANGE_RATES_KEY = "watchlist:fx:usd-rates:latest"

DEFAULT_WATCHLIST_ORPHAN_TTL = 30 * 60
UTC8 = ZoneInfo("Asia/Shanghai")
FX_REFRESH_INTERVAL = timedelta(hours=4)
