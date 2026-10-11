import { describe, expect, test, jest, beforeEach, afterEach } from '@jest/globals';
import { registerFREDTools } from '../../../src/fred/tools.js';
import { resetRequestState } from '../../../src/common/request.js';

type ToolHandler = (input: Record<string, unknown>) => Promise<{ content: Array<{ type: string; text: string }> }>;

/** Registers the tools against a stub server and returns handlers by name. */
function captureHandlers(): Record<string, ToolHandler> {
  const handlers: Record<string, ToolHandler> = {};
  const mockServer = {
    registerTool: (name: string, _meta: unknown, handler: ToolHandler) => {
      handlers[name] = handler;
    }
  };
  registerFREDTools(mockServer as never);
  return handlers;
}

const jsonResponse = (body: unknown) => ({
  ok: true,
  status: 200,
  json: () => Promise.resolve(body),
  text: () => Promise.resolve(JSON.stringify(body)),
  headers: { get: () => null },
});

const seriesFixture = {
  id: 'GDP',
  realtime_start: '2024-01-01',
  realtime_end: '2024-12-31',
  title: 'Gross Domestic Product',
  observation_start: '1947-01-01',
  observation_end: '2024-04-01',
  frequency: 'Quarterly',
  frequency_short: 'Q',
  units: 'Billions of Dollars',
  units_short: 'Bil. of $',
  seasonal_adjustment: 'Seasonally Adjusted Annual Rate',
  seasonal_adjustment_short: 'SAAR',
  last_updated: '2024-06-27',
  popularity: 93,
  notes: 'Featured measure of U.S. output.'
};

const observationsFixture = {
  realtime_start: '2024-01-01',
  realtime_end: '2024-12-31',
  observation_start: '1947-01-01',
  observation_end: '2024-04-01',
  units: 'lin',
  output_type: 1,
  file_type: 'json',
  order_by: 'observation_date',
  sort_order: 'asc',
  count: 2,
  offset: 0,
  limit: 100000,
  observations: [
    { realtime_start: '2024-01-01', realtime_end: '2024-12-31', date: '2024-01-01', value: '28624.069' },
    { realtime_start: '2024-01-01', realtime_end: '2024-12-31', date: '2024-04-01', value: '.' }
  ]
};

