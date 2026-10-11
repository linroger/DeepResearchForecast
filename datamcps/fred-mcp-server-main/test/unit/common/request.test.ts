import { describe, expect, test, jest, beforeEach, afterEach } from '@jest/globals';
import { makeRequest, fetchFREDSeriesData, resetRequestState, FREDApiError } from '../../../src/common/request.js';

describe('Request module', () => {
  // Store the original fetch
  const originalFetch = global.fetch;
  
  // Setup before tests
  beforeEach(() => {
    // Drop cached responses and rate-limiter state between tests
    resetRequestState();
    // Mock the global fetch function
    global.fetch = jest.fn().mockImplementation(() => 
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ test: 'data' }),
        text: () => Promise.resolve('response text')
      })
    );
  });
  
  // Cleanup after tests
  afterEach(() => {
    // Restore the original fetch
    global.fetch = originalFetch;
  });
  
  test('makeRequest constructs correct URL with parameters', async () => {
    // Save the environment variable
    const oldApiKey = process.env.FRED_API_KEY;
    process.env.FRED_API_KEY = 'test-api-key';
    
    try {
      // Call makeRequest with test parameters
      await makeRequest('test-endpoint', { param1: 'value1', param2: 'value2' });
      
      // Check that fetch was called
      expect(global.fetch).toHaveBeenCalledTimes(1);
      
      // Get the URL that was passed to fetch
      const url = (global.fetch as jest.Mock).mock.calls[0][0];
      
      // Verify URL includes correct components
      expect(url).toContain('https://api.stlouisfed.org/fred/test-endpoint');
      expect(url).toContain('param1=value1');
      expect(url).toContain('param2=value2');
      expect(url).toContain('api_key=test-api-key');
      expect(url).toContain('file_type=json');
    } finally {
      // Restore the environment variable
      process.env.FRED_API_KEY = oldApiKey;
    }
  });
  
  test('makeRequest throws a clear error when no API key is configured', async () => {
    // Save the environment variable
    const oldApiKey = process.env.FRED_API_KEY;
    delete process.env.FRED_API_KEY;

    try {
      // Call makeRequest and expect a configuration error, not a request
      await expect(makeRequest('test-endpoint'))
        .rejects.toThrow('FRED_API_KEY is not set');
      expect(global.fetch).not.toHaveBeenCalled();
    } finally {
      // Restore the environment variable
      process.env.FRED_API_KEY = oldApiKey;
    }
  });
  
  test('makeRequest returns JSON response on success', async () => {
    const testData = { test: 'data' };
    (global.fetch as jest.Mock).mockImplementationOnce(() => 
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(testData)
      })
    );
    
    const result = await makeRequest('test-endpoint');
    
    expect(result).toEqual(testData);
  });
  
  test('makeRequest throws error on failed request', async () => {
    (global.fetch as jest.Mock).mockImplementationOnce(() => 
      Promise.resolve({
        ok: false,
        status: 404,
        text: () => Promise.resolve('Not Found')
      })
    );
    
    await expect(makeRequest('test-endpoint'))
      .rejects.toThrow('FRED API error (404): Not Found');
  });
  
  describe('fetchFREDSeriesData', () => {
    test('fetches and formats series data correctly', async () => {
      // Mock the makeRequest function's response
      const mockResponse = {
        realtime_start: '2023-01-01',
        realtime_end: '2023-12-31',
        observation_start: '2023-01-01',
        observation_end: '2023-12-31',
        units: 'Index',
        output_type: 1,
        file_type: 'json',
        order_by: 'observation_date',
        sort_order: 'asc',
        count: 2,
        offset: 0,
        limit: 1000,
        observations: [
          {
            realtime_start: '2023-01-01',
            realtime_end: '2023-01-31',
            date: '2023-01-15',
            value: '100.5'
          },
          {
            realtime_start: '2023-02-01',
            realtime_end: '2023-02-28',
            date: '2023-02-15',
            value: '101.2'
          }
        ]
      };
      
      (global.fetch as jest.Mock).mockImplementationOnce(() => 
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockResponse)
        })
      );
      
      // Call the function with test parameters
      const result = await fetchFREDSeriesData('TEST', { start_date: '2023-01-01' });
      
      // Verify the result structure
      expect(result).toHaveProperty('content');
      expect(result.content[0]).toHaveProperty('type', 'text');
      
      // Parse the JSON text to verify the data was formatted correctly
      const parsedData = JSON.parse(result.content[0].text);
      
      // Verify data was transformed correctly
      expect(parsedData).toHaveProperty('series_id', 'TEST');
      expect(parsedData).toHaveProperty('total_observations', 2);
      expect(parsedData.data).toHaveLength(2);
      expect(parsedData.data[0]).toHaveProperty('date', '2023-01-15');
      expect(parsedData.data[0]).toHaveProperty('value', 100.5); // Should be parsed as float
      expect(parsedData.data[1]).toHaveProperty('value', 101.2); // Should be parsed as float
    });
    
    test('handles errors from the API request', async () => {
      // Mock the fetch function to simulate an error response
      (global.fetch as jest.Mock).mockImplementationOnce(() => 
        Promise.resolve({
          ok: false,
          status: 400,
          text: () => Promise.resolve('Bad Request')
        })
      );
      
      // Call the function and expect it to throw an error
      await expect(fetchFREDSeriesData('TEST', {}))
        .rejects
        .toThrow('Failed to retrieve TEST data: FRED API error (400): Bad Request');
    });
    
    test('handles non-Error exceptions', async () => {
      // Mock the fetch function to throw a string or other non-Error object
      (global.fetch as jest.Mock).mockImplementationOnce(() => {
        throw 'Network disconnected';
      });
      
      // Call the function and expect it to throw an error
      await expect(fetchFREDSeriesData('TEST', {}))
        .rejects
        .toThrow('Failed to retrieve TEST data: FRED API network error: Network disconnected');
    });
    
    test('handles malformed response data', async () => {
      // Mock a successful response with invalid data structure
      const invalidResponse = {
        realtime_start: '2023-01-01',
        realtime_end: '2023-12-31',
        // Missing required fields
        observations: [
          {
            // Missing 'value' field which will cause parseFloat to fail
            date: '2023-01-15'
          }
        ]
      };
      
      (global.fetch as jest.Mock).mockImplementationOnce(() => 
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve(invalidResponse)
        })
      );
      
      // The function should still run without errors
      const result = await fetchFREDSeriesData('TEST', {});
      
      // Parse the response to verify the data structure
      const parsedData = JSON.parse(result.content[0].text);
      // Invalid data still included in response but may have null/undefined values
      expect(parsedData.data).toBeDefined();
    });
    
    test('handles empty observations array', async () => {
      // Mock a response with empty observations
      const emptyResponse = {
        realtime_start: '2023-01-01',
        realtime_end: '2023-12-31',
        observation_start: '2023-01-01',
        observation_end: '2023-12-31',
        units: 'Index',
        output_type: 1,
        file_type: 'json',
        order_by: 'observation_date',
        sort_order: 'asc',
        count: 0,
        offset: 0,
        limit: 1000,
        observations: []
      };
      
      (global.fetch as jest.Mock).mockImplementationOnce(() => 
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve(emptyResponse)
        })
      );
      
      // The function should still run without errors
      const result = await fetchFREDSeriesData('TEST', {});
      
      // Parse the response to verify the data is an empty array
      const parsedData = JSON.parse(result.content[0].text);
      expect(parsedData.data).toHaveLength(0);
      expect(parsedData.total_observations).toBe(0);
    });
    
    test('uses metadata from registry for known series', async () => {
      // Mock a successful response
      const mockResponse = {
        realtime_start: '2023-01-01',
        realtime_end: '2023-12-31',
        observation_start: '2023-01-01',
        observation_end: '2023-12-31',
        units: 'Index',
        output_type: 1,
        file_type: 'json',
        order_by: 'observation_date',
        sort_order: 'asc',
        count: 1,
        offset: 0,
        limit: 1000,
        observations: [
          {
            realtime_start: '2023-01-01',
            realtime_end: '2023-01-31',
            date: '2023-01-15',
            value: '100.5'
          }
        ]
      };
      
      (global.fetch as jest.Mock).mockImplementationOnce(() => 
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockResponse)
        })
      );
      
      // Call the function with a known series ID
      const result = await fetchFREDSeriesData('CPIAUCSL', {});
      
      // Parse the result to verify the metadata
      const parsedData = JSON.parse(result.content[0].text);
      
      // Verify the metadata from the registry was used
      expect(parsedData).toHaveProperty('title', 'Consumer Price Index for All Urban Consumers: All Items in U.S. City Average');
      expect(parsedData.description).toContain('Consumer Price Index');
      expect(parsedData.data[0]).toHaveProperty('units', 'Index 1982-1984=100');
    });
  });
});