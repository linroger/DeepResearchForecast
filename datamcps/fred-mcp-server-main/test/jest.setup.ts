import { jest } from '@jest/globals';

// Mock environment variables
process.env.FRED_API_KEY = 'test-api-key';

// Keep request retries deterministic and fast in tests; individual tests
// override these to exercise retry behavior
process.env.FRED_API_MAX_RETRIES = '0';
process.env.FRED_API_RETRY_BASE_DELAY_MS = '1';

// Mock console.error to avoid cluttering test output
jest.spyOn(console, 'error').mockImplementation(() => {});