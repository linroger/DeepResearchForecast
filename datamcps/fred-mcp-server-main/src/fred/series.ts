/**
 * FRED Series Data API Client
 *
 * Provides functionality for fetching series data and metadata
 */
import { makeRequest, SeriesObservationsResponse } from "../common/request.js";
import { logger } from "../common/logger.js";
import { getSeriesInfo } from "./search.js";

/**
 * Options for fetching FRED series data
 */
export interface FREDSeriesOptions {
  series_id: string;
  observation_start?: string;
  observation_end?: string;
  limit?: number;
  offset?: number;
  sort_order?: "asc" | "desc";
  units?: "lin" | "chg" | "ch1" | "pch" | "pc1" | "pca" | "cch" | "cca" | "log";
  frequency?: "d" | "w" | "bw" | "m" | "q" | "sa" | "a" | "wef" | "weth" | "wew" | "wetu" | "wem" | "wesu" | "wesa" | "bwew" | "bwem";
  aggregation_method?: "avg" | "sum" | "eop";
  output_type?: number;
  vintage_dates?: string;
}

interface SeriesInfo {
  title?: string;
  units?: string;
  frequency?: string;
  seasonal_adjustment?: string;
  observation_range?: string;
  notes?: string;
}

/**
 * Fetches data for any FRED series with enhanced options
 */
export async function getSeriesData(options: FREDSeriesOptions) {
  try {
    const { series_id, ...queryOptions } = options;

    if (!series_id) {
      throw new Error("series_id is required");
    }

    // Prepare query parameters
    const queryParams: Record<string, string | number> = {
      series_id
    };

    // Add optional parameters
    if (queryOptions.observation_start) queryParams.observation_start = queryOptions.observation_start;
    if (queryOptions.observation_end) queryParams.observation_end = queryOptions.observation_end;
    if (queryOptions.limit !== undefined) queryParams.limit = queryOptions.limit;
    if (queryOptions.offset !== undefined) queryParams.offset = queryOptions.offset;
    if (queryOptions.sort_order) queryParams.sort_order = queryOptions.sort_order;
    if (queryOptions.units) queryParams.units = queryOptions.units;
    if (queryOptions.frequency) queryParams.frequency = queryOptions.frequency;
    if (queryOptions.aggregation_method) queryParams.aggregation_method = queryOptions.aggregation_method;
    if (queryOptions.output_type !== undefined) queryParams.output_type = queryOptions.output_type;
    if (queryOptions.vintage_dates) queryParams.vintage_dates = queryOptions.vintage_dates;

    // Fetch observations and series metadata concurrently; metadata is
    // best-effort and must not fail the data request
    const [dataResponse, seriesInfo] = await Promise.all([
      makeRequest<SeriesObservationsResponse>("series/observations", queryParams),
      fetchSeriesInfoSafe(series_id)
    ]);

    // Transform the data for easier consumption
    const formattedData = dataResponse.observations.map(obs => ({
      date: obs.date,
      value: obs.value === "." ? null : parseFloat(obs.value)
    }));

    const responseData = {
      series_id,
      title: seriesInfo?.title || `FRED Series: ${series_id}`,
      units: seriesInfo?.units || (queryOptions.units ? `Transformed (${queryOptions.units})` : "Value"),
      frequency: seriesInfo?.frequency || "Unknown",
      seasonal_adjustment: seriesInfo?.seasonal_adjustment || "Unknown",
      observation_range: seriesInfo?.observation_range || `${dataResponse.observation_start} to ${dataResponse.observation_end}`,
      total_observations: dataResponse.count,
      data_offset: dataResponse.offset,
      data_limit: dataResponse.limit,
      source: "Federal Reserve Economic Data (FRED)",
      notes: seriesInfo?.notes,
      data: formattedData
    };

    return {
      content: [{
        type: "text" as const,
        text: JSON.stringify(responseData, null, 2)
      }]
    };
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Failed to retrieve series data: ${error.message}`);
    }
    throw error;
  }
}

async function fetchSeriesInfoSafe(seriesId: string): Promise<SeriesInfo | null> {
  try {
    const infoResponse = await getSeriesInfo(seriesId);
    if (infoResponse.content && infoResponse.content[0]) {
      return JSON.parse(infoResponse.content[0].text) as SeriesInfo;
    }
  } catch (error) {
    logger.debug(`Could not fetch series info for ${seriesId}:`, error);
  }
  return null;
}
