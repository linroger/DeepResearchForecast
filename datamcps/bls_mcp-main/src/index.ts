import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { Client } from "./client.js";
import { registerSeriesTools } from "./tools/series.js";
import { registerSurveyTools } from "./tools/surveys.js";

const server = new McpServer({
  name: "bls-mcp",
  version: "1.0.0",
});

const registrationKey = process.env.BLS_API_KEY;
const client = new Client(registrationKey);

registerSeriesTools(server, client);
registerSurveyTools(server, client);

const transport = new StdioServerTransport();
await server.connect(transport);

console.error("BLS MCP server running on stdio");
if (registrationKey) {
  console.error("Using registered API key (higher rate limits, up to 50 series, 20-year range)");
} else {
  console.error("No BLS_API_KEY set — using unregistered limits (25 queries/day, 10-year range, 25 series max)");
}
