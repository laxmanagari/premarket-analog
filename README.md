# premarket-analog

Three related tools in one CLI:

- **`backtest`** — backtests a premarket gap-up analog pattern against a
  ticker's (and optionally peers') full daily price history, and reports how
  the pattern has historically resolved at +1, +5, and +20 trading days.
- **`screen`** — checks a candidate list *right now*, live, ahead of today's
  close: which of them currently have the gap % and prior-day RSI the pattern
  calls for.
- **`pool`** — backtests the pattern across *many* tickers and pools every
  match into one combined distribution. The pattern (gap %, RSI band, volume
  multiple) is pure math, not tied to any one stock, so this trades
  ticker-specificity for sample size — useful when a candidate (e.g. an
  obscure daily gainer) has too little of its own history to say much on its
  own; see **Notes / caveats** for what pooling does and doesn't tell you.
- **`catalyst`** — fetches raw catalyst material for a ticker: the 2-3 most
  relevant recent news articles (Alpha Vantage `NEWS_SENTIMENT`), falling
  back to an earnings-date check (`EARNINGS_CALENDAR`) if nothing relevant
  turns up. This is structured source data only, not a synthesized
  narrative — see **Catalyst context** below for why. Pair with `--catalyst`
  on `backtest` to fold this into that report as its own labeled section per
  ticker, before the technical/pattern data.

There's also a **`rate-guard`** subcommand: not part of the analysis itself,
it's a sliding-window rate-limit primitive an external caller (e.g. a
cloud-routine agent making Alpha Vantage calls of its own via MCP tools,
outside this CLI's own REST path) can shell out to before each call — see
**Rate limiting** below.

The intended morning flow is `screen` first (which candidates match live
today) piped into `backtest` (how has this exact setup played out historically
for those specific tickers) — and `pool` as a separate, broader check on how
the setup resolves in general, independent of which ticker triggered it.

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

This is the **only** Alpha Vantage call the tool ever makes per ticker — RSI(14),
SMA(50), SMA(200), and the rolling volume average are all computed locally in
pandas from that single response's close/volume series (see `indicators.py`);
there's no separate call to Alpha Vantage's own RSI/SMA technical-indicator
endpoints. Every run prints the total count of real Alpha Vantage requests
made to stderr, e.g. `Alpha Vantage API calls this run: 2`, so this stays easy
to verify — it should always equal the number of tickers fetched via the REST
path (0 if running on `--data-dir` or the `yfinance` fallback).

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

### Rate limiting

Alpha Vantage's real free-tier limit is **5 calls/minute, 25 calls/day**.
Every direct REST call this CLI makes (`TIME_SERIES_DAILY(_ADJUSTED)`,
`NEWS_SENTIMENT`, `EARNINGS_CALENDAR`) passes through a shared sliding-window
guard first: before making a call, it checks whether doing so would exceed 5
calls in the trailing 60 seconds, and if so, sleeps exactly until the oldest
call in that window ages out (not a blind fixed delay). This is automatic —
nothing to configure for normal use of `backtest`/`screen`/`pool`/`catalyst`.

For an external caller that makes Alpha Vantage calls of its own outside this
CLI's Python — e.g. a cloud-routine agent using MCP tools, since a sandboxed
environment usually can't reach Alpha Vantage's REST API directly (see
above) — the same algorithm is available as a subcommand:

```bash
premarket-analog rate-guard --state-file /tmp/av_data/call_log.json
# then make your own Alpha Vantage call
```

Call it once immediately before each external Alpha Vantage call, always with
the same `--state-file`; it tracks recent call timestamps in that file and
blocks only when needed. Every run also prints its own total call count to
stderr (`Alpha Vantage API calls this run: N`) so actual usage against the
25/day cap is easy to see.

### Catalyst context

`premarket-analog catalyst TICKER [TICKER2 ...]` fetches what's likely
driving a ticker's move: the top (up to 3) relevant recent articles via Alpha
Vantage's `NEWS_SENTIMENT` (filtered by relevance, sorted, most relevant
first), or — if nothing sufficiently relevant turns up — a check of
`EARNINGS_CALENDAR` for whether today is that ticker's reported earnings
date. If neither turns up anything, it says "no clear catalyst found" rather
than guessing.

This only fetches and structures source material (title, source, url,
relevance) — it does **not** write a narrative. Turning "these are the 2-3
most relevant articles" into an actual 2-3 sentence plain-language paraphrase
of what's driving the move is a language task, not something deterministic
code can do; that step is left to whoever consumes this output (a person
reading it, or an agent orchestrating a run), and every catalyst section
says so explicitly rather than silently quoting Alpha Vantage's article
summaries as if they were a synthesized take.

Add `--catalyst` to `backtest` to fold this into that report instead of
running it standalone: each ticker gets its own `### Catalyst` section,
using the same fetch, placed before that ticker's technical/pattern-analog
data. It renders even if the technical fetch for that ticker fails (or vice
versa) — they're independent data sources, so one failing doesn't hide the
other's result.

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

Markdown reports (`backtest` and `pool`) lead with a color-coded **Summary**
table before the detailed per-horizon breakdown: 🟢/🟡/🔴 for a solid, mixed,
or weak/negative historical read, plus a compact win-rate bar. A thin sample
is always ⚪, regardless of how good the raw numbers look — too few
occurrences to call it a real edge, not something worth painting green. JSON
output is unaffected (still just the numbers); the color coding is a markdown
presentation layer only.

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

### Pooled cross-ticker backtest

Pool matches across many tickers into one combined distribution, instead of
per-ticker stats:

```bash
# Explicit universe
premarket-analog pool AAPL MSFT GOOGL AMZN NVDA --format markdown

# Piped, same as backtest/screen
printf "AAPL\nMSFT\nGOOGL\n" | premarket-analog pool --format json

# No tickers given and nothing piped: falls back to a built-in curated
# universe of ~80 liquid large/mid-cap tickers
premarket-analog pool --format markdown
```

Each ticker still gets the exact same per-ticker scan as `backtest` (same
`compute_indicators`/`scan`/`forward_returns`); `pool` just merges every
ticker's matches into one set of per-horizon stats instead of reporting them
separately, and shows how many different tickers contributed to each
horizon's count.

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
- `pool`'s bigger sample size is a trade against ticker-specificity: it
  answers "how does this exact setup resolve, averaged across many different
  stocks," not "how does *this* stock behave." A large pooled sample also
  mixes different sectors, volatility regimes, and market conditions across
  the scanned history — it doesn't mean the edge transfers uniformly to any
  one ticker today. The report says this explicitly and lists how many
  distinct tickers contributed to each horizon's count.
- `catalyst`'s coverage depends entirely on Alpha Vantage's own news indexing
  — thin or delayed for smaller/obscure tickers (exactly the ones a daily
  gainers list tends to surface). "No clear catalyst found" means nothing
  sufficiently relevant was indexed at the time of the call, not that
  nothing happened.
