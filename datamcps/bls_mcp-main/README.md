# BLS MCP

An MCP (Model Context Protocol) server that wraps the [Bureau of Labor Statistics Public Data API v2](https://www.bls.gov/developers/), letting Claude query U.S. labor statistics — employment, unemployment, wages, CPI, and more — directly from a conversation.

> **Disclaimer:** This project is an independent, unofficial tool and is not affiliated with, endorsed by, or associated with the U.S. Bureau of Labor Statistics, the U.S. Department of Labor, or any government agency. All data is fetched in real time from the publicly available `api.bls.gov` API. The accuracy, completeness, and timeliness of the data are the sole responsibility of that API. This tool is provided for informational and research purposes only. Nothing returned by this server constitutes legal, financial, economic, or policy advice. Use responsibly and in accordance with applicable laws.

> **API status:** The BLS Public Data API is at v0.0.2-beta and subject to change without notice. Tool behaviour may change as the upstream API evolves.

## Available Tools

| Tool | Endpoint | Description |
|------|----------|-------------|
| `get_single_series` | `GET /timeseries/data/{id}` | Retrieve data for a single time series for the past three years |
| `get_latest_series` | `GET /timeseries/data/{id}?latest=true` | Retrieve the most recent data point for a series |
| `get_multiple_series` | `POST /timeseries/data/` | Retrieve data for one or more series with optional parameters |
| `get_popular_series` | `GET /timeseries/popular` | List the 25 most popular BLS series, optionally filtered by survey |
| `get_all_surveys` | `GET /surveys` | List all BLS surveys with abbreviations and names |
| `get_survey` | `GET /surveys/{abbr}` | Retrieve metadata for a single BLS survey |

## Tool Parameters

### get_single_series / get_latest_series

| Parameter | Type | Description |
|-----------|------|-------------|
| `series_id` | string | BLS series ID (uppercase, digits, `_`, `-`, `#`) |

### get_multiple_series

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `series_ids` | string[] | Yes | Array of BLS series IDs (1–50) |
| `start_year` | string | No | Start year in `YYYY` format |
| `end_year` | string | No | End year in `YYYY` format |
| `catalog` | boolean | No | Include catalog data (requires API key) |
| `calculations` | boolean | No | Include net/percent change calculations (requires API key) |
| `annual_average` | boolean | No | Include annual averages (requires API key) |
| `aspects` | boolean | No | Include aspect data (requires API key) |

### get_popular_series

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `survey` | string | No | 2-letter survey abbreviation (e.g. `LA`, `CU`, `CE`) |

### get_survey

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `survey_abbreviation` | string | Yes | 2-letter survey abbreviation (e.g. `TU`, `CU`, `LA`) |

### get_all_surveys — no parameters.

## Series ID Format

BLS series IDs may contain uppercase letters, digits, underscores (`_`), dashes (`-`), and hashes (`#`). Lowercase letters and other special characters are not accepted. Examples:

- `LAUCN040010000000005` — Local Area Unemployment
- `CUUR0000SA0` — Consumer Price Index
- `CES0000000001` — Current Employment Statistics
- `OEUN000000056--5747213213` — Occupational Employment

Use `get_popular_series` or `get_all_surveys` to discover valid series IDs and survey abbreviations.

## Registered vs. Unregistered Access

The BLS API works without an API key, but with reduced limits:

| | Unregistered | Registered |
|---|---|---|
| Daily query limit | 25 | 500 |
| Series per query | 25 | 50 |
| Year range | 10 years | 20 years |
| Optional parameters | No | catalog, calculations, annual averages, aspects |

Register for a free API key at [https://data.bls.gov/registrationEngine/](https://data.bls.gov/registrationEngine/) and pass it via the `BLS_API_KEY` environment variable.

## Prerequisites

- **Node.js** 18 or later
- **npm** 9 or later
- **Claude Desktop** (or any MCP-compatible client)

## Installation

```bash
git clone https://github.com/larasrinath/bls_mcp.git
cd bls_mcp
npm install
npm run build
```

The compiled server lands in `./dist/index.js`.

## Claude Desktop Configuration

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

**Linux:** `~/.config/Claude/claude_desktop_config.json`

Add the following block (adjust the path to match your machine):

```json
{
  "mcpServers": {
    "bls": {
      "command": "node",
      "args": ["/absolute/path/to/bls_mcp/dist/index.js"],
      "env": {
        "BLS_API_KEY": "your-registration-key-here"
      }
    }
  }
}
```

The `env` block is optional — omit it to use the API without a key (lower rate limits apply).

**macOS/Linux example:**

```
"args": ["/Users/yourname/Projects/bls_mcp/dist/index.js"]
```

**Windows example:**

```
"args": ["C:\\Users\\yourname\\Projects\\bls_mcp\\dist\\index.js"]
```

Restart Claude Desktop after saving. The six BLS tools will appear in the tool picker.

## Bundled Skill

This repo includes a [Claude skill](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/skills) at `skills/bls-query/` that teaches Claude how to map natural language queries (e.g. "What's the current CPI?") to the correct BLS series IDs and tools — without guessing.

The skill includes a series catalog covering CPI, unemployment, employment, JOLTS, PPI, wages, productivity, and more (~100 common series IDs).

**To install for Claude Code:** Copy the `skills/bls-query` folder into `~/.claude/skills/`.

**To install for Claude.ai:** Upload the `skills/bls-query` folder via Settings > Capabilities > Skills.

## Example Prompts

- What is the current unemployment rate? (use `get_popular_series` to find the series, then `get_latest_series`)
- Show me CPI data for the last 3 years using series CUUR0000SA0.
- Compare employment data for series CES0000000001 and CES3000000001 from 2020 to 2024.
- What BLS surveys are available?
- Tell me about the American Time Use survey.
- What are the most popular Local Area Unemployment series?

## Development

```bash
# Run directly without building (uses tsx, included in devDependencies)
npm run dev

# Rebuild after changes
npm run build
```

## Project Structure

```
bls_mcp/
├── src/
│   ├── index.ts          # MCP server entry point
│   ├── client.ts         # Typed BLS API client (axios)
│   └── tools/
│       ├── series.ts     # get_single_series, get_latest_series, get_multiple_series
│       └── surveys.ts    # get_popular_series, get_all_surveys, get_survey
├── skills/
│   └── bls-query/
│       ├── SKILL.md      # Query workflow and tool selection guide
│       └── references/
│           └── series-catalog.md  # ~100 common series ID mappings
├── package.json
├── tsconfig.json
├── LICENSE
└── README.md
```

## Rate Limits

The BLS API enforces daily query limits (25 for unregistered, 500 for registered users). If you hit a rate limit, the server surfaces a clear error message rather than crashing silently. Register for a free API key to increase your limits.

## License

MIT — see [LICENSE](LICENSE).
