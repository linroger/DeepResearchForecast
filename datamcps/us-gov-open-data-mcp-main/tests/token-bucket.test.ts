/**
 * Unit tests for the TokenBucket rate limiter.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { TokenBucket } from "../src/shared/client.js";

describe("TokenBucket", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("allows immediate acquire when tokens are available", async () => {
    const bucket = new TokenBucket(5, 5); // 5 burst, 5/sec
    // Should resolve immediately — bucket starts full
    await bucket.acquire();
    expect(bucket.pending).toBe(0);
  });

  it("allows a full burst without waiting", async () => {
    const bucket = new TokenBucket(3, 1); // burst of 3, 1/sec refill
    // All three should resolve instantly (bucket starts with 3 tokens)
    await bucket.acquire();
    await bucket.acquire();
    await bucket.acquire();
    expect(bucket.pending).toBe(0);
  });

  it("queues callers when burst is exhausted", async () => {
    const bucket = new TokenBucket(1, 10); // burst of 1, 10/sec
    // First acquire drains the only token
    await bucket.acquire();

    // Second acquire should queue
    const p = bucket.acquire();
    expect(bucket.pending).toBe(1);

    // Advance time so a token refills (100ms for 10/sec)
    vi.advanceTimersByTime(150);
    await p;
    expect(bucket.pending).toBe(0);
  });

  it("respects FIFO order under contention", async () => {
    const bucket = new TokenBucket(1, 10); // 1 burst, 10/sec → 1 token every 100ms
    await bucket.acquire(); // drain the bucket

    const order: number[] = [];
    const p1 = bucket.acquire().then(() => order.push(1));
    const p2 = bucket.acquire().then(() => order.push(2));
    const p3 = bucket.acquire().then(() => order.push(3));

    expect(bucket.pending).toBe(3);

    // Advance enough time for all three to be released (300ms+ for 3 tokens at 10/sec)
    vi.advanceTimersByTime(100);
    await Promise.resolve(); // flush microtasks
    vi.advanceTimersByTime(100);
    await Promise.resolve();
    vi.advanceTimersByTime(100);
    await Promise.resolve();

    await Promise.all([p1, p2, p3]);
    expect(order).toEqual([1, 2, 3]);
  });

  it("refills tokens over time", async () => {
    const bucket = new TokenBucket(2, 2); // 2 burst, 2/sec
    // Drain both tokens
    await bucket.acquire();
    await bucket.acquire();

    // Advance 1 second → should refill 2 tokens
    vi.advanceTimersByTime(1000);

    // Both should resolve immediately now
    await bucket.acquire();
    await bucket.acquire();
    expect(bucket.pending).toBe(0);
  });

  it("caps tokens at max (burst) even after long idle", async () => {
    const bucket = new TokenBucket(3, 10); // 3 burst, 10/sec
    // Drain all tokens
    await bucket.acquire();
    await bucket.acquire();
    await bucket.acquire();

    // Wait a very long time — should refill to max (3), not 100
    vi.advanceTimersByTime(10_000);

    // 4th immediate acquire should queue (only 3 available after refill)
    await bucket.acquire();
    await bucket.acquire();
    await bucket.acquire();
    const p = bucket.acquire();
    expect(bucket.pending).toBe(1);

    vi.advanceTimersByTime(150);
    await p;
  });

  it("batch-releases multiple waiters when enough tokens accumulate", async () => {
    const bucket = new TokenBucket(5, 10); // 5 burst, 10/sec
    // Drain all 5
    for (let i = 0; i < 5; i++) await bucket.acquire();

    // Queue 3 waiters
    const results: number[] = [];
    const p1 = bucket.acquire().then(() => results.push(1));
    const p2 = bucket.acquire().then(() => results.push(2));
    const p3 = bucket.acquire().then(() => results.push(3));
    expect(bucket.pending).toBe(3);

    // Advance 500ms → refills 5 tokens (10/sec * 0.5s), enough for all 3
    vi.advanceTimersByTime(500);
    await Promise.resolve();
    await Promise.resolve(); // extra flush for chained .then()
    await Promise.all([p1, p2, p3]);

    expect(results).toEqual([1, 2, 3]);
    expect(bucket.pending).toBe(0);
  });

  it("pending starts at 0", () => {
    const bucket = new TokenBucket(5, 5);
    expect(bucket.pending).toBe(0);
  });
});
