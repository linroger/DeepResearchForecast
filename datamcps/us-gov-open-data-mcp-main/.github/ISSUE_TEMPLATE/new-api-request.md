---
name: "New API Request"
about: Request a new U.S. government data API to be added as a module
title: "[API]: "
labels: ["new-api"]
assignees: []
---

## API Overview

**Agency / Data Source:**
<!-- e.g. Bureau of Labor Statistics, NOAA, EPA -->

**API Name:**
<!-- e.g. Current Population Survey, Climate Data Online -->

**API Documentation URL:**
<!-- Link to the official API docs -->

**Base URL:**
<!-- e.g. https://api.example.gov/v1 -->

## Authentication

<!-- Check one -->
- [ ] No authentication required
- [ ] API key (query parameter)
- [ ] API key (header)
- [ ] API key (POST body)
- [ ] OAuth / Bearer token
- [ ] Other (describe below)

**Key signup URL (if applicable):**
<!-- e.g. https://api.example.gov/signup -->

**Env var name suggestion:**
<!-- e.g. EXAMPLE_API_KEY -->

## Proposed Tools

<!-- List 2–6 MCP tools this module should expose. Each tool should map to a useful query. -->

| Tool Name | Description | Key Parameters |
|-----------|-------------|----------------|
| `example_search` | Search for records by keyword | `query`, `year`, `state` |
| `example_detail` | Get details for a specific record | `id` |

## Data Description

**What data does this API provide?**
<!-- Describe the datasets, what they measure, and why they're useful -->

**Update frequency:**
<!-- e.g. Daily, Weekly, Monthly, Quarterly, Annually -->

**Data format:**
<!-- e.g. JSON, XML, CSV -->

## Cross-Referencing Potential

<!-- How does this data connect to APIs already in the project? Check all that apply. -->

- [ ] Economic data (FRED, BEA, BLS)
- [ ] Congressional / legislative (Congress, GovInfo)
- [ ] Spending / budget (USAspending, Treasury)
- [ ] Health (CDC, CMS, FDA)
- [ ] Demographics (Census)
- [ ] Energy / environment (EIA, EPA, NOAA, NREL)
- [ ] Education (NAEP, College Scorecard)
- [ ] Financial regulation (FDIC, CFPB, SEC, FEC)
- [ ] Other: <!-- describe -->

## Additional Context

<!-- Any other information: example API calls, rate limits, known quirks, related existing modules, etc. -->
