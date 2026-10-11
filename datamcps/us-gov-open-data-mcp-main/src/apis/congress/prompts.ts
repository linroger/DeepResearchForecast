/**
 * congress MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "legislation_tracker",
    description: "Track the status and details of a specific bill or recent legislation on a topic, with full cross-source analysis.",
    arguments: [
      { name: "topic", description: "Topic or bill name, e.g. 'CHIPS Act', 'border security', 'student loans'", required: true },
    ],
    load: async ({ topic }: any) =>
      `Find and analyze legislation related to "${topic}".\n\n` +
      `== LEGISLATION DETAILS ==\n` +
      `1. Use congress_search_bills to find relevant bills (try current and recent congresses)\n` +
      `2. For the most relevant bill(s), use congress_bill_details to get sponsors, cosponsors (with party breakdown), and status\n` +
      `3. Use congress_bill_actions to see the full legislative timeline\n` +
      `4. Use congress_bill_summaries for the CRS summary\n` +
      `5. Use congress_bill_committees to see which committees handled the bill\n` +
      `6. Check congress_bill_amendments to see if the bill was modified\n` +
      `7. Use congress_bill_subjects to understand the policy areas\n` +
      `8. Use congress_bill_related to find companion bills in the other chamber\n\n` +
      `== VOTE ANALYSIS ==\n` +
      `9. If the bill had a House vote, use congress_house_votes for party-line breakdown\n` +
      `10. If the bill had a Senate vote, use congress_senate_votes for party-line breakdown\n` +
      `11. Compare House and Senate votes to show bicameral alignment or divergence\n\n` +
      `== CROSS-SOURCE CONNECTIONS ==\n` +
      `12. If it became law, use congress_recent_laws to confirm\n` +
      `13. Use lobbying_search to find who lobbied for/against this bill\n` +
      `14. Use fec_search_candidates for top sponsors — check their top donors for potential connections\n` +
      `15. If it affected spending, use usa_spending_over_time to see spending trends before/after\n` +
      `16. Check Federal Register (fr_search_rules) for implementing regulations\n` +
      `17. Use FRED series to check relevant economic indicators before and after passage\n\n` +
      `Present a clear timeline: introduced → committee → floor vote → signed/vetoed.\n` +
      `Always show party-line vote breakdown alongside donor/lobbying data for transparency.`,
  },
];
