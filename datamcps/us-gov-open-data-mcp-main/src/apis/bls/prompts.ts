/**
 * bls MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "jobs_report",
    description: "Get a comprehensive labor market overview — employment by industry, unemployment demographics, wages, and job openings.",
    load: async () =>
      "Generate a comprehensive labor market report using BLS data.\n\n" +
      "1. **Employment by industry** — use bls_employment_by_industry for sector breakdown with YoY changes\n" +
      "2. **CPI breakdown** — use bls_cpi_breakdown to show cost-of-living pressure on workers\n" +
      "3. **Wages** — use bls_series_data for CES0500000003 (average hourly earnings)\n" +
      "4. **Broader unemployment** — use bls_series_data for LNS13023621 (U-6) and LNS11300000 (participation rate)\n\n" +
      "Compare wages to CPI: are real wages rising or falling?\n" +
      "Which industries are growing vs shrinking?\n" +
      "Present the full picture of the labor market.",
  },
];
