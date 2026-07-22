import { describe, expect, it, vi } from "vitest";

import {
  manualPlanSaveState,
  normalizeCreationState,
  prepareAndEnqueueKeyframe,
} from "../../src/lib/quickWorkflow";

describe("manualPlanSaveState", () => {
  it("prevents a manual save from replacing an Agent Plan", () => {
    expect(manualPlanSaveState("agent", "confirmed")).toEqual({
      disabled: true,
      label: "Agent Plan 已自动保存",
    });
  });

  it("keeps the manual path available without an Agent Plan", () => {
    expect(manualPlanSaveState("manual", "confirmed")).toEqual({
      disabled: false,
      label: "保存手工 Plan",
    });
  });
});

describe("prepareAndEnqueueKeyframe", () => {
  it("stops before plan materialization when canonical registration fails", async () => {
    const registerLead = vi
      .fn()
      .mockRejectedValue(new Error("provider_timeout: canonical unavailable"));
    const confirm = vi.fn();
    const enqueue = vi.fn();

    await expect(
      prepareAndEnqueueKeyframe(
        {
          projectId: "project-1",
          planId: "plan-1",
          canonKey: null,
          leadName: "林夏",
        },
        { registerLead, confirm, enqueue },
      ),
    ).rejects.toThrow("provider_timeout: canonical unavailable");

    expect(confirm).not.toHaveBeenCalled();
    expect(enqueue).not.toHaveBeenCalled();
  });

  it("does not call the local worker tick after enqueueing", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const registerLead = vi.fn();
    const confirm = vi.fn().mockResolvedValue({ node_run_id: "run-1", graph_id: "graph-1" });
    const enqueue = vi.fn().mockResolvedValue({
      node_run_id: "run-1",
      status: "queued",
      job_id: "node-run:run-1",
    });

    await prepareAndEnqueueKeyframe(
      {
        projectId: "project-1",
        planId: "plan-1",
        canonKey: "projects/project-1/characters/lead/canonical.png",
        leadName: "林夏",
      },
      { registerLead, confirm, enqueue },
    );

    expect(confirm).toHaveBeenCalledWith("project-1", "plan-1");
    expect(enqueue).toHaveBeenCalledWith("project-1", "run-1");
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("enqueues every keyframe run materialized from the Plan", async () => {
    const registerLead = vi.fn();
    const confirm = vi.fn().mockResolvedValue({
      node_run_id: "run-1",
      node_run_ids: ["run-1", "run-2", "run-3"],
      graph_id: "graph-1",
      graph_ids: ["graph-1", "graph-2", "graph-3"],
    });
    const enqueue = vi.fn(async (_projectId: string, nodeRunId: string) => ({
      node_run_id: nodeRunId,
      status: "queued",
      job_id: `node-run:${nodeRunId}`,
    }));

    const result = await prepareAndEnqueueKeyframe(
      {
        projectId: "project-1",
        planId: "plan-1",
        canonKey: "projects/project-1/characters/lead/canonical.png",
        leadName: "林夏",
      },
      { registerLead, confirm, enqueue },
    );

    expect(enqueue.mock.calls).toEqual([
      ["project-1", "run-1"],
      ["project-1", "run-2"],
      ["project-1", "run-3"],
    ]);
    expect(result.enqueues).toHaveLength(3);
  });
});

describe("normalizeCreationState", () => {
  it("restores a complete 10-shot Agent workflow", () => {
    const shots = Array.from({ length: 10 }, (_, index) => ({
      shot_number: index + 1,
      visual_description: `Shot ${index + 1}`,
      keyframe_prompt: `Prompt ${index + 1}`,
    }));

    const restored = normalizeCreationState({
      brief: {
        id: "brief-2",
        status: "confirmed",
        source: "agent",
        brief: {
          title: "Rain Witness",
          logline: "A reporter follows a watcher.",
          synopsis: "A complete synopsis.",
          protagonist: { name: "Lin Xia", profile: "Reporter", goal: "Find the truth" },
          conflict: "The watcher anticipates her.",
          stakes: "Her sister remains missing.",
          world: "A neon city.",
          tone: "Suspense",
          audience: "18-35",
          visual_style: "Wet neon noir",
          episode_hook: "The watcher has her sister's face.",
        },
      },
      plan: {
        id: "plan-2",
        status: "draft",
        source: "agent",
        materialized: false,
        plan: { prompt: "Prompt 1", shot_notes: "Ten shots", shots },
      },
    });

    expect(restored.briefRev).toBe("brief-2");
    expect(restored.planId).toBe("plan-2");
    expect(restored.leadName).toBe("Lin Xia");
    expect(restored.step).toBe(4);
    expect(restored.agentBriefNeedsRegeneration).toBe(false);
    expect(restored.agentPlanNeedsRegeneration).toBe(false);
  });

  it("marks legacy Agent Brief and Plan as requiring regeneration", () => {
    const restored = normalizeCreationState({
      brief: {
        id: "brief-v1",
        status: "confirmed",
        source: "agent",
        brief: { logline: "Only a logline", tone: "simple", audience: "general" },
      },
      plan: {
        id: "plan-v1",
        status: "confirmed",
        source: "agent",
        materialized: true,
        plan: { prompt: "single opening keyframe" },
      },
    });

    expect(restored.step).toBe(4);
    expect(restored.agentBriefNeedsRegeneration).toBe(true);
    expect(restored.agentPlanNeedsRegeneration).toBe(true);
  });

  it("keeps a manual single-shot Plan producible", () => {
    const restored = normalizeCreationState({
      brief: {
        id: "brief-manual",
        status: "confirmed",
        source: "user",
        brief: { logline: "Manual path" },
      },
      plan: {
        id: "plan-manual",
        status: "draft",
        source: "manual",
        materialized: false,
        plan: { prompt: "manual keyframe" },
      },
    });

    expect(restored.agentBriefNeedsRegeneration).toBe(false);
    expect(restored.agentPlanNeedsRegeneration).toBe(false);
  });
});
