# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.0] - 2026-08-20

### ✨ Added
- Client-side rate limiting (token bucket matching FRED's 120 requests/minute per-key quota)
- TTL+LRU response cache and coalescing of identical in-flight requests
- Retries with exponential backoff and jitter for 429/5xx/network failures, honoring `Retry-After`
- Request timeouts via `AbortController`
- HTTP session limits (`MCP_MAX_SESSIONS`) and idle-session reaping (`MCP_SESSION_TTL_MS`)
- `GET /healthz` endpoint with session, cache, and uptime statistics
- Graceful shutdown on SIGTERM as well as SIGINT
- Leveled stderr logging via `LOG_LEVEL`
- All tunables configurable through environment variables (see README)

### 🔧 Changed
- A missing `FRED_API_KEY` now fails with a clear configuration error instead of sending a placeholder key that FRED rejected with an opaque 400
- Unknown HTTP session IDs return 404 instead of 400
- Tools are registered through `registerTool` (SDK 1.25 deprecated `server.tool`)
- `fred_get_series` fetches observations and metadata concurrently
- `fred_browse` accepts `filter_variable` and `filter_value` for `category_series`

### 🐛 Fixed
- Windows build and entrypoint detection (#29, thanks @zhowzeng)

## [1.1.0] - 2026-01-25

_Not published to npm; included in 1.2.0._

### ✨ Added
- Streamable HTTP transport (`--http` flag or `TRANSPORT=http`)
- MCP conformance test suite and CI workflow
- Documentation site (Mintlify)

### 🔧 Changed
- Updated `@modelcontextprotocol/sdk` to 1.26, added `express`
- Docker image pinned to Node 22 with HTTP transport support

## [1.0.0] - 2025-08-15

### 🚨 Breaking Changes
- Complete API redesign - replaced 20+ individual series tools with 3 universal tools
- Removed all hardcoded series-specific tools (CPIAUCSL, GDP, UNRATE, etc.)
- Changed from Apache-2.0 to AGPL-3.0 license

### ✨ Added
- **`fred_browse`** tool - Browse FRED's complete catalog through categories, releases, and sources
- **`fred_search`** tool - Search for any series by keywords, tags, or filters
- **`fred_get_series`** tool - Retrieve data for any of the 800,000+ FRED series
- Support for data transformations (percent change, year-over-year, log, etc.)
- Support for frequency conversions (daily to monthly, quarterly to annual, etc.)
- Pagination support for browsing large result sets
- Comprehensive GitHub Actions workflows for CI/CD
- Automated npm and GitHub Packages publishing on release
- Test coverage for new API structure

### 🔄 Changed
- Simplified codebase architecture (862 insertions, 1062 deletions)
- Updated documentation to reflect new universal access approach
- Enhanced README with detailed tool documentation and examples
- Switched to AGPL-3.0 license with commercial licensing options

### 🗑️ Removed
- All individual series tools (RRPONTSYD, CPIAUCSL, MORTGAGE30US, etc.)
- Legacy client and registry modules
- Hardcoded series registry limiting access to predefined series

### 🔧 Fixed
- GitHub Actions workflows now properly use pnpm
- Test suite updated to match new API structure
- Package.json dependencies cleaned up

## [0.4.1] - 2025-05-19

### Added
- Initial release with hardcoded series tools
- Support for specific FRED series like GDP, UNRATE, CPIAUCSL
- Basic MCP server implementation
- Test coverage setup

## [0.3.0] - 2025-05-12

### Added
- Additional economic indicators
- Docker support
- Basic documentation

## [0.2.0] - 2025-05-05

### Added
- Core FRED API integration
- Initial series support

## [0.1.0] - 2025-04-28

### Added
- Initial project setup
- Basic MCP server structure

[1.0.0]: https://github.com/stefanoamorelli/fred-mcp-server/compare/v0.4.1...v1.0.0
[0.4.1]: https://github.com/stefanoamorelli/fred-mcp-server/compare/v0.3.0...v0.4.1
[0.3.0]: https://github.com/stefanoamorelli/fred-mcp-server/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/stefanoamorelli/fred-mcp-server/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/stefanoamorelli/fred-mcp-server/releases/tag/v0.1.0