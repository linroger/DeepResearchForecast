# @pipeworx/bis

BIS (Bank for International Settlements) MCP — central-bank and global-financial
statistics over the BIS SDMX v2 API. No auth.

Part of [Pipeworx](https://pipeworx.io) — an MCP gateway connecting AI agents to 1683+ live data sources.

## Tools

- `bis_credit_gap(country, start_period?, end_period?, limit?)` — credit-to-GDP
  ratio, its long-run HP-filter trend, and the gap between them, per quarter,
  for one country. The gap is the Basel III reference indicator for the
  countercyclical capital buffer. Accepts a country name or ISO alpha-2 code;
  44 economies plus the euro area aggregate (`XM`).
- `list_curated_flows(topic?)` — pre-vetted dataflow refs by topic (rates, fx,
  banking, debt, credit, property, derivatives, prices).
- `search_dataflows(query, limit?)` — keyword search over the full BIS dataflow
  registry; returns `flow_ref`s ready for `fetch_dataset`.
- `fetch_dataset(flow_ref, key?, start_period?, end_period?, limit?)` — tidy
  rows from any BIS dataflow.

## Auth

None. BIS publishes these statistics openly and applies no key or quota.

## Notes on the upstream API

- **`flow_ref` carries a version and the version is not always `1.0`.** BIS
  re-versions dataflows in place (`WS_TC` is `2.0`), and a stale version returns
  an empty result rather than an error. Take refs from `list_curated_flows` or
  `search_dataflows` instead of assuming one.
- **Keys are positional over the flow's own dimensions**, dot-separated — e.g.
  `Q.US...` on `WS_CREDIT_GAP`, whose key is
  `FREQ.BORROWERS_CTY.TC_BORROWERS.TC_LENDERS.CG_DTYPE`. Leave a position empty
  to not filter on it. When a key matches nothing, `fetch_dataset` names the
  flow's actual dimensions back to you.
- **Rows carry both the code and its meaning.** Every coded column arrives with
  a `<COLUMN>_label` companion (`CG_DTYPE: "C"` /
  `CG_DTYPE_label: "Credit-to-GDP gaps (actual-trend)"`), because BIS's coded
  values are opaque on their own.
- The banking and debt-securities flows are multi-megabyte unbounded — pass
  `start_period` / `end_period`.

## Data sources

- API: https://stats.bis.org/api/v2/
- API docs: https://stats.bis.org/api-doc/v2/
- Browse: https://stats.bis.org
- Credit-to-GDP gaps: https://www.bis.org/statistics/c_gaps.htm

## Quick Start

Add to your MCP client (Claude Desktop, Cursor, Windsurf, etc.):

```json
{
  "mcpServers": {
    "bis": {
      "url": "https://gateway.pipeworx.io/bis/mcp"
    }
  }
}
```

### What this endpoint actually serves

`tools/list` at `https://gateway.pipeworx.io/bis/mcp` returns the tools in the table
above **plus the shared Pipeworx meta-tools** — `ask_pipeworx`,
`discover_tools`, `search_within`, `remember`/`recall` and the rest of the
gateway-wide set. So the tool count you see is larger than this table: a
single-pack endpoint currently lists roughly 30 shared tools alongside the
pack's own. The connection's `initialize` response states its exact scope, and
is the authoritative answer for a given day.

This is deliberate, not multiplexing by accident. The meta-tools are what let a
scoped connection answer a question this pack does not cover — via
`ask_pipeworx`, which routes across the whole catalog — without you adding a
second MCP server. There is currently no way to mount a pack endpoint without
them; if the extra schemas cost you more context than the routing is worth,
connect to the full gateway once rather than to several pack endpoints.

Or connect to the full Pipeworx gateway to get every pack's tools listed
directly, instead of just this one's:

```json
{
  "mcpServers": {
    "pipeworx": {
      "url": "https://gateway.pipeworx.io/mcp"
    }
  }
}
```

Both URLs reach the same gateway and the same 1683+ data sources. The
only difference is which pack's tools are listed **directly**; `ask_pipeworx`
reaches all of them from either one.

## No MCP client? Call it over HTTP

```bash
curl -X POST https://gateway.pipeworx.io/v1/tools/bis_list_curated_flows \
  -H 'Content-Type: application/json' \
  -d '{"topic":"rates"}'
```

No account needed for the first calls. Inspect any tool: `GET https://gateway.pipeworx.io/v1/tools/bis_list_curated_flows`. Find one: `POST https://gateway.pipeworx.io/v1/tools/search_packs` with `{"query":"..."}`.

## Standalone (no gateway account)

This package also runs as a local stdio MCP server — no Pipeworx account, no
gateway round-trip:

```json
{
  "mcpServers": {
    "bis": {
      "command": "npx",
      "args": ["-y", "@pipeworx/mcp-bis"]
    }
  }
}
```

Or run it directly to confirm it starts:

```bash
npx -y @pipeworx/mcp-bis
```

It speaks MCP over stdin/stdout and answers `initialize`/`tools/list`/`tools/call`
for **only** this pack's tools — none of the shared meta-tools the gateway
connection above adds. Same source, same tools, no ask_pipeworx routing.

## Using with ask_pipeworx

Instead of calling tools directly, you can ask questions in plain English —
this works on the pack endpoint above as well as on the full gateway:

```
ask_pipeworx({ question: "your question about Bis data" })
```

The gateway picks the right tool and fills the arguments automatically.

## More

- [Docs and guides](https://pipeworx.io/docs)
- [pipeworx.io](https://pipeworx.io)

## License

MIT
