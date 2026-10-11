import { describe, expect, test, afterEach } from '@jest/globals';
import { RateLimiter } from '../../../src/common/rate-limiter.js';

describe('RateLimiter', () => {
  let limiter: RateLimiter | null = null;

  afterEach(() => {
    limiter?.dispose();
    limiter = null;
  });

  test('grants tokens immediately while capacity remains', async () => {
    limiter = new RateLimiter(5, 60_000);
    for (let i = 0; i < 5; i++) {
      await limiter.acquire();
    }
    expect(limiter.pending).toBe(0);
  });

  test('queues callers once tokens are exhausted', async () => {
    limiter = new RateLimiter(1, 60_000);
    await limiter.acquire();

    let resolved = false;
    const waiting = limiter.acquire().then(() => { resolved = true; });

    // Give the microtask queue a chance to run; the waiter must still be queued
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(resolved).toBe(false);
    expect(limiter.pending).toBe(1);

    limiter.dispose();
    await waiting;
  });

  test('releases queued callers as tokens refill', async () => {
    // 600 tokens/minute = one every 100ms
    limiter = new RateLimiter(600, 60_000);
    // Drain all tokens synchronously
    for (let i = 0; i < 600; i++) {
      await limiter.acquire();
    }

    const start = Date.now();
    await limiter.acquire();
    // The queued acquire should have waited for a refill rather than
    // resolving immediately
    expect(Date.now() - start).toBeGreaterThanOrEqual(50);
  });

  test('dispose releases all queued waiters', async () => {
    limiter = new RateLimiter(1, 60_000);
    await limiter.acquire();

    const waiters = [limiter.acquire(), limiter.acquire(), limiter.acquire()];
    expect(limiter.pending).toBe(3);

    limiter.dispose();
    await Promise.all(waiters);
    expect(limiter.pending).toBe(0);
  });

  test('available never exceeds capacity', async () => {
    limiter = new RateLimiter(3, 100);
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(limiter.available).toBeLessThanOrEqual(3);
  });
});
