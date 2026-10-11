/**
 * noaa MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "climate_trends",
    description: "Temperature and precipitation trends for a U.S. location over time.",
    arguments: [
      { name: "location", description: "State or city name", required: false },
    ],
    load: async (args: any) => { const location = args?.location; return (
      `Analyze climate trends${location ? ` for ${location}` : " nationally"}:\n\n` +
      "1. Use noaa_locations to find the location ID (category 'ST' for states)\n" +
      "2. Use noaa_stations to find stations in that location with dataset GSOM (monthly summary)\n" +
      "3. Use noaa_climate_data with GSOM dataset for TAVG (temperature) and PRCP (precipitation) for the last 10 years\n" +
      "4. Compare recent years to historical averages\n\n" +
      "Present temperature and precipitation trends. Note: NOAA values are scaled (temps ×10, precip ×100).\n" +
      "If energy data would add context, use eia_state_energy for the same state."
    ); },
  },
];

// ─── Re-export cache control ─────────────────────────────────────────

export { clearCache } from "./sdk.js";
