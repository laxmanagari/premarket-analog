# premarket-analog

Two related tools in one CLI:

- **`backtest`** — backtests a premarket gap-up analog pattern against a
  ticker's (and optionally peers') full daily price history, and reports how
  the pattern has historically resolved at +1, +5, and +20 trading days.
- **`screen`** — checks a candidate list *right now*, live, ahead of today's
  close: which of them currently have the gap % and prior-day RSI the pattern
  calls for.

The intended morning flow is `screen` first (which candidates match live
today) piped into `backtest` (how has this exact setup played out historically
for those tickers).

## Install

```bash
cd premarket-analog
pip install -e .
```

## Data source

Set `ALPHAVANTAGE_API_KEY` (or pass `--api-key`) to pull daily adjusted OHLCV
from Alpha Vantage's `TIME_SERIES_DAILY_ADJUSTED` endpoint. If no key is set,
or Alpha Vantage returns an error/rate-limit/premium-only response, the tool
automatically falls back to `yfinance`. `screen`'s live quote always comes
from `yfinance` directly (Alpha Vantage isn't used for that step) unless
`--quotes-file` is given (see below).

### Running where outbound network access is restricted

Both subcommands accept `--data-dir DIR`: instead of any network call, price
history is loaded from `{DIR}/{TICKER}.json` — a file containing Alpha
Vantage's raw `TIME_SERIES_DAILY` or `TIME_SERIES_DAILY_ADJUSTED` JSON
response for that ticker. `screen` additionally accepts `--quotes-file PATH`,
a JSON manifest of pre-fetched live quotes:
`{"AAPL": {"price": 190.5, "previous_close": 188.0}, ...}`.

This exists for sandboxed environments (e.g. a Claude Code cloud routine) that
can reach Alpha Vantage through an MCP connector but can't reach the open
internet directly (yfinance, or Alpha Vantage's own REST API) — something
else fetches the data via the MCP tools and saves it to these files first,
and this CLI does the RSI/pattern/backtest math against them with zero
outbound calls of its own. Alpha Vantage's free tier only exposes `compact`
history (~100 trading days) through most MCP-connected accounts, so a
`--data-dir`-driven `backtest` will usually have a short lookback window —
expect the thin-sample warning to fire routinely there; it's telling the
truth about the data available, not misbehaving.

## Usage

`backtest` is also the default subcommand, so `premarket-analog AAPL` and
`premarket-analog backtest AAPL` are equivalent.

Single ticker with peer comparison:

```bash
premarket-analog backtest AAPL --peers MSFT,GOOGL,AMZN --format markdown
```

Piped from a screener (batch mode — no `--peers`, tickers come from stdin):

```bash
printf "AAPL\nMSFT\nGOOGL\nAMZN\nNVDA\n" | premarket-analog backtest --format json --output /tmp/morning_scan.json
```

This is the shape an automated morning job would use: a screener emits its
candidate list to stdout, it's piped straight in, and JSON comes out ready to
be parsed or archived.

### Live screen

Check which of a candidate list currently matches the pattern, before today's
close resolves anything:

```bash
premarket-analog screen AAPL MSFT NVDA
# or piped in the same way as backtest:
printf "AAPL\nMSFT\nNVDA\n" | premarket-analog screen --format json
```

`screen` only checks gap % and prior-day RSI — see **Notes / caveats** below
for why volume isn't part of the live check. Chain the two together to go
from "what's live right now" to "how has that setup historically resolved":

```bash
premarket-analog screen AAPL MSFT NVDA --format json \
  | jq -r '.matched_tickers[]' \
  | premarket-analog backtest --format markdown
```

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

- In `backtest`, volume confirmation uses the signal day's *full* daily volume
  vs. its trailing average — a proxy, since daily bars don't expose true
  premarket-only volume.
- `screen` deliberately does not check volume at all. Free live-quote data
  (`yfinance`'s `fast_info`) only exposes the most recently *completed*
  session's volume, not volume accumulated so far in the current session —
  during premarket it would just restate yesterday's already-known volume, so
  a "volume ratio" computed from it would be misleading rather than merely
  imprecise. `screen` checks gap % and prior-day RSI only, and says so
  explicitly in its output.
- Occurrence counts below ~10 per horizon are flagged explicitly in the
  `backtest` report as statistically thin.
- Every `backtest` report states the exact date range of history scanned,
  since a pattern that worked in one regime (e.g. 2021-2023) is not guaranteed
  to hold in another.
