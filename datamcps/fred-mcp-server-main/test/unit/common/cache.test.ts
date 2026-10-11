import { describe, expect, test, jest, afterEach } from '@jest/globals';
import { TTLCache } from '../../../src/common/cache.js';

describe('TTLCache', () => {
  afterEach(() => {
    jest.useRealTimers();
  });

  test('stores and retrieves values', () => {
    const cache = new TTLCache<string>(10, 1000);
    cache.set('a', 'value-a');
    expect(cache.get('a')).toBe('value-a');
    expect(cache.size).toBe(1);
  });

  test('returns undefined for missing keys', () => {
    const cache = new TTLCache<string>(10, 1000);
    expect(cache.get('missing')).toBeUndefined();
  });

  test('expires entries after their TTL', () => {
    jest.useFakeTimers();
    const cache = new TTLCache<string>(10, 1000);
    cache.set('a', 'value-a');

    jest.advanceTimersByTime(999);
    expect(cache.get('a')).toBe('value-a');

    jest.advanceTimersByTime(2);
    expect(cache.get('a')).toBeUndefined();
  });

  test('a TTL of zero disables storage', () => {
    const cache = new TTLCache<string>(10, 0);
    cache.set('a', 'value-a');
    expect(cache.get('a')).toBeUndefined();
    expect(cache.size).toBe(0);
  });

  test('evicts the least recently used entry at capacity', () => {
    const cache = new TTLCache<string>(2, 10_000);
    cache.set('a', 'value-a');
    cache.set('b', 'value-b');

    // Touch "a" so "b" becomes least recently used
    cache.get('a');
    cache.set('c', 'value-c');

    expect(cache.get('a')).toBe('value-a');
    expect(cache.get('b')).toBeUndefined();
    expect(cache.get('c')).toBe('value-c');
    expect(cache.size).toBe(2);
  });

  test('overwriting a key does not evict others', () => {
    const cache = new TTLCache<string>(2, 10_000);
    cache.set('a', 'value-a');
    cache.set('b', 'value-b');
    cache.set('a', 'value-a2');

    expect(cache.get('a')).toBe('value-a2');
    expect(cache.get('b')).toBe('value-b');
  });

  test('clear removes all entries and resets stats', () => {
    const cache = new TTLCache<string>(10, 1000);
    cache.set('a', 'value-a');
    cache.get('a');
    cache.get('missing');
    cache.clear();

    expect(cache.size).toBe(0);
    expect(cache.stats()).toEqual({ size: 0, hits: 0, misses: 0 });
  });

  test('tracks hit and miss statistics', () => {
    const cache = new TTLCache<string>(10, 1000);
    cache.set('a', 'value-a');
    cache.get('a');
    cache.get('a');
    cache.get('missing');

    expect(cache.stats()).toEqual({ size: 1, hits: 2, misses: 1 });
  });
});
