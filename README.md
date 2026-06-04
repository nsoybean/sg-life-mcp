# sg-life-mcp

A Model Context Protocol (MCP) server that answers everyday Singapore life decisions using real-time data from [data.gov.sg](https://data.gov.sg).

Instead of returning raw API data, it combines multiple signals into a single plain-English verdict.

```
"Should I jog now in Bedok?"

verdict: GO
area: Bedok (region: east)
summary: Conditions look good for a jog!

signals:
  psi: 42
  pm25: 18
  uv: 3
  rainfall_stations_wet: 0
  forecast_2hr: Partly Cloudy
```

## Tools

### `should_i_jog_now(area)`

Combines 5 real-time signals to decide if it's safe to run outside:

| Signal       | Source       | Blocks if             |
| ------------ | ------------ | --------------------- |
| PSI 24hr     | NEA          | > 100                 |
| PM2.5 1hr    | NEA          | > 55 µg/m³            |
| UV index     | NEA          | ≥ 11 (extreme)        |
| Rainfall     | NEA stations | rain detected         |
| 2hr forecast | NEA          | thundery / heavy rain |

Returns `GO`, `CAUTION`, or `SKIP` with a reason.

## Setup

**Requirements:** Python 3.10+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/nsoybean/sg-life-mcp
cd sg-life-mcp
uv venv && source .venv/bin/activate
uv pip install mcp httpx
```

**Test without Claude Desktop:**

```bash
python server.py --test
```

**Connect to Claude Desktop** — add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sg-life": {
      "command": "/full/path/to/.venv/bin/python",
      "args": ["/full/path/to/server.py"]
    }
  }
}
```

Fully quit and reopen Claude Desktop after editing the config. Ask: _"Should I jog now in Tampines?"_

**View logs:**

```bash
tail -f ~/Library/Logs/Claude/mcp-server-sg-life.log
```

## Data sources

All data from [data.gov.sg](https://data.gov.sg) real-time APIs — no API key required.

- NEA PSI: `api-open.data.gov.sg/v2/real-time/api/psi`
- NEA PM2.5: `api-open.data.gov.sg/v2/real-time/api/pm25`
- NEA UV index: `api-open.data.gov.sg/v2/real-time/api/uv-index`
- NEA Rainfall: `api-open.data.gov.sg/v2/real-time/api/rainfall`
- NEA 2hr forecast: `api-open.data.gov.sg/v2/real-time/api/two-hr-forecast`

## Roadmap

- [ ] `best_run_window_today` — scan today's forecast and rank time slots
- [ ] `morning_brief` — all signals in a 5-line daily digest
- [ ] `safe_for_kids_outside` — PSI + dengue clusters + UV
- [ ] `hang_laundry_outside` — rainfall + wind + 4-day forecast
