# premarket-analog

Backtests a premarket gap-up analog pattern against a ticker's (and optionally
peers') full daily price history, and reports how the pattern has historically
resolved at +1, +5, and +20 trading days.

## Install

```bash
cd premarket-analog
pip install -e .
```

## Data source

Set `ALPHAVANTAGE_API_KEY` (or pass `--api-key`) to pull daily adjusted OHLCV
from Alpha Vantage's `TIME_SERIES_DAILY_ADJUSTED` endpoint. If no key is set,
or Alpha Vantage returns an error/rate-limit/premium-only response, the tool
automatically falls back to `yfinance`.

## Usage

Single ticker with peer comparison:

```bash
premarket-analog AAPL --peers MSFT,GOOGL,AMZN --format markdown
```

Piped from a screener (batch mode — no `--peers`, tickers come from stdin):

```bash
printf "AAPL\nMSFT\nGOOGL\nAMZN\nNVDA\n" | premarket-analog --format json --output /tmp/morning_scan.json
```

This is the shape an automated morning job would use: a screener emits its
candidate list to stdout, it's piped straight in, and JSON comes out ready to
be parsed or archived.

### Custom pattern

Override any of the default thresholds:

```bash
premarket-analog AAPL --gap-pct-min 3 --rsi-min 45 --rsi-max 65 --volume-multiple 2
```

or supply a JSON file via `--pattern-config`:

```json
{
  "gap_pct_min": 3.0,
  "rsi_range": [45, 65],
  "volume_multiple": 2.0,
  "volume_window": 20
}
```

### Default pattern definition

- Gap up ≥ 2% (day's open vs. prior close)
- Prior-day RSI(14) in [50, 70] (momentum without being deeply overbought)
- Day's volume ≥ 1.5× its trailing 20-day average

## Notes / caveats

- Volume confirmation uses the signal day's *full* daily volume vs. its
  trailing average — a proxy, since daily bars don't expose true premarket-only
  volume.
- Occurrence counts below ~10 per horizon are flagged explicitly in the report
  as statistically thin.
- Every report states the exact date range of history scanned, since a pattern
  that worked in one regime (e.g. 2021-2023) is not guaranteed to hold in
  another.
