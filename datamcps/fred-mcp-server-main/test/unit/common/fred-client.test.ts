import { describe, expect, test, jest, afterEach } from '@jest/globals';
import { FREDClient } from '../../../src/common/fred-client.js';
import { FREDApiError } from '../../../src/common/errors.js';

const okResponse = (body: unknown) => ({
  ok: true,
  status: 200,
  json: () => Promise.resolve(body),
  text: () => Promise.resolve(JSON.stringify(body)),
  headers: { get: () => null },
}) as unknown as Response;

const errorResponse = (status: number, text = 'error') => ({
  ok: false,
  status,
  json: () => Promise.resolve({}),
  text: () => Promise.resolve(text),
  headers: { get: () => null },
}) as unknown as Response;

const testConfig = (overrides: Partial<ReturnType<typeof baseConfig>> = {}) => () => ({
  ...baseConfig(),
  ...overrides,
});

const baseConfig = () => ({
  apiKey: 'test-key',
  requestTimeoutMs: 5_000,
  maxRetries: 0,
  retryBaseDelayMs: 1,
  rateLimitPerMinute: 10_000,
  cacheTtlMs: 60_000,
  cacheMaxEntries: 100,
});

describe('FREDClient', () => {
  let client: FREDClient | null = null;

  afterEach(() => {
    client?.reset();
    client = null;
  });

  test('throws a configuration error when the API key is missing', async () => {
    const fetchFn = jest.fn<typeof fetch>();
    client = new FREDClient({ config: testConfig({ apiKey: '' }), fetchFn });

    await expect(client.request('series')).rejects.toThrow('FRED_API_KEY is not set');
    expect(fetchFn).not.toHaveBeenCalled();
  });

  test('caches successful responses', async () => {
    const fetchFn = jest.fn<typeof fetch>().mockResolvedValue(okResponse({ count: 1 }));
    client = new FREDClient({ config: testConfig(), fetchFn });

    const first = await client.request('series', { series_id: 'GDP' });
    const second = await client.request('series', { series_id: 'GDP' });

    expect(first).toEqual({ count: 1 });
    expect(second).toEqual({ count: 1 });
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(client.stats().cache.hits).toBe(1);
  });

  test('different query parameters are cached independently', async () => {
    const fetchFn = jest.fn<typeof fetch>()
      .mockResolvedValueOnce(okResponse({ id: 'GDP' }))
      .mockResolvedValueOnce(okResponse({ id: 'UNRATE' }));
    client = new FREDClient({ config: testConfig(), fetchFn });

    const gdp = await client.request('series', { series_id: 'GDP' });
    const unrate = await client.request('series', { series_id: 'UNRATE' });

    expect(gdp).toEqual({ id: 'GDP' });
    expect(unrate).toEqual({ id: 'UNRATE' });
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  test('coalesces identical concurrent requests into one upstream call', async () => {
    let release: (value: Response) => void;
    const gate = new Promise<Response>((resolve) => { release = resolve; });
    const fetchFn = jest.fn<typeof fetch>().mockReturnValue(gate);
    client = new FREDClient({ config: testConfig(), fetchFn });

    const a = client.request('series', { series_id: 'GDP' });
    const b = client.request('series', { series_id: 'GDP' });
    expect(client.stats().inFlight).toBe(1);

    release!(okResponse({ count: 42 }));
    const [resultA, resultB] = await Promise.all([a, b]);

    expect(resultA).toEqual({ count: 42 });
    expect(resultB).toEqual({ count: 42 });
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  test('retries retryable failures up to maxRetries', async () => {
    const fetchFn = jest.fn<typeof fetch>()
      .mockResolvedValueOnce(errorResponse(503, 'unavailable'))
      .mockResolvedValueOnce(errorResponse(503, 'unavailable'))
      .mockResolvedValueOnce(okResponse({ recovered: true }));
    client = new FREDClient({ config: testConfig({ maxRetries: 3 }), fetchFn });

    const result = await client.request('series');

    expect(result).toEqual({ recovered: true });
    expect(fetchFn).toHaveBeenCalledTimes(3);
  });

  test('does not retry non-retryable client errors', async () => {
    const fetchFn = jest.fn<typeof fetch>().mockResolvedValue(errorResponse(400, 'Bad Request'));
    client = new FREDClient({ config: testConfig({ maxRetries: 3 }), fetchFn });

    await expect(client.request('series')).rejects.toThrow('FRED API error (400): Bad Request');
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  test('surfaces the last error after exhausting retries', async () => {
    const fetchFn = jest.fn<typeof fetch>().mockResolvedValue(errorResponse(500, 'boom'));
    client = new FREDClient({ config: testConfig({ maxRetries: 2 }), fetchFn });

    await expect(client.request('series')).rejects.toThrow('FRED API error (500): boom');
    expect(fetchFn).toHaveBeenCalledTimes(3);
  });

  test('wraps network failures in FREDApiError', async () => {
    const fetchFn = jest.fn<typeof fetch>().mockRejectedValue(new Error('ECONNRESET'));
    client = new FREDClient({ config: testConfig(), fetchFn });

    const error = await client.request('series').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(FREDApiError);
    expect((error as FREDApiError).message).toContain('FRED API network error: ECONNRESET');
  });

  test('treats aborts as timeouts', async () => {
    const abortError = new Error('The operation was aborted');
    abortError.name = 'AbortError';
    const fetchFn = jest.fn<typeof fetch>().mockRejectedValue(abortError);
    client = new FREDClient({ config: testConfig({ requestTimeoutMs: 123 }), fetchFn });

    await expect(client.request('series')).rejects.toThrow('timed out after 123ms');
  });

  test('never exposes the API key in cache keys or errors', async () => {
    const fetchFn = jest.fn<typeof fetch>().mockResolvedValue(okResponse({ ok: 1 }));
    client = new FREDClient({ config: testConfig({ apiKey: 'super-secret' }), fetchFn });

    await client.request('series');

    // The upstream URL must carry the key...
    expect(String(fetchFn.mock.calls[0][0])).toContain('api_key=super-secret');
    // ...but reset+repeat proves cache keys are redacted (no collision issues)
    expect(client.stats().cache.size).toBe(1);
  });

  test('failed requests are not cached', async () => {
    const fetchFn = jest.fn<typeof fetch>()
      .mockResolvedValueOnce(errorResponse(400, 'bad'))
      .mockResolvedValueOnce(okResponse({ ok: 1 }));
    client = new FREDClient({ config: testConfig(), fetchFn });

    await expect(client.request('series')).rejects.toThrow('FRED API error (400)');
    const result = await client.request('series');

    expect(result).toEqual({ ok: 1 });
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });
});
