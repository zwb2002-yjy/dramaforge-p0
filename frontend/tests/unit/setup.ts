import { configure } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Route pages are `lazyRouteComponent` chunks: a full-suite run transforms and
// evaluates the whole route graph in every router-mounted test file, so a
// `findBy*` that resolves in ~0.6s when a file runs alone can cross the 1s
// default and fail non-deterministically. Raising the async utility timeout is
// a margin for the real condition, not a substitute for waiting on it.
configure({ asyncUtilTimeout: 5_000 });

// jsdom does not implement scrollTo; TanStack Router may call it.
Object.defineProperty(window, "scrollTo", {
  value: () => undefined,
  writable: true,
});

// Node >= 25 enables the experimental Web Storage API by default. Without
// `--localstorage-file`, `globalThis.localStorage` is a broken global that
// shadows jsdom's storage inside the vitest jsdom environment, leaving
// `window.localStorage` undefined on Node 26 runners. Restore a spec-shaped
// in-memory implementation so tests keep working on both Node generations.
if (typeof window.localStorage === "undefined") {
  class MemoryStorage implements Storage {
    private readonly data = new Map<string, string>();

    get length(): number {
      return this.data.size;
    }

    clear(): void {
      this.data.clear();
    }

    getItem(key: string): string | null {
      return this.data.has(key) ? this.data.get(key)! : null;
    }

    key(index: number): string | null {
      return Array.from(this.data.keys())[index] ?? null;
    }

    removeItem(key: string): void {
      this.data.delete(key);
    }

    setItem(key: string, value: string): void {
      this.data.set(key, String(value));
    }
  }

  Object.defineProperty(window, "localStorage", {
    value: new MemoryStorage(),
    configurable: true,
  });
}
