/**
 * usaspending MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "federal_spending_overview",
    description: "Comprehensive overview of federal spending with connections to authorizing legislation and votes.",
    load: async () =>
      "Give me a comprehensive overview of federal spending using USAspending data.\n\n" +
      "== SPENDING DATA ==\n" +
      "1. **Top spending agencies** — use usa_spending_by_agency with limit=15\n" +
      "2. **Top recipients** — use usa_spending_by_recipient for contracts, limit=15\n" +
      "3. **Top states by spending** — use usa_spending_by_state\n" +
      "4. **Spending trend** — use usa_spending_over_time with group=quarter for the last 2 years\n\n" +
      "== LEGISLATIVE AUTHORIZATION ==\n" +
      "5. Use congress_search_bills for 'appropriations' in the current congress to find the authorizing legislation\n" +
      "6. Use congress_house_votes and congress_senate_votes to show how each party voted on the appropriations\n\n" +
      "== CONTEXT ==\n" +
      "7. Use census_population to calculate per-capita spending by state\n" +
      "8. Use lobbying_search for top-spending agencies to find who lobbied for these programs\n\n" +
      "Summarize the key findings: which agencies spend the most, which companies receive the most, " +
      "which states get the most per capita, how each party voted on the budget, and whether spending is trending up or down.",
  },
];
