# News and Market Context

Load this reference before using an exposed `news_search`, `social_search` or `market_compare`. It does not impose a prose length requirement.

## News discovery

When exposed, use `news_search` to discover dated publisher articles and then `web_fetch` selected original URLs before factual or numeric claims. A NewsAPI snippet is discovery, not a fetched page. Keep publisher, URL, language, publication time and retrieval time; repeated outlets may share one origin. The opening prefetch is already captured: reuse its evidence before spending another query.

## Social and cross-platform market context

`social_search`, when enabled, returns attributed discussion and opinion. `market_compare` returns source-aware topic candidates from additional venues. Preserve provider/native identity, quote basis, units, rules and horizon; similar titles do not establish equivalent contracts or executable arbitrage. These records are context only: never convert tone to event probability or participation counts to trading volume, and never treat them as automatic forecast anchors or settlement evidence.

## Availability and replay

Read availability status before interpreting an empty list: unavailable, forbidden, rate-limited, partial, disabled and verified empty differ. Do not retry a failed provider repeatedly. Once the research generation is sealed, use stored captures and citations; do not acquire replacement evidence on resume. If these tools are absent, continue with the existing web/data tools.
