/**
 * MCP Tool Definitions for FRED API
 *
 * Comprehensive tools for accessing any FRED data
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { searchSeries } from "./search.js";
import { getSeriesData } from "./series.js";
import { browseCategories, getCategorySeries, browseReleases, getReleaseSeries, browseSources } from "./browse.js";
import { logger } from "../common/logger.js";

/**
 * Schema for FRED search tool
 */
const SEARCH_SCHEMA = {
  search_text: z.string().optional().describe("Text to search for in series titles and descriptions"),
  search_type: z.enum(["full_text", "series_id"]).optional().describe("Type of search to perform"),
  tag_names: z.string().optional().describe("Comma-separated list of tag names to filter by"),
  exclude_tag_names: z.string().optional().describe("Comma-separated list of tag names to exclude"),
  limit: z.number().min(1).max(1000).optional().default(25).describe("Maximum number of results to return"),
  offset: z.number().min(0).optional().default(0).describe("Number of results to skip for pagination"),
  order_by: z.enum([
    "search_rank", "series_id", "title", "units", "frequency",
    "seasonal_adjustment", "realtime_start", "realtime_end",
    "last_updated", "observation_start", "observation_end", "popularity"
  ]).optional().describe("Field to order results by"),
  sort_order: z.enum(["asc", "desc"]).optional().describe("Sort order for results"),
  filter_variable: z.enum(["frequency", "units", "seasonal_adjustment"]).optional().describe("Variable to filter by"),
  filter_value: z.string().optional().describe("Value to filter the variable by")
};

/**
 * Schema for FRED series data tool
 */
const SERIES_DATA_SCHEMA = {
  series_id: z.string().describe("The FRED series ID to retrieve data for (e.g., 'GDP', 'UNRATE', 'CPIAUCSL')"),
  observation_start: z.string().optional().describe("Start date for observations in YYYY-MM-DD format"),
  observation_end: z.string().optional().describe("End date for observations in YYYY-MM-DD format"),
  limit: z.number().min(1).max(100000).optional().describe("Maximum number of observations to return"),
  offset: z.number().min(0).optional().describe("Number of observations to skip"),
  sort_order: z.enum(["asc", "desc"]).optional().describe("Sort order of observations by date"),
  units: z.enum([
    "lin", "chg", "ch1", "pch", "pc1", "pca", "cch", "cca", "log"
  ]).optional().describe("Data transformation: lin=levels, chg=change, pch=percent change, log=natural log"),
  frequency: z.enum([
    "d", "w", "bw", "m", "q", "sa", "a",
    "wef", "weth", "wew", "wetu", "wem", "wesu", "wesa", "bwew", "bwem"
  ]).optional().describe("Frequency aggregation: d=daily, w=weekly, m=monthly, q=quarterly, a=annual"),
  aggregation_method: z.enum(["avg", "sum", "eop"]).optional().describe("Aggregation method: avg=average, sum=sum, eop=end of period"),
  output_type: z.number().min(1).max(4).optional().describe("Output format: 1=observations, 2=observations by vintage, 3=observations by release, 4=initial release only"),
  vintage_dates: z.string().optional().describe("Vintage date or dates in YYYY-MM-DD format")
};

/**
 * Schema for FRED browse tool
 */
const BROWSE_SCHEMA = {
  browse_type: z.enum(["categories", "releases", "sources", "category_series", "release_series"]).describe("Type of browsing to perform"),
  category_id: z.number().optional().describe("Category ID (for categories or category_series)"),
  release_id: z.number().optional().describe("Release ID (for release_series)"),
  limit: z.number().min(1).max(1000).optional().default(50).describe("Maximum number of results"),
  offset: z.number().min(0).optional().default(0).describe("Number of results to skip"),
  order_by: z.string().optional().describe("Field to order by"),
  sort_order: z.enum(["asc", "desc"]).optional().describe("Sort order"),
  filter_variable: z.enum(["frequency", "units", "seasonal_adjustment"]).optional().describe("Variable to filter by (category_series only)"),
  filter_value: z.string().optional().describe("Value to filter the variable by (category_series only)")
};

type BrowseInput = z.infer<z.ZodObject<typeof BROWSE_SCHEMA>>;
type SearchInput = z.infer<z.ZodObject<typeof SEARCH_SCHEMA>>;
type SeriesInput = z.infer<z.ZodObject<typeof SERIES_DATA_SCHEMA>>;

/**
 * Registers the FRED tools with the MCP server
 */
export function registerFREDTools(server: McpServer) {
  // Register browse tool for comprehensive navigation
  server.registerTool(
    "fred_browse",
    {
      title: "Browse FRED catalog",
      description: "Browse FRED's complete catalog through categories, releases, or sources. Use browse_type='categories' to explore the category tree, 'releases' for data releases, 'sources' for data sources, 'category_series' to get all series in a category, or 'release_series' to get all series in a release.",
      inputSchema: BROWSE_SCHEMA
    },
    async (input: BrowseInput) => {
      logger.debug(`fred_browse called with params: ${JSON.stringify(input)}`);

      switch (input.browse_type) {
        case "categories":
          return await browseCategories(input.category_id);
        case "category_series":
          if (!input.category_id) {
            throw new Error("category_id is required for category_series");
          }
          return await getCategorySeries(input.category_id, {
            limit: input.limit,
            offset: input.offset,
            order_by: input.order_by,
            sort_order: input.sort_order,
            filter_variable: input.filter_variable,
            filter_value: input.filter_value
          });
        case "releases":
          return await browseReleases({
            limit: input.limit,
            offset: input.offset,
            order_by: input.order_by,
            sort_order: input.sort_order
          });
        case "release_series":
          if (!input.release_id) {
            throw new Error("release_id is required for release_series");
          }
          return await getReleaseSeries(input.release_id, {
            limit: input.limit,
            offset: input.offset,
            order_by: input.order_by,
            sort_order: input.sort_order
          });
        case "sources":
          return await browseSources({
            limit: input.limit,
            offset: input.offset,
            order_by: input.order_by,
            sort_order: input.sort_order
          });
        default:
          throw new Error(`Invalid browse_type: ${input.browse_type}`);
      }
    }
  );

  // Register search tool
  server.registerTool(
    "fred_search",
    {
      title: "Search FRED series",
      description: "Search for FRED economic data series by keywords, tags, or filters. Returns matching series with their IDs, titles, and metadata. Use this to find specific series when you know what you're looking for.",
      inputSchema: SEARCH_SCHEMA
    },
    async (input: SearchInput) => {
      logger.debug(`fred_search called with params: ${JSON.stringify(input)}`);
      return await searchSeries(input);
    }
  );

  // Register series data tool
  server.registerTool(
    "fred_get_series",
    {
      title: "Get FRED series data",
      description: "Retrieve data for any FRED series by its ID. Supports data transformations, frequency changes, and date ranges.",
      inputSchema: SERIES_DATA_SCHEMA
    },
    async (input: SeriesInput) => {
      logger.debug(`fred_get_series called with params: ${JSON.stringify(input)}`);
      return await getSeriesData(input);
    }
  );
}
