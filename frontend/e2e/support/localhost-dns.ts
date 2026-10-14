import dns from "node:dns";

/**
 * Browsers map every `*.localhost` name to the loopback address, but Node's resolver does
 * not on every system (WSL, some Linux and macOS set-ups). Playwright's API requests run in
 * Node, so tenant hosts such as `brightminds.localhost` are mapped to 127.0.0.1 here.
 */
function loopback(hostname: string): string {
  return hostname.endsWith(".localhost") ? "127.0.0.1" : hostname;
}

type AnyFn = (...args: unknown[]) => unknown;

const lookup = dns.lookup as unknown as AnyFn;
dns.lookup = ((hostname: string, ...rest: unknown[]) =>
  lookup(loopback(hostname), ...rest)) as unknown as typeof dns.lookup;

const promisesLookup = dns.promises.lookup as unknown as AnyFn;
dns.promises.lookup = ((hostname: string, ...rest: unknown[]) =>
  promisesLookup(loopback(hostname), ...rest)) as unknown as typeof dns.promises.lookup;
