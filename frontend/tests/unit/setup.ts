import "@testing-library/jest-dom/vitest";

// jsdom does not implement scrollTo; TanStack Router may call it.
Object.defineProperty(window, "scrollTo", {
  value: () => undefined,
  writable: true,
});
