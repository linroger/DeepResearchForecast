/**
 * Centralized runtime configuration
 *
 * All tunables are read from the environment on each call so tests (and
 * long-running processes reacting to restarts) always see current values.
 */

export interface FREDConfig {
  /** FRED API key. Empty string when not configured. */
  apiKey: string;
  /** Per-request timeout in milliseconds. */
  requestTimeoutMs: number;
  /** Maximum retry attempts for retryable failures (429/5xx/network). */
  maxRetries: number;
  /** Base delay for exponential backoff in milliseconds. */
  retryBaseDelayMs: number;
  /** Requests allowed per minute against the FRED API. */
  rateLimitPerMinute: number;
  /** Cache TTL for successful API responses in milliseconds. 0 disables caching. */
  cacheTtlMs: number;
  /** Maximum number of cached responses before LRU eviction. */
  cacheMaxEntries: number;
}

export interface HttpConfig {
  /** Bind address. Empty string means all interfaces (dual-stack). */
  host: string;
  port: number;
  /** Maximum number of concurrent MCP sessions. */
  maxSessions: number;
  /** Idle time after which a session is reaped, in milliseconds. */
  sessionTtlMs: number;
  /** How often the session reaper runs, in milliseconds. */
  sessionSweepIntervalMs: number;
  /** Maximum accepted JSON body size, e.g. "1mb". */
  bodyLimit: string;
}

function intFromEnv(name: string, fallback: number, min = 0): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const parsed = parseInt(raw, 10);
  if (Number.isNaN(parsed) || parsed < min) return fallback;
  return parsed;
}

export function getFREDConfig(): FREDConfig {
  return {
    apiKey: process.env.FRED_API_KEY ?? "",
    requestTimeoutMs: intFromEnv("FRED_API_TIMEOUT_MS", 30_000, 1),
    maxRetries: intFromEnv("FRED_API_MAX_RETRIES", 3),
    retryBaseDelayMs: intFromEnv("FRED_API_RETRY_BASE_DELAY_MS", 500, 1),
    // FRED enforces 120 requests/minute per API key
    rateLimitPerMinute: intFromEnv("FRED_RATE_LIMIT_PER_MINUTE", 120, 1),
    cacheTtlMs: intFromEnv("FRED_CACHE_TTL_MS", 60_000),
    cacheMaxEntries: intFromEnv("FRED_CACHE_MAX_ENTRIES", 500, 1),
  };
}

export function getHttpConfig(): HttpConfig {
  return {
    host: process.env.HOST || "",
    port: intFromEnv("PORT", 3000, 1),
    // 0 is allowed: it drains the server by refusing new sessions
    maxSessions: intFromEnv("MCP_MAX_SESSIONS", 100, 0),
    sessionTtlMs: intFromEnv("MCP_SESSION_TTL_MS", 30 * 60_000, 1),
    sessionSweepIntervalMs: intFromEnv("MCP_SESSION_SWEEP_INTERVAL_MS", 60_000, 1),
    bodyLimit: process.env.MCP_BODY_LIMIT || "1mb",
  };
}
