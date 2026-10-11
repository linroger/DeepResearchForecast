/**
 * govinfo MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "recent_legislation_text",
    description: "Get the full text of recently enacted legislation with vote breakdown and impact analysis.",
    load: async () =>
      "Find and present recent significant legislation:\n\n" +
      "1. Use congress_recent_laws to find the 5 most recently signed laws\n" +
      "2. For the most significant one, use govinfo_bill_text to get the full text\n" +
      "3. Use congress_bill_details for cosponsor and committee info\n" +
      "4. Use congress_house_votes for the House party-line vote breakdown\n" +
      "5. Use congress_senate_votes for the Senate party-line vote breakdown\n" +
      "6. Use lobbying_search to find who lobbied on this legislation\n" +
      "7. Check usa_spending_by_agency to see if it affected agency spending\n\n" +
      "Summarize the key provisions, show the party-line vote breakdown from both chambers, " +
      "and note any lobbying activity related to the bill.",
  },
];

// ─── Re-export cache control from SDK ────────────────────────────────

export { clearCache } from "./sdk.js";
