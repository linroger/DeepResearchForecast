/**
 * sec MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "company_snapshot",
    description: "Quick financial overview of a public company from SEC filings.",
    arguments: [
      { name: "company", description: "Company name or ticker", required: true },
    ],
    load: async (args: any) => { const company = args?.company ?? ""; return (
      `Get a financial snapshot of ${company}:\n\n` +
      `1. Use sec_company_search to find the company and get its CIK number\n` +
      "2. Use sec_company_financials with the CIK to get recent financials\n" +
      "   Request these metrics: Revenues, NetIncomeLoss, Assets, Liabilities, EarningsPerShareDiluted\n\n" +
      "Present the last 3-4 years of financial data as a summary. Note trends in revenue, profitability, and debt levels."
    ); },
  },
];

// ─── Re-export cache control from SDK ────────────────────────────────

export { clearCache } from "./sdk.js";
