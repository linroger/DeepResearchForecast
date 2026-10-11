/**
 * cdc MCP prompts.
 */

import type { InputPrompt } from "fastmcp";

export const prompts: InputPrompt<any, any>[] = [
  {
    name: "health_overview",
    description: "Comprehensive U.S. health snapshot: leading causes of death, life expectancy, and international comparison.",
    load: async () =>
      "Build a comprehensive health overview:\n\n" +
      "1. Use cdc_causes_of_death (no state filter, most recent year) for top 10 causes nationally\n" +
      "2. Use cdc_life_expectancy for recent trends by race and sex\n" +
      "3. Use wb_compare with SP.DYN.LE00.IN to compare U.S. life expectancy to GB, DE, JP, CA, FR\n" +
      "4. Use wb_compare with SH.XPD.CHEX.PC.CD to compare health spending per capita\n\n" +
      "Highlight: the U.S. spends more on healthcare than any nation but has lower life expectancy than most peers. Present the data objectively and let the user draw conclusions.",
  },
];

export { clearCache } from "./sdk.js";
