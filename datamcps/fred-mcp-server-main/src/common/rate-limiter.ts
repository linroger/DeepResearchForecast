/**
 * Token-bucket rate limiter with a FIFO wait queue.
 *
 * FRED enforces a per-key request quota (120/minute). Instead of letting the
 * API reject bursts with 429s, callers await acquire() and are released as
 * tokens refill, smoothing load across concurrent sessions.
 */

export class RateLimiter {
  private tokens: number;
  private lastRefill: number;
  private waiters: Array<() => void> = [];
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private capacity: number,
    private refillIntervalMs: number = 60_000
  ) {
    this.tokens = capacity;
    this.lastRefill = Date.now();
  }

  /** Resolves when a token is available. Tokens refill continuously. */
  async acquire(): Promise<void> {
    this.refill();
    if (this.tokens >= 1 && this.waiters.length === 0) {
      this.tokens -= 1;
      return;
    }
    return new Promise<void>((resolve) => {
      this.waiters.push(resolve);
      this.scheduleDrain();
    });
  }

  /** Number of requests currently queued waiting for a token. */
  get pending(): number {
    return this.waiters.length;
  }

  /** Tokens currently available (after refill). */
  get available(): number {
    this.refill();
    return Math.floor(this.tokens);
  }

  /** Release queued waiters and stop internal timers (for shutdown/tests). */
  dispose(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    for (const resolve of this.waiters.splice(0)) resolve();
  }

  private refill(): void {
    const now = Date.now();
    const elapsed = now - this.lastRefill;
    if (elapsed <= 0) return;
    this.tokens = Math.min(
      this.capacity,
      this.tokens + (elapsed / this.refillIntervalMs) * this.capacity
    );
    this.lastRefill = now;
  }

  private scheduleDrain(): void {
    if (this.timer) return;
    const msPerToken = this.refillIntervalMs / this.capacity;
    this.timer = setTimeout(() => {
      this.timer = null;
      this.refill();
      while (this.tokens >= 1 && this.waiters.length > 0) {
        this.tokens -= 1;
        const resolve = this.waiters.shift()!;
        resolve();
      }
      if (this.waiters.length > 0) this.scheduleDrain();
    }, Math.max(1, Math.ceil(msPerToken)));
    // Never keep the process alive just to drain the queue
    this.timer.unref?.();
  }
}
