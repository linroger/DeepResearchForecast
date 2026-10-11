import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { Client, BlsApiError } from "../client.js";

function wrapError(error: unknown): { content: { type: "text"; text: string }[] } {
  if (error instanceof BlsApiError) {
    return {
      content: [
        {
          type: "text" as const,
          text: `Error: ${error.message}${error.isRateLimit ? "\nConsider setting BLS_API_KEY for higher rate limits." : ""}`,
        },
      ],
    };
  }
  return {
    content: [{ type: "text" as const, text: `Unexpected error: ${String(error)}` }],
  };
}

const SERIES_ID_PATTERN = /^[A-Z0-9_#-]+$/;

export function registerSeriesTools(server: McpServer, client: Client) {
  server.tool(
    "get_single_series",
    "Retrieve data for a single BLS time series for the past three years. " +
      "Provide a valid BLS series ID (uppercase letters, numbers, underscores, dashes, hashes only).",
    {
      series_id: z
        .string()
        .regex(SERIES_ID_PATTERN, "Series ID must be uppercase with no special characters except _, -, #")
        .describe("BLS series ID, e.g. LAUCN040010000000005"),
    },
    async ({ series_id }) => {
      try {
        const data = await client.getSingleSeries(series_id);
        return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
      } catch (error) {
        return wrapError(error);
      }
    }
  );

  server.tool(
    "get_latest_series",
    "Retrieve the most recent data point for a given BLS series ID.",
    {
      series_id: z
        .string()
        .regex(SERIES_ID_PATTERN, "Series ID must be uppercase with no special characters except _, -, #")
        .describe("BLS series ID, e.g. LAUCN040010000000005"),
    },
    async ({ series_id }) => {
      try {
        const data = await client.getLatestSeries(series_id);
        return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
      } catch (error) {
        return wrapError(error);
      }
    }
  );

  server.tool(
    "get_multiple_series",
    "Retrieve data for one or more BLS time series. " +
      "Registered users can include up to 50 series IDs. " +
      "Optionally specify start/end years (up to 20-year range), " +
      "and enable catalog, calculations, annual averages, or aspects.",
    {
      series_ids: z
        .array(
          z.string().regex(SERIES_ID_PATTERN, "Each series ID must be uppercase with no special characters except _, -, #")
        )
        .min(1)
        .max(50)
        .describe("Array of BLS series IDs"),
      start_year: z
        .string()
        .regex(/^\d{4}$/, "Must be a 4-digit year")
        .optional()
        .describe("Start year in YYYY format"),
      end_year: z
        .string()
        .regex(/^\d{4}$/, "Must be a 4-digit year")
        .optional()
        .describe("End year in YYYY format"),
      catalog: z
        .boolean()
        .optional()
        .describe("Include catalog data (requires registration key)"),
      calculations: z
        .boolean()
        .optional()
        .describe("Include calculations such as net and percent changes (requires registration key)"),
      annual_average: z
        .boolean()
        .optional()
        .describe("Include annual average data (requires registration key)"),
      aspects: z
        .boolean()
        .optional()
        .describe("Include aspect data (requires registration key)"),
    },
    async ({ series_ids, start_year, end_year, catalog, calculations, annual_average, aspects }) => {
      try {
        const data = await client.getSeriesData({
          seriesid: series_ids,
          startyear: start_year,
          endyear: end_year,
          catalog,
          calculations,
          annualaverage: annual_average,
          aspects,
        });
        return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
      } catch (error) {
        return wrapError(error);
      }
    }
  );
}
