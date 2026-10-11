/**
 * Minimal leveled logger writing to stderr.
 *
 * stdout is reserved for the MCP stdio transport, so every log line must go
 * to stderr. Level is controlled with LOG_LEVEL (error|warn|info|debug).
 */

const LEVELS = { error: 0, warn: 1, info: 2, debug: 3 } as const;

export type LogLevel = keyof typeof LEVELS;

function currentLevel(): number {
  const raw = (process.env.LOG_LEVEL || "info").toLowerCase() as LogLevel;
  return LEVELS[raw] ?? LEVELS.info;
}

function write(level: LogLevel, message: string, ...args: unknown[]) {
  if (LEVELS[level] > currentLevel()) return;
  const timestamp = new Date().toISOString();
  console.error(`${timestamp} [${level.toUpperCase()}] ${message}`, ...args);
}

export const logger = {
  error: (message: string, ...args: unknown[]) => write("error", message, ...args),
  warn: (message: string, ...args: unknown[]) => write("warn", message, ...args),
  info: (message: string, ...args: unknown[]) => write("info", message, ...args),
  debug: (message: string, ...args: unknown[]) => write("debug", message, ...args),
};
