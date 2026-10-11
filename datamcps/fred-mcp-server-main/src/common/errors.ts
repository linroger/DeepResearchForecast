/**
 * Error raised for FRED API failures, carrying enough context for callers
 * (and MCP clients) to distinguish auth, rate-limit, and server problems.
 */
export class FREDApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly retryable: boolean = false
  ) {
    super(message);
    this.name = "FREDApiError";
  }
}
