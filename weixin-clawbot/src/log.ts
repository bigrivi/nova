/**
 * Process-wide leveled logger.
 *
 * Everything goes to stderr so a piped stdout stays clean, and the SDK's own
 * `console.log` channel is redirected here by passing `log` into `start()`.
 */

/** Severity levels, ordered from most to least verbose. */
export type LogLevel = "debug" | "info" | "warn" | "error";

const LEVEL_ORDER: readonly LogLevel[] = ["debug", "info", "warn", "error"];

let threshold: LogLevel = "info";

/** Raise or lower the global verbosity. Unknown levels are ignored. */
export function setLogLevel(level: string): void {
  if ((LEVEL_ORDER as readonly string[]).includes(level)) {
    threshold = level as LogLevel;
  }
}

/** Write one line at `level`, unless the level is below the threshold. */
function emit(level: LogLevel, args: readonly unknown[]): void {
  if (LEVEL_ORDER.indexOf(level) < LEVEL_ORDER.indexOf(threshold)) {
    return;
  }
  const stamp = new Date().toISOString();
  const body = args
    .map((arg) => (typeof arg === "string" ? arg : inspect(arg)))
    .join(" ");
  process.stderr.write(`${stamp} ${level.toUpperCase().padEnd(5)} ${body}\n`);
}

/** Render a value for the log line, falling back to String for exotic types. */
function inspect(value: unknown): string {
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

/** Log at `debug`. */
export const debug = (...args: unknown[]): void => emit("debug", args);
/** Log at `info`. */
export const info = (...args: unknown[]): void => emit("info", args);
/** Log at `warn`. */
export const warn = (...args: unknown[]): void => emit("warn", args);
/** Log at `error`. */
export const error = (...args: unknown[]): void => emit("error", args);