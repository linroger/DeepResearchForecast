/**
 * usda-nass MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "farm_economy",
    description: "Overview of U.S. agricultural production, prices, and trends.",
    load: async () =>
      "Build a farm economy overview:\n\n" +
      "1. Use usda_crop_data for CORN, SOYBEANS, WHEAT — production for last 3 years (national)\n" +
      "2. Use usda_prices for CORN, SOYBEANS, WHEAT — price trends\n" +
      "3. Use usda_livestock for CATTLE and HOGS — inventory trends\n" +
      "4. Use bls_cpi_breakdown to show food price inflation\n" +
      "5. Use usa_spending_by_agency to show USDA spending\n\n" +
      "Connect the dots: are crop prices rising or falling? How does that correlate with consumer food prices (CPI food component)?",
  },
];

// ─── Re-export cache control ─────────────────────────────────────────

export { clearCache } from "./sdk.js";
