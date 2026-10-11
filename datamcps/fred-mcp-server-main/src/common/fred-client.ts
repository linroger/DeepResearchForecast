/**
 * FRED HTTP client.
 *
 * Owns the full request pipeline: rate limiting, response caching, in-flight
 * request coalescing, timeouts, and retries with exponential backoff.
 *
 * All collaborators are injected through the constructor (defaulting to the
 * in-memory implementations), so alternative backends — a Redis cache or a
 * distributed throttle for multi-instance deployments — plug in without
 * touching this class.
 */
import { getFREDConfig, FREDConfig } from "./config.js";
import { logger as defaultLogger } from "./logger.js";
import { TTLCache } from "./cache.js";
import { RateLimiter } from "./rate-limiter.js";
import { FREDApiError } from "./errors.js";

const BASE_URL = "https://api.stlouisfed.org/fred";

/** Minimal cache contract the client depends on. */
export interface ResponseCache {
  get(key: string): unknown | undefined;
  set(key: string, value: unknown): void;
  clear(): void;
  stats(): { size: number; hits: number; misses: number };
}

/** Minimal throttle contract the client depends on. */
export interface Throttle {
  acquire(): Promise<void>;
  dispose(): void;
  readonly pending: number;
  readonly available: number;
}

/** Minimal logger contract the client depends on. */
export interface Logger {
  error(message: string, ...args: unknown[]): void;
  warn(message: string, ...args: unknown[]): void;
  info(message: string, ...args: unknown[]): void;
  debug(message: string, ...args: unknown[]): void;
}

export interface FREDClientOptions {
  /** Config provider, evaluated per request so env changes take effect. */
  config?: () => FREDConfig;
  cache?: ResponseCache;
  throttle?: Throttle;
  fetchFn?: typeof fetch;
  logger?: Logger;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export class FREDClient {
  private readonly configProvider: () => FREDConfig;
  private readonly fetchFn: typeof fetch;
  private readonly log: Logger;
  private cache: ResponseCache | null;
  private throttle: Throttle | null;
  private readonly inFlight = new Map<string, Promise<unknown>>();

  constructor(private readonly options: FREDClientOptions = {}) {
    this.configProvider = options.config ?? getFREDConfig;
    this.fetchFn = options.fetchFn ?? ((...args) => fetch(...args));
    this.log = options.logger ?? defaultLogger;
    this.cache = options.cache ?? null;
    this.throttle = options.throttle ?? null;
  }

  /**
   * Performs a GET against a FRED endpoint, returning the parsed JSON body.
   */
  async request<T>(
    endpoint: string,
    queryParams: Record<string, string | number | boolean> = {}
  ): Promise<T> {
    const config = this.configProvider();

    if (!config.apiKey) {
      throw new FREDApiError(
        "FRED_API_KEY is not set. Get a free API key at https://fred.stlouisfed.org/docs/api/api_key.html and set the FRED_API_KEY environment variable.",
        undefined,
        false
      );
    }

    const url = new URL(`${BASE_URL}/${endpoint}`);
    Object.entries(queryParams).forEach(([key, value]) => {
      url.searchParams.append(key, String(value));
    });
    url.searchParams.append("api_key", config.apiKey);
    url.searchParams.append("file_type", "json");

    const fullUrl = url.toString();
    // Never log or key the cache on the API key
    const cacheKey = fullUrl.replace(/api_key=[^&]+/, "api_key=***");

    const cached = this.getCache(config).get(cacheKey);
    if (cached !== undefined) {
      this.log.debug(`FRED cache hit: ${cacheKey}`);
      return cached as T;
    }

    // Coalesce identical concurrent requests into a single upstream call
    const pending = this.inFlight.get(cacheKey);
    if (pending) {
      this.log.debug(`FRED request coalesced: ${cacheKey}`);
      return pending as Promise<T>;
    }

    this.log.debug(`Fetching FRED API: ${cacheKey}`);

    const requestPromise = this.execute<T>(fullUrl, cacheKey, config)
      .then((result) => {
        this.getCache(config).set(cacheKey, result);
        return result;
      })
      .finally(() => {
        this.inFlight.delete(cacheKey);
      });

    this.inFlight.set(cacheKey, requestPromise);
    return requestPromise as Promise<T>;
  }

  /** Cache/throttle statistics, exposed for health endpoints. */
  stats() {
    return {
      cache: this.cache?.stats() ?? { size: 0, hits: 0, misses: 0 },
      rateLimiter: this.throttle
        ? { pending: this.throttle.pending, available: this.throttle.available }
        : null,
      inFlight: this.inFlight.size,
    };
  }

  /** Drop cached responses, queued waiters, and in-flight bookkeeping. */
  reset(): void {
    this.cache?.clear();
    this.cache = this.options.cache ?? null;
    this.throttle?.dispose();
    this.throttle = this.options.throttle ?? null;
    this.inFlight.clear();
  }

  private getCache(config: FREDConfig): ResponseCache {
    if (!this.cache) {
      this.cache = new TTLCache(config.cacheMaxEntries, config.cacheTtlMs);
    }
    return this.cache;
  }

  private getThrottle(config: FREDConfig): Throttle {
    if (!this.throttle) {
      this.throttle = new RateLimiter(config.rateLimitPerMinute);
    }
    return this.throttle;
  }

  private async execute<T>(url: string, redactedUrl: string, config: FREDConfig): Promise<T> {
    let lastError: FREDApiError | null = null;

    for (let attempt = 0; attempt <= config.maxRetries; attempt++) {
      if (attempt > 0) {
        const delay = this.retryDelayMs(attempt, config.retryBaseDelayMs);
        this.log.warn(
          `Retrying FRED request (attempt ${attempt}/${config.maxRetries}) after ${delay}ms: ${redactedUrl}`
        );
        await sleep(delay);
      }

      await this.getThrottle(config).acquire();

      let response: Response;
      try {
        response = await this.fetchWithTimeout(url, config.requestTimeoutMs);
      } catch (error) {
        const isAbort = error instanceof Error && error.name === "AbortError";
        lastError = new FREDApiError(
          isAbort
            ? `FRED API request timed out after ${config.requestTimeoutMs}ms`
            : `FRED API network error: ${error instanceof Error ? error.message : String(error)}`,
          undefined,
          true
        );
        continue;
      }

      if (response.ok) {
        return response.json() as Promise<T>;
      }

      const errorText = await response.text();
      const retryable = response.status === 429 || response.status >= 500;
      lastError = new FREDApiError(
        `FRED API error (${response.status}): ${errorText}`,
        response.status,
        retryable
      );
      if (!retryable) throw lastError;

      // Honor the server's Retry-After on rate-limit responses
      const retryAfter = response.headers?.get?.("retry-after");
      if (retryAfter && attempt < config.maxRetries) {
        const seconds = parseInt(retryAfter, 10);
        if (!Number.isNaN(seconds) && seconds >= 0) {
          this.log.warn(`FRED rate limit hit (429); honoring Retry-After of ${seconds}s`);
          await sleep(seconds * 1000);
        }
      }
    }

    throw lastError ?? new FREDApiError("FRED API request failed", undefined, false);
  }

  private retryDelayMs(attempt: number, baseMs: number): number {
    // Exponential backoff with full jitter
    const cap = baseMs * 2 ** attempt;
    return Math.floor(Math.random() * cap);
  }

  private async fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    (timer as { unref?: () => void }).unref?.();
    try {
      return await this.fetchFn(url, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }
  }
}
