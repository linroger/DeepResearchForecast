/**
 * fec MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "campaign_finance_summary",
    description: "Overview of fundraising in the current election cycle with connections to voting records and lobbying.",
    load: async () =>
      "Build a campaign finance overview for the current cycle:\n\n" +
      "== FUNDRAISING ==\n" +
      "1. Use fec_top_candidates for office 'P' (Presidential) — top fundraisers\n" +
      "2. Use fec_top_candidates for office 'S' (Senate) — top fundraisers\n" +
      "3. Use fec_top_candidates for office 'H' (House) — top fundraisers\n\n" +
      "== CROSS-SOURCE CONNECTIONS ==\n" +
      "4. For top incumbents, use congress_member_bills to see what they've sponsored\n" +
      "5. Use congress_house_votes or congress_senate_votes to find key votes by these members\n" +
      "6. Use lobbying_contributions to check lobbyist donations to top fundraisers\n" +
      "7. Use lobbying_search to find which industries lobby these candidates\n\n" +
      "Show total raised, spent, cash on hand, and debt. Note party breakdown. " +
      "Highlight any connections between top donors/lobbying activity and the member's voting record or sponsored bills.",
  },
];

// ─── Re-export cache control from SDK ────────────────────────────────

export { clearCache } from "./sdk.js";
