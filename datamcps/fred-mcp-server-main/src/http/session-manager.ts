/**
 * Tracks live Streamable HTTP transports by session id.
 *
 * Bounds memory under load: sessions are capped, idle sessions are reaped on
 * a sweep interval, and everything can be closed at once on shutdown. Without
 * this, abandoned sessions (clients that never send a DELETE) accumulate for
 * the life of the process.
 */
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { logger } from "../common/logger.js";

interface SessionEntry {
  transport: StreamableHTTPServerTransport;
  lastActivity: number;
}

export class SessionManager {
  private sessions = new Map<string, SessionEntry>();
  private sweeper: ReturnType<typeof setInterval> | null = null;

  constructor(
    private readonly maxSessions: number,
    private readonly ttlMs: number
  ) {}

  /** Returns the transport and refreshes its idle timer, or undefined. */
  get(sessionId: string): StreamableHTTPServerTransport | undefined {
    const entry = this.sessions.get(sessionId);
    if (!entry) return undefined;
    entry.lastActivity = Date.now();
    return entry.transport;
  }

  add(sessionId: string, transport: StreamableHTTPServerTransport): void {
    this.sessions.set(sessionId, { transport, lastActivity: Date.now() });
  }

  delete(sessionId: string): boolean {
    return this.sessions.delete(sessionId);
  }

  get size(): number {
    return this.sessions.size;
  }

  get hasCapacity(): boolean {
    return this.sessions.size < this.maxSessions;
  }

  /** Close and remove sessions idle longer than the TTL. */
  async sweep(now = Date.now()): Promise<number> {
    let reaped = 0;
    for (const [id, entry] of this.sessions) {
      if (now - entry.lastActivity > this.ttlMs) {
        this.sessions.delete(id);
        reaped++;
        try {
          await entry.transport.close();
        } catch (error) {
          logger.warn(`Error closing idle session ${id}:`, error);
        }
      }
    }
    if (reaped > 0) {
      logger.info(`Reaped ${reaped} idle MCP session(s); ${this.sessions.size} active`);
    }
    return reaped;
  }

  startSweeper(intervalMs: number): void {
    if (this.sweeper) return;
    this.sweeper = setInterval(() => {
      void this.sweep();
    }, intervalMs);
    // The sweeper must never keep the process alive on its own
    this.sweeper.unref?.();
  }

  stopSweeper(): void {
    if (this.sweeper) {
      clearInterval(this.sweeper);
      this.sweeper = null;
    }
  }

  /** Close every session; used during graceful shutdown. */
  async closeAll(): Promise<void> {
    this.stopSweeper();
    const entries = [...this.sessions.entries()];
    this.sessions.clear();
    await Promise.allSettled(
      entries.map(async ([id, entry]) => {
        try {
          await entry.transport.close();
        } catch (error) {
          logger.warn(`Error closing session ${id} during shutdown:`, error);
        }
      })
    );
  }
}
