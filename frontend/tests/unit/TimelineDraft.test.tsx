import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { EditSessionRead } from "../../src/features/editing/api";
import { useTimelineDraft } from "../../src/features/editing/useTimelineDraft";

function session(id = "s1", version = 1): EditSessionRead {
  return {
    id,
    project_id: "p1",
    version,
    name: "Cut",
    status: "draft",
    timeline: {
      clips: [
        { id: "c1", shot_id: "shot1", duration_seconds: 3 },
        { id: "c2", shot_id: "shot2", duration_seconds: 4 },
      ],
      metadata: {},
    },
    production_lineage: { readonly: true },
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  };
}
function mount() {
  return renderHook(({ persisted }) => useTimelineDraft("p1", persisted.id, persisted), {
    initialProps: { persisted: session() },
  });
}

describe("Timeline draft lifecycle", () => {
  it("refreshes a clean draft, but preserves dirty content and its baseline version", () => {
    const { result, rerender } = mount();
    rerender({ persisted: session("s1", 2) });
    expect(result.current.baselineVersion).toBe(2);
    act(() => result.current.updateClipField(0, "subtitle", "local"));
    rerender({ persisted: session("s1", 3) });
    expect(result.current.draft?.clips[0].subtitle).toBe("local");
    expect(result.current.baselineVersion).toBe(2);
    expect(result.current.dirty).toBe(true);
  });

  it("captures allow-listed Save input without mutating draft on a failed/409 request", () => {
    const { result } = mount();
    act(() => result.current.updateTimelineMetadata("music", "local"));
    const input = result.current.captureSave();
    expect(Object.keys(input.timeline).sort()).toEqual(["clips", "metadata"]);
    expect(input.expectedVersion).toBe(1);
    // A failed server request has no receipt to accept.
    expect(result.current.baselineVersion).toBe(1);
    expect(result.current.dirty).toBe(true);
    expect(result.current.draft?.metadata.music).toBe("local");
  });

  it("accepts a save but preserves edits made after that request was submitted", () => {
    const { result } = mount();
    act(() => result.current.updateClipField(0, "subtitle", "submitted"));
    const input = result.current.captureSave();
    act(() => result.current.updateClipField(0, "subtitle", "newer"));
    const saved = { ...session("s1", 2), timeline: input.timeline };
    act(() => expect(result.current.acceptSaved(saved, input)).toBe(true));
    expect(result.current.baseline?.clips[0].subtitle).toBe("submitted");
    expect(result.current.baselineVersion).toBe(2);
    expect(result.current.draft?.clips[0].subtitle).toBe("newer");
    expect(result.current.dirty).toBe(true);
  });

  it("does not roll back an accepted clean save from an older query response", () => {
    const { result, rerender } = mount();
    act(() => result.current.updateClipField(0, "subtitle", "saved"));
    const input = result.current.captureSave();
    act(() => result.current.acceptSaved({ ...session("s1", 2), timeline: input.timeline }, input));
    rerender({ persisted: session("s1", 1) });
    expect(result.current.baselineVersion).toBe(2);
    expect(result.current.draft?.clips[0].subtitle).toBe("saved");
    expect(result.current.dirty).toBe(false);
  });

  it("isolates route lifetimes and rejects a stale save even after returning to the same session", () => {
    const { result, rerender } = mount();
    act(() => result.current.updateClipField(0, "subtitle", "old local"));
    const input = result.current.captureSave();
    rerender({ persisted: session("s2") });
    expect(result.current.dirty).toBe(false);
    expect(result.current.draft?.clips[0].subtitle).toBeUndefined();
    act(() => expect(result.current.acceptSaved(session("s1", 2), input)).toBe(false));
    rerender({ persisted: session("s1") });
    act(() => expect(result.current.acceptSaved(session("s1", 2), input)).toBe(false));
    expect(result.current.baselineVersion).toBe(1);
  });

  it("applies suggestions atomically and refuses invalid or duplicate reorder identities", () => {
    const { result } = mount();
    for (const clip_ids of [
      ["c1", "missing"],
      ["c1", "c1"],
    ]) {
      act(() =>
        expect(
          result.current.applySuggestion(
            [
              { operation: "set_clip_duration", clip_id: "c1", duration_seconds: 9 },
              { operation: "reorder_clips", clip_ids },
            ],
            1,
          ),
        ).not.toBeNull(),
      );
      expect(result.current.draft?.clips[0].duration_seconds).toBe(3);
      expect(result.current.dirty).toBe(false);
    }
    act(() =>
      expect(
        result.current.applySuggestion([{ operation: "reorder_clips", clip_ids: ["c2", "c1"] }], 1),
      ).toBeNull(),
    );
    expect(result.current.draft?.clips.map((clip) => clip.id)).toEqual(["c2", "c1"]);
    expect(result.current.dirty).toBe(true);
  });
});
