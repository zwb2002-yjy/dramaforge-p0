import { describe, expect, it } from "vitest";

import { storyCreateIdempotencyKey } from "../../src/features/script/createKey";

const BRIEF = "双人冲突";
const FILENAME = "story-draft.md";
const DRAFT = "# Episode 1\n## Scene 1\nbody";

describe("storyCreateIdempotencyKey", () => {
  it("is stable for the same submitted content", () => {
    expect(storyCreateIdempotencyKey(BRIEF, FILENAME, DRAFT)).toBe(
      storyCreateIdempotencyKey(BRIEF, FILENAME, DRAFT),
    );
  });

  it("changes when any part of the content changes", () => {
    const base = storyCreateIdempotencyKey(BRIEF, FILENAME, DRAFT);
    expect(storyCreateIdempotencyKey(`${BRIEF} `, FILENAME, DRAFT)).not.toBe(base);
    expect(storyCreateIdempotencyKey(BRIEF, "other.md", DRAFT)).not.toBe(base);
    expect(storyCreateIdempotencyKey(BRIEF, FILENAME, `${DRAFT}\nmore`)).not.toBe(base);
  });

  it("keeps the key and field separators unambiguous", () => {
    expect(storyCreateIdempotencyKey("a\u0000b", FILENAME, DRAFT)).not.toBe(
      storyCreateIdempotencyKey("a", FILENAME, `b\u0000${DRAFT}`),
    );
    expect(storyCreateIdempotencyKey(BRIEF, FILENAME, DRAFT)).toMatch(
      /^story-create-[a-z0-9]+-[a-z0-9]+$/,
    );
  });
});
