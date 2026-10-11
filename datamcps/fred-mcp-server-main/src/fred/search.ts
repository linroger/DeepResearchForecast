/**
 * FRED Search API Client
 * 
 * Provides search functionality for discovering FRED series
 */
import { makeRequest } from "../common/request.js";
import { z } from "zod";

/**
 * Schema for a single search result series
 */
const SearchSeriesSchema = z.object({
  id: z.string(),
  realtime_start: z.string(),
  realtime_end: z.string(),
  title: z.string(),
  observation_start: z.string(),
  observation_end: z.string(),
  frequency: z.string(),
  frequency_short: z.string(),
  units: z.string(),
  units_short: z.string(),
  seasonal_adjustment: z.string(),
  seasonal_adjustment_short: z.string(),
  last_updated: z.string(),
  popularity: z.number(),
  notes: z.string().optional(),
});

/**
 * Schema for search response
 */
const SearchResponseSchema = z.object({
  realtime_start: z.string(),
  realtime_end: z.string(),
  order_by: z.string(),
  sort_order: z.string(),
  count: z.number(),
  offset: z.number(),
  limit: z.number(),
  seriess: z.array(SearchSeriesSchema),
});

export type SearchSeries = z.infer<typeof SearchSeriesSchema>;
export type SearchResponse = z.infer<typeof SearchResponseSchema>;

/**
 * Options for searching FRED series
 */
export interface FREDSearchOptions {
  search_text?: string;
  search_type?: "full_text" | "series_id";
  tag_names?: string;
  exclude_tag_names?: string;
  limit?: number;
  offset?: number;
  order_by?: "search_rank" | "series_id" | "title" | "units" | "frequency" | "seasonal_adjustment" | "realtime_start" | "realtime_end" | "last_updated" | "observation_start" | "observation_end" | "popularity";
  sort_order?: "asc" | "desc";
  filter_variable?: "frequency" | "units" | "seasonal_adjustment";
  filter_value?: string;
}

/**
 * Searches for FRED series based on criteria
 */
export async function searchSeries(options: FREDSearchOptions = {}) {
  try {
    const queryParams: Record<string, string | number> = {};
    
    // Add search parameters
    if (options.search_text) queryParams.search_text = options.search_text;
    if (options.search_type) queryParams.search_type = options.search_type;
    if (options.tag_names) queryParams.tag_names = options.tag_names;
    if (options.exclude_tag_names) queryParams.exclude_tag_names = options.exclude_tag_names;
    if (options.limit !== undefined) queryParams.limit = options.limit;
    if (options.offset !== undefined) queryParams.offset = options.offset;
    if (options.order_by) queryParams.order_by = options.order_by;
    if (options.sort_order) queryParams.sort_order = options.sort_order;
    if (options.filter_variable) queryParams.filter_variable = options.filter_variable;
    if (options.filter_value) queryParams.filter_value = options.filter_value;
    
    const response = await makeRequest<SearchResponse>(
      "series/search",
      queryParams
    );
    
    // Format the response for better readability
    const formattedResults = {
      total_results: response.count,
      showing: `${response.offset + 1}-${Math.min(response.offset + response.limit, response.count)}`,
      results: response.seriess.map(series => ({
        id: series.id,
        title: series.title,
        units: series.units,
        frequency: series.frequency,
        seasonal_adjustment: series.seasonal_adjustment,
        observation_range: `${series.observation_start} to ${series.observation_end}`,
        last_updated: series.last_updated,
        popularity: series.popularity,
        notes: series.notes?.substring(0, 200) + (series.notes && series.notes.length > 200 ? "..." : "")
      }))
    };
    
    return {
      content: [{
        type: "text" as const,
        text: JSON.stringify(formattedResults, null, 2)
      }]
    };
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Failed to search FRED series: ${error.message}`);
    }
    throw error;
  }
}

/**
 * Gets detailed information about a specific series
 */
export async function getSeriesInfo(seriesId: string) {
  try {
    const queryParams: Record<string, string> = {
      series_id: seriesId
    };
    
    const response = await makeRequest<{
      realtime_start: string;
      realtime_end: string;
      seriess: SearchSeries[];
    }>("series", queryParams);
    
    if (!response.seriess || response.seriess.length === 0) {
      throw new Error(`Series ${seriesId} not found`);
    }
    
    const series = response.seriess[0];
    
    return {
      content: [{
        type: "text" as const,
        text: JSON.stringify({
          id: series.id,
          title: series.title,
          units: series.units,
          frequency: series.frequency,
          seasonal_adjustment: series.seasonal_adjustment,
          observation_range: `${series.observation_start} to ${series.observation_end}`,
          last_updated: series.last_updated,
          popularity: series.popularity,
          notes: series.notes
        }, null, 2)
      }]
    };
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Failed to get series info: ${error.message}`);
    }
    throw error;
  }
}