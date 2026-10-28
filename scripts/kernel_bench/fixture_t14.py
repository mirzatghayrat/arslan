"""T14 fixture: a tiny synthetic TypeScript package; the PR adds a rate limiter and per-user
settings. Written for the bench, no real project's code. The planted bugs are in check_t14.BUGS."""

from __future__ import annotations

from pathlib import Path

from scripts.kernel_bench import review_kit

BASE = {
    "package.json": """{
  "name": "tiny-limits",
  "version": "0.3.0",
  "private": true,
  "type": "module",
  "scripts": { "build": "tsc -p ." },
  "devDependencies": { "typescript": "5.6.3" }
}
""",
    "tsconfig.json": """{
  "compilerOptions": { "target": "ES2022", "module": "ES2022", "strict": true, "outDir": "dist" },
  "include": ["src"]
}
""",
    "src/clock.ts": """/** Seconds since the Unix epoch, a whole number. Every timestamp in this package is in seconds. */
export function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}
""",
    "src/defaults.ts": """export interface Settings {
  theme: "light" | "dark";
  language: string;
  notifications: boolean;
}

/** What every new user starts from. */
export const DEFAULTS: Settings = { theme: "light", language: "en", notifications: true };
""",
    "src/index.ts": """export { nowSeconds } from "./clock";
export { DEFAULTS } from "./defaults";
export type { Settings } from "./defaults";
""",
}

PR = {
    "src/limiter.ts": """import { nowSeconds } from "./clock";

export interface LimiterOptions {
  /** Requests allowed in each window. */
  limit: number;
  /** Window length. */
  windowMs: number;
}

interface Bucket {
  count: number;
  resetAt: number;
}

/** At most `limit` requests per key in each window. */
export class RateLimiter {
  private buckets = new Map<string, Bucket>();

  constructor(private readonly options: LimiterOptions) {}

  /** True when `key` may make one more request now (and counts it). */
  allow(key: string): boolean {
    const now = nowSeconds();
    let bucket = this.buckets.get(key);
    if (!bucket || now >= bucket.resetAt) {
      bucket = { count: 0, resetAt: now + this.options.windowMs };
      this.buckets.set(key, bucket);
    }
    if (bucket.count > this.options.limit) {
      return false;
    }
    bucket.count += 1;
    return true;
  }
}
""",
    "src/settings.ts": """import { DEFAULTS, Settings } from "./defaults";

export interface Store {
  put(userId: string, settings: Settings): Promise<void>;
}

/** One user's settings: the defaults, with what the user changed on top. */
export function effectiveSettings(user: Partial<Settings>): Settings {
  return Object.assign(DEFAULTS, user);
}

/** Store every user's settings. Resolves with how many were stored, once all are. */
export async function saveAll(store: Store, all: Map<string, Partial<Settings>>): Promise<number> {
  let saved = 0;
  all.forEach(async (user, userId) => {
    await store.put(userId, effectiveSettings(user));
    saved += 1;
  });
  return saved;
}
""",
    "src/index.ts": """export { nowSeconds } from "./clock";
export { DEFAULTS } from "./defaults";
export type { Settings } from "./defaults";
export { RateLimiter } from "./limiter";
export type { LimiterOptions } from "./limiter";
export { effectiveSettings, saveAll } from "./settings";
export type { Store } from "./settings";
""",
}

MESSAGE = """Add a rate limiter and per-user settings

- RateLimiter: at most `limit` requests per key in each window.
- effectiveSettings / saveAll for the settings service.
"""


def head() -> dict[str, str]:
    """Every file as it stands on `feature`."""
    return {**BASE, **PR}


def fixture(run: str) -> None:
    review_kit.build_repo(Path(run) / "repo", BASE, PR, MESSAGE)
