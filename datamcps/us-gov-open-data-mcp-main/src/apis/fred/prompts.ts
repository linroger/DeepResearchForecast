/**
 * FRED MCP prompts — guided analysis workflows.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "recession_check",
    description: "Analyze whether the U.S. is in or approaching a recession using key economic indicators with legislative context.",
    load: async () =>
      "Use fred_series_data to fetch the following for the last 2 years (sort: desc, frequency: m or q as appropriate):\n\n" +
      "== ECONOMIC INDICATORS ==\n" +
      "1. GDP — quarterly growth (negative 2 consecutive quarters = technical recession)\n" +
      "2. UNRATE — unemployment trend (rising = weakening labor market)\n" +
      "3. PAYEMS — nonfarm payrolls (declining = job losses)\n" +
      "4. CPIAUCSL — inflation trend (context for Fed policy)\n" +
      "5. FEDFUNDS — Fed rate (tightening vs easing cycle)\n" +
      "6. UMCSENT — consumer sentiment (leading indicator)\n\n" +
      "== LEGISLATIVE/FISCAL CONTEXT ==\n" +
      "7. Use congress_recent_laws to find any stimulus, relief, or economic bills passed recently\n" +
      "8. Use congress_house_votes and congress_senate_votes for party-line breakdown on key economic legislation\n" +
      "9. Use Treasury fiscal_snapshot data (debt, revenue, outlays) for fiscal backdrop\n" +
      "10. Use dol_ui_claims_national for the latest weekly unemployment insurance claims (leading indicator)\n\n" +
      "Analyze the trends together. A recession typically shows: declining GDP, rising unemployment, " +
      "falling payrolls, and deteriorating consumer sentiment. Present the data and your assessment " +
      "with appropriate caveats about confounding factors.",
  },
];
