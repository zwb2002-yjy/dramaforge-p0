import "@testing-library/jest-dom/vitest";

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
