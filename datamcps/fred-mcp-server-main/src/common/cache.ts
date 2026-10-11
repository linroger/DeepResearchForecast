/**
 * In-memory TTL cache with LRU eviction.
 *
 * Keeps repeated identical FRED API calls (a common pattern when several MCP
 * sessions ask for the same popular series) from consuming the shared
 * rate-limit budget.
 */

interface CacheEntry<V> {
  value: V;
  expiresAt: number;
}

export class TTLCache<V = unknown> {
  private entries = new Map<string, CacheEntry<V>>();
  private hits = 0;
  private misses = 0;

  constructor(
    private maxEntries: number,
    private defaultTtlMs: number
  ) {}

  get(key: string): V | undefined {
    const entry = this.entries.get(key);
    if (!entry) {
      this.misses++;
      return undefined;
    }
    if (entry.expiresAt <= Date.now()) {
      this.entries.delete(key);
      this.misses++;
      return undefined;
    }
    // Re-insert to mark as most recently used (Map preserves insertion order)
    this.entries.delete(key);
    this.entries.set(key, entry);
    this.hits++;
    return entry.value;
  }

  set(key: string, value: V, ttlMs = this.defaultTtlMs): void {
    if (ttlMs <= 0) return;
    if (this.entries.has(key)) {
      this.entries.delete(key);
    } else if (this.entries.size >= this.maxEntries) {
      // Evict least recently used (first key in insertion order)
      const oldest = this.entries.keys().next().value;
      if (oldest !== undefined) this.entries.delete(oldest);
    }
    this.entries.set(key, { value, expiresAt: Date.now() + ttlMs });
  }

  delete(key: string): boolean {
    return this.entries.delete(key);
  }

  clear(): void {
    this.entries.clear();
    this.hits = 0;
    this.misses = 0;
  }

  get size(): number {
    return this.entries.size;
  }

  stats() {
    return { size: this.entries.size, hits: this.hits, misses: this.misses };
  }
}
