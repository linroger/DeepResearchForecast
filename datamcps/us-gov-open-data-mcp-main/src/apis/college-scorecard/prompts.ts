/**
 * college-scorecard MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "college_roi",
    description: "Analyze the return on investment of college — compare costs, debt, and earnings across school types.",
    load: async () =>
      "Analyze college ROI using the College Scorecard:\n\n" +
      "1. Use scorecard_top ranking='earnings' per_page=10 — schools with highest post-grad earnings\n" +
      "2. Use scorecard_top ranking='expensive' per_page=10 — most expensive schools\n" +
      "3. Use scorecard_search ownership=1 sort='latest.earnings.10_yrs_after_entry.median:desc' per_page=10 — top public schools by earnings\n" +
      "4. Use scorecard_search ownership=2 sort='latest.earnings.10_yrs_after_entry.median:desc' per_page=10 — top private nonprofit by earnings\n\n" +
      "Compare: tuition vs earnings, debt vs earnings ratio, public vs private ROI. " +
      "Cross-reference with FRED (SLOAS — student loan debt outstanding) and BLS (employment by education level).",
  },
];

export { clearCache } from "./sdk.js";
