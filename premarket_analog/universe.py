"""A curated default universe of liquid US large/mid-cap tickers, for the
`pool` subcommand's cross-ticker backtest when no explicit ticker list is
given. The pattern definition (gap %, RSI band, volume multiple) is pure
math -- it doesn't care which ticker it's evaluated against -- so pooling
matches across many names gives a statistically meaningful sample even when
any single name (especially a thin, obscure daily gainer) has too little of
its own history to say much on its own.

This is not exhaustive and isn't meant to be a precise index replica; it's a
reasonable cross-section of well-known, highly liquid names across sectors.
"""

DEFAULT_UNIVERSE = [
    # Technology
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "CRM",
    "ADBE", "CSCO", "INTC", "AMD", "QCOM", "TXN", "IBM", "NOW", "INTU",
    "AMAT", "MU",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SCHW", "USB",
    # Healthcare
    "UNH", "JNJ", "LLY", "PFE", "ABBV", "MRK", "TMO", "ABT", "DHR", "BMY",
    # Consumer
    "WMT", "PG", "KO", "PEP", "COST", "MCD", "NKE", "SBUX", "HD", "LOW", "TGT",
    # Industrials
    "GE", "HON", "CAT", "BA", "UPS", "LMT", "RTX", "MMM", "DE",
    # Energy
    "XOM", "CVX", "COP", "SLB",
    # Communication / media
    "DIS", "CMCSA", "NFLX", "T", "VZ",
    # Staples
    "PM", "MO", "CL",
]
