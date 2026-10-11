/**
 * eia MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "energy_snapshot",
    description: "Current U.S. energy prices, production trends, and state comparisons.",
    load: async () =>
      "Use EIA tools to build a current energy overview:\n\n" +
      "1. eia_petroleum — current WTI and Brent crude prices, retail gasoline prices\n" +
      "2. eia_natural_gas — current natural gas prices\n" +
      "3. eia_electricity — electricity prices by state (show top 5 most/least expensive)\n" +
      "4. eia_total_energy — total U.S. energy overview\n\n" +
      "Also use bls_cpi_breakdown to show the energy component's impact on overall inflation.\n" +
      "Note any recent executive orders from fr_executive_orders related to energy policy.",
  },
];

// ─── Re-export cache control from SDK ────────────────────────────────

export { clearCache } from "./sdk.js";
