/**
 * Backwards-compatible facade over the FREDClient request pipeline.
 *
 * A single shared client instance backs every tool call so all MCP sessions
 * in the process share one cache and one rate-limit budget (FRED quotas are
 * per API key, not per session).
 */
import { z } from "zod";
import { FREDClient } from "./fred-client.js";
import { FREDApiError } from "./errors.js";

export { FREDApiError };
export { FREDClient } from "./fred-client.js";
export type { ResponseCache, Throttle, FREDClientOptions } from "./fred-client.js";

const defaultClient = new FREDClient();

/**
 * Utility for making requests to the FRED API.
 *
 * Handles rate limiting (shared token bucket), response caching, in-flight
 * request coalescing, timeouts, and retries with exponential backoff.
 */
export const makeRequest = async <T>(
  endpoint: string,
  queryParams: Record<string, string | number | boolean> = {}
): Promise<T> => defaultClient.request<T>(endpoint, queryParams);

/**
 * Reset shared request state (cache, rate limiter, in-flight requests).
 * Intended for tests and for reconfiguration after env changes.
 */
export function resetRequestState(): void {
  defaultClient.reset();
}

/** Cache/coalescing statistics for the shared client, for health endpoints. */
export function getRequestStats() {
  return defaultClient.stats();
}

// Observation schema for the series/observations endpoint
export const ObservationSchema = z.object({
  realtime_start: z.string(),
  realtime_end: z.string(),
  date: z.string(),
  value: z.string()
});

// Schema for the series/observations API response
export const SeriesObservationsResponseSchema = z.object({
  realtime_start: z.string(),
  realtime_end: z.string(),
  observation_start: z.string(),
  observation_end: z.string(),
  units: z.string(),
  output_type: z.number(),
  file_type: z.string(),
  order_by: z.string(),
  sort_order: z.string(),
  count: z.number(),
  offset: z.number(),
  limit: z.number(),
  observations: z.array(ObservationSchema)
});

// Export types based on the schemas
export type Observation = z.infer<typeof ObservationSchema>;
export type SeriesObservationsResponse = z.infer<typeof SeriesObservationsResponseSchema>;

/**
 * Metadata for FRED economic data series
 */
export interface FREDSeriesMetadata {
  title: string;
  description: string;
  units: string;
}

/**
 * Registry of known FRED series with their metadata
 * Key: series ID as used in FRED API
 * Value: human-readable metadata about the series
 */
export const FRED_SERIES_REGISTRY: Record<string, FREDSeriesMetadata> = {
  "CPIAUCSL": {
    title: "Consumer Price Index for All Urban Consumers: All Items in U.S. City Average",
    description: "The Consumer Price Index for All Urban Consumers: All Items (CPIAUCSL) is a measure of the average monthly change in the price for goods and services paid by urban consumers between any two time periods.",
    units: "Index 1982-1984=100"
  },
  "RRPONTSYD": {
    title: "Overnight Reverse Repurchase Agreements: Treasury Securities Sold by the Federal Reserve",
    description: "Daily amount value of RRP transactions reported by the New York Fed as part of the Temporary Open Market Operations.",
    units: "Billions of Dollars"
  }
};

/**
 * Fetches economic data for a specific FRED series
 *
 * @param seriesId - FRED series identifier (e.g., "CPIAUCSL")
 * @param options - Query parameters for filtering the data
 * @returns Formatted series data with metadata
 */
export async function fetchFREDSeriesData(
  seriesId: string,
  options: {
    start_date?: string;
    end_date?: string;
    limit?: number;
    sort_order?: "asc" | "desc"
  }
) {
  try {
    const queryParams: Record<string, string | number | boolean> = {
      series_id: seriesId
    };

    if (options.start_date) queryParams.observation_start = options.start_date;
    if (options.end_date) queryParams.observation_end = options.end_date;
    if (options.limit) queryParams.limit = options.limit;
    if (options.sort_order) queryParams.sort_order = options.sort_order;

    const response = await makeRequest<SeriesObservationsResponse>(
      "series/observations",
      queryParams
    );

    const metadata = FRED_SERIES_REGISTRY[seriesId] || {
      title: `FRED Data Series: ${seriesId}`,
      description: `Economic data from FRED series ${seriesId}`,
      units: "Value"
    };

    const formattedData = response.observations.map(obs => ({
      date: obs.date,
      value: parseFloat(obs.value),
      units: metadata.units,
    }));

    const responseData = {
      title: metadata.title,
      description: metadata.description,
      source: "Federal Reserve Economic Data (FRED)",
      series_id: seriesId,
      total_observations: response.count,
      data: formattedData
    };

    return {
      content: [{
        type: "text" as const,
        text: JSON.stringify(responseData, null, 2)
      }]
    };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    throw new Error(`Failed to retrieve ${seriesId} data: ${errorMessage}`);
  }
}
