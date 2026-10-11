# Testing FRED MCP Server

## Using MCP Inspector

The MCP Inspector is running at:
http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=7cd01fa7d661894a5c33f873f03fa8d924a27294fdb0d24d6052ad6b750a893b

## Example Test Queries

### 1. Browse Categories
Tool: `fred_browse`
```json
{
  "browse_type": "categories",
  "limit": 10
}
```

### 2. Search for Interest Rates
Tool: `fred_search`
```json
{
  "search_text": "interest rate",
  "limit": 5,
  "order_by": "popularity",
  "sort_order": "desc"
}
```

### 3. Get GDP Data
Tool: `fred_get_series`
```json
{
  "series_id": "GDP",
  "observation_start": "2023-01-01",
  "observation_end": "2024-12-31"
}
```

### 4. Get Unemployment Rate with Transformations
Tool: `fred_get_series`
```json
{
  "series_id": "UNRATE",
  "units": "pch",
  "observation_start": "2024-01-01"
}
```

### 5. Browse Releases
Tool: `fred_browse`
```json
{
  "browse_type": "releases",
  "limit": 10,
  "order_by": "name"
}
```

### 6. Get All Series in a Category
First, browse to find a category ID, then:
Tool: `fred_browse`
```json
{
  "browse_type": "category_series",
  "category_id": 32991,
  "limit": 20
}
```

### 7. Search by Tags
Tool: `fred_search`
```json
{
  "tag_names": "inflation,cpi",
  "limit": 10
}
```

### 8. Get CPI with Monthly Percent Change
Tool: `fred_get_series`
```json
{
  "series_id": "CPIAUCSL",
  "units": "pc1",
  "observation_start": "2024-01-01"
}
```

## Common Series IDs to Test

- **GDP** - Gross Domestic Product
- **UNRATE** - Unemployment Rate  
- **CPIAUCSL** - Consumer Price Index
- **DFF** - Federal Funds Rate
- **DEXUSEU** - US/Euro Exchange Rate
- **HOUST** - Housing Starts
- **PAYEMS** - Nonfarm Payrolls
- **M2SL** - M2 Money Supply
- **DGS10** - 10-Year Treasury Rate
- **MORTGAGE30US** - 30-Year Mortgage Rate

## Data Transformation Options (units parameter)

- **lin** - Levels (no transformation)
- **chg** - Change from previous period
- **ch1** - Change from year ago
- **pch** - Percent change
- **pc1** - Percent change from year ago
- **pca** - Compounded annual rate of change
- **cch** - Continuously compounded rate of change
- **log** - Natural log

## Frequency Options

- **d** - Daily
- **w** - Weekly
- **m** - Monthly
- **q** - Quarterly
- **a** - Annual