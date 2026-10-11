/**
 * fbi MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "crime_overview",
    description: "National and state crime trends overview.",
    load: async () =>
      "Build a crime statistics overview:\n\n" +
      "1. Use fbi_crime_summarized with offense='V' for national violent crime trends\n" +
      "2. Use fbi_crime_summarized with offense='P' for national property crime trends\n" +
      "3. Compare specific states using fbi_crime_summarized with state param\n" +
      "4. Use fbi_arrest_data with offense='all' for arrest trend context\n\n" +
      "Present trends objectively. Note data methodology changes affecting comparisons.",
  },
];

// ─── Re-export cache control from SDK ────────────────────────────────

export { clearCache } from "./sdk.js";