describe('FRED tool handlers', () => {
  const originalFetch = global.fetch;
  let handlers: Record<string, ToolHandler>;

  beforeEach(() => {
    resetRequestState();
    handlers = captureHandlers();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  describe('fred_browse', () => {
    test('browses root categories', async () => {
      global.fetch = jest.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({ categories: [{ id: 0, name: 'Root', parent_id: 0 }] }) as never
      );

      const result = await handlers.fred_browse({ browse_type: 'categories' });
      const parsed = JSON.parse(result.content[0].text);

      expect(String((global.fetch as jest.Mock).mock.calls[0][0])).toContain('/fred/category?');
      expect(parsed.categories).toEqual([{ id: 0, name: 'Root', parent_id: 0 }]);
    });

    test('browses child categories when category_id is given', async () => {
      global.fetch = jest.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({ categories: [{ id: 5, name: 'Money', parent_id: 0 }] }) as never
      );

      await handlers.fred_browse({ browse_type: 'categories', category_id: 0 });

      // category_id 0 is falsy but the tree root; a child listing still needs the parameter when truthy
      expect(String((global.fetch as jest.Mock).mock.calls[0][0])).toContain('/fred/category');
    });

    test('lists series in a category', async () => {
      global.fetch = jest.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({
          count: 1, offset: 0, limit: 50,
          seriess: [seriesFixture]
        }) as never
      );

      const result = await handlers.fred_browse({ browse_type: 'category_series', category_id: 125 });
      const parsed = JSON.parse(result.content[0].text);

      expect(parsed.category_id).toBe(125);
      expect(parsed.total_series).toBe(1);
      expect(parsed.series[0].id).toBe('GDP');
    });

    test('category_series requires category_id', async () => {
      await expect(handlers.fred_browse({ browse_type: 'category_series' }))
        .rejects.toThrow('category_id is required');
    });

    test('release_series requires release_id', async () => {
      await expect(handlers.fred_browse({ browse_type: 'release_series' }))
        .rejects.toThrow('release_id is required');
    });

    test('lists releases', async () => {
      global.fetch = jest.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({
          realtime_start: '2024-01-01', realtime_end: '2024-12-31',
          order_by: 'release_id', sort_order: 'asc',
          count: 1, offset: 0, limit: 50,
          releases: [{ id: 10, realtime_start: '2024-01-01', realtime_end: '2024-12-31', name: 'GDP Release', press_release: true, link: 'https://example.com' }]
        }) as never
      );

      const result = await handlers.fred_browse({ browse_type: 'releases' });
      const parsed = JSON.parse(result.content[0].text);

      expect(parsed.total_releases).toBe(1);
      expect(parsed.releases[0].name).toBe('GDP Release');
    });

    test('lists series in a release', async () => {
      global.fetch = jest.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({ count: 1, offset: 0, limit: 50, seriess: [seriesFixture] }) as never
      );

      const result = await handlers.fred_browse({ browse_type: 'release_series', release_id: 53 });
      const parsed = JSON.parse(result.content[0].text);

      expect(parsed.release_id).toBe(53);
      expect(parsed.series[0].id).toBe('GDP');
    });

    test('lists sources', async () => {
      global.fetch = jest.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({
          realtime_start: '2024-01-01', realtime_end: '2024-12-31',
          order_by: 'source_id', sort_order: 'asc',
          count: 1, offset: 0, limit: 50,
          sources: [{ id: 1, realtime_start: '2024-01-01', realtime_end: '2024-12-31', name: 'Board of Governors', link: 'https://www.federalreserve.gov/' }]
        }) as never
      );

      const result = await handlers.fred_browse({ browse_type: 'sources' });
      const parsed = JSON.parse(result.content[0].text);

      expect(parsed.total_sources).toBe(1);
      expect(parsed.sources[0].name).toBe('Board of Governors');
    });
  });

  describe('fred_search', () => {
    test('formats search results with truncated notes', async () => {
      global.fetch = jest.fn<typeof fetch>().mockResolvedValue(
        jsonResponse({
          realtime_start: '2024-01-01', realtime_end: '2024-12-31',
          order_by: 'search_rank', sort_order: 'desc',
          count: 1, offset: 0, limit: 25,
          seriess: [{ ...seriesFixture, notes: 'x'.repeat(300) }]
        }) as never
      );

      const result = await handlers.fred_search({ search_text: 'gdp' });
      const parsed = JSON.parse(result.content[0].text);

      expect(parsed.total_results).toBe(1);
      expect(parsed.results[0].id).toBe('GDP');
      expect(parsed.results[0].notes.endsWith('...')).toBe(true);
      expect(parsed.results[0].notes.length).toBe(203);
      expect(String((global.fetch as jest.Mock).mock.calls[0][0])).toContain('search_text=gdp');
    });
  });

  describe('fred_get_series', () => {
    test('combines observations with series metadata', async () => {
      global.fetch = jest.fn<typeof fetch>().mockImplementation(((url: string) => {
        if (String(url).includes('series/observations')) {
          return Promise.resolve(jsonResponse(observationsFixture));
        }
        return Promise.resolve(jsonResponse({
          realtime_start: '2024-01-01', realtime_end: '2024-12-31',
          seriess: [seriesFixture]
        }));
      }) as never);

      const result = await handlers.fred_get_series({ series_id: 'GDP' });
      const parsed = JSON.parse(result.content[0].text);

      expect(parsed.series_id).toBe('GDP');
      expect(parsed.title).toBe('Gross Domestic Product');
      expect(parsed.units).toBe('Billions of Dollars');
      expect(parsed.data).toEqual([
        { date: '2024-01-01', value: 28624.069 },
        { date: '2024-04-01', value: null } // "." means missing in FRED
      ]);
    });

    test('falls back to defaults when metadata fetch fails', async () => {
      global.fetch = jest.fn<typeof fetch>().mockImplementation(((url: string) => {
        if (String(url).includes('series/observations')) {
          return Promise.resolve(jsonResponse(observationsFixture));
        }
        return Promise.resolve({
          ok: false, status: 500,
          text: () => Promise.resolve('metadata down'),
          json: () => Promise.resolve({}),
          headers: { get: () => null },
        });
      }) as never);

      const result = await handlers.fred_get_series({ series_id: 'GDP' });
      const parsed = JSON.parse(result.content[0].text);

      expect(parsed.title).toBe('FRED Series: GDP');
      expect(parsed.total_observations).toBe(2);
    });

    test('propagates observation fetch failures', async () => {
      global.fetch = jest.fn<typeof fetch>().mockResolvedValue({
        ok: false, status: 400,
        text: () => Promise.resolve('Bad Request'),
        json: () => Promise.resolve({}),
        headers: { get: () => null },
      } as never);

      await expect(handlers.fred_get_series({ series_id: 'NOPE' }))
        .rejects.toThrow('Failed to retrieve series data');
    });
  });
});
