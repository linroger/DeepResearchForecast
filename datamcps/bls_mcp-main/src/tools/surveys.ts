import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { Client, BlsApiError } from "../client.js";

function wrapError(error: unknown): { content: { type: "text"; text: string }[] } {
  if (error instanceof BlsApiError) {
    return {
      content: [
        {
          type: "text" as const,
          text: `Error: ${error.message}${error.isRateLimit ? "\nConsider setting BLS_API_KEY for higher rate limits." : ""}`,
        },
      ],
    };
  }
  return {
    content: [{ type: "text" as const, text: `Unexpected error: ${String(error)}` }],
  };
}

export function registerSurveyTools(server: McpServer, client: Client) {
  server.tool(
    "get_popular_series",
    "Retrieve the 25 most popular BLS series IDs overall or for a specific survey. " +
      "Optionally provide a survey abbreviation to filter by survey.",
    {
      survey: z
        .string()
        .regex(/^[A-Z]{2}$/, "Survey abbreviation must be exactly 2 uppercase letters")
        .optional()
        .describe("Optional 2-letter survey abbreviation, e.g. LA, CU, CE"),
    },
    async ({ survey }) => {
      try {
        const data = await client.getPopularSeries(survey);
        return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
      } catch (error) {
        return wrapError(error);
      }
    }
  );

  server.tool(
    "get_all_surveys",
    "Retrieve a list of all BLS surveys with their abbreviations and names.",
    {},
    async () => {
      try {
        const data = await client.getAllSurveys();
        return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
      } catch (error) {
        return wrapError(error);
      }
    }
  );

  server.tool(
    "get_survey",
    "Retrieve metadata for a single BLS survey by its abbreviation.",
    {
      survey_abbreviation: z
        .string()
        .regex(/^[A-Z]{2}$/, "Survey abbreviation must be exactly 2 uppercase letters")
        .describe("Survey abbreviation, e.g. TU, CU, LA"),
    },
    async ({ survey_abbreviation }) => {
      try {
        const data = await client.getSurvey(survey_abbreviation);
        return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
      } catch (error) {
        return wrapError(error);
      }
    }
  );
}
