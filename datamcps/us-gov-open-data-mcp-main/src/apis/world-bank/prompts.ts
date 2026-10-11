/**
 * world-bank MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "international_comparison",
    description: "Compare the U.S. to peer nations on key economic and social indicators.",
    load: async () =>
      "Use wb_compare to compare the U.S. (US) with major economies (GB, DE, JP, CN, CA, FR) on these indicators:\n\n" +
      "1. NY.GDP.PCAP.CD — GDP per capita\n" +
      "2. SH.XPD.CHEX.PC.CD — Health expenditure per capita\n" +
      "3. SP.DYN.LE00.IN — Life expectancy at birth\n" +
      "4. SL.UEM.TOTL.ZS — Unemployment rate\n" +
      "5. GC.DOD.TOTL.GD.ZS — Government debt as % of GDP\n" +
      "6. FP.CPI.TOTL.ZG — Inflation rate\n\n" +
      "Use date range last 5 years. Present as a comparison table. Note where the U.S. ranks among peers and highlight any outliers.",
  },
];

export { clearCache } from "./sdk.js";
