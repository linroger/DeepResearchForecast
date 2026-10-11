import { describe, expect, test, jest } from '@jest/globals';
import { SessionManager } from '../../../src/http/session-manager.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';

const mockTransport = () => ({
  close: jest.fn<() => Promise<void>>().mockResolvedValue(undefined),
}) as unknown as StreamableHTTPServerTransport;

describe('SessionManager', () => {
  test('stores and retrieves sessions', () => {
    const manager = new SessionManager(10, 60_000);
    const transport = mockTransport();

    manager.add('session-1', transport);

    expect(manager.get('session-1')).toBe(transport);
    expect(manager.size).toBe(1);
  });

  test('returns undefined for unknown sessions', () => {
    const manager = new SessionManager(10, 60_000);
    expect(manager.get('unknown')).toBeUndefined();
  });

  test('reports capacity against the max session limit', () => {
    const manager = new SessionManager(2, 60_000);
    expect(manager.hasCapacity).toBe(true);

    manager.add('a', mockTransport());
    manager.add('b', mockTransport());

    expect(manager.hasCapacity).toBe(false);

    manager.delete('a');
    expect(manager.hasCapacity).toBe(true);
  });

  test('sweep closes and removes idle sessions only', async () => {
    const manager = new SessionManager(10, 1_000);
    const idle = mockTransport();
    const active = mockTransport();

    manager.add('idle', idle);
    manager.add('active', active);

    // Refresh "active" via get() at a simulated later time, then sweep well
    // past the idle session's TTL
    const now = Date.now();
    manager.get('active');
    const reaped = await manager.sweep(now + 2_000);

    expect(reaped).toBeGreaterThanOrEqual(1);
    expect(manager.get('idle')).toBeUndefined();
    expect(idle.close).toHaveBeenCalled();
  });

  test('get refreshes the idle timer', async () => {
    const manager = new SessionManager(10, 1_000);
    manager.add('a', mockTransport());

    // Touch the session, then sweep at a time within TTL of the touch
    manager.get('a');
    const reaped = await manager.sweep(Date.now() + 500);

    expect(reaped).toBe(0);
    expect(manager.get('a')).toBeDefined();
  });

  test('closeAll closes every session and empties the manager', async () => {
    const manager = new SessionManager(10, 60_000);
    const t1 = mockTransport();
    const t2 = mockTransport();
    manager.add('a', t1);
    manager.add('b', t2);

    await manager.closeAll();

    expect(manager.size).toBe(0);
    expect(t1.close).toHaveBeenCalled();
    expect(t2.close).toHaveBeenCalled();
  });

  test('closeAll tolerates transports that fail to close', async () => {
    const manager = new SessionManager(10, 60_000);
    const failing = {
      close: jest.fn<() => Promise<void>>().mockRejectedValue(new Error('boom')),
    } as unknown as StreamableHTTPServerTransport;
    manager.add('a', failing);
    manager.add('b', mockTransport());

    await expect(manager.closeAll()).resolves.toBeUndefined();
    expect(manager.size).toBe(0);
  });
});
