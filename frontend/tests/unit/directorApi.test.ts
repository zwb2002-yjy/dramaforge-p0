import { afterEach, describe, expect, it, vi } from "vitest";

import {
  authorizeDirectorBudget,
  authorizeAndMaterializeRepair,
  ensureDirectorWorkspace,
  generateConcepts,
  inspectTrial,
  inspectProduction,
  materializeTrial,
  materializeProduction,
  exportProduction,
  planRepairs,
  reviewProduction,
  reviewTrial,
} from "../../src/features/director/api";

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
  window.sessionStorage.clear();
});

describe("Director HTTP client", () => {
  it("creates the workflow once when the aggregate snapshot is missing", async () => {
    const snapshot = {
      project_id: "project-1",
      project_name: "作品",
      aspect_ratio: "9:16",
      workflow: { id: "workflow-1", project_id: "project-1", template_id: "live_action_dialogue_short", template_version: "1.0.0", status: "drafting_creative", current_stage: "creative", current_artifact_versions: {}, version: 1 },
      current_artifacts: {}, approvals: [], budget_authorizations: [], pending_changes: [], issues: [], step_runs: [], production_batches: [], budget_reservations: [], allowed_actions: ["generate_concepts"], next_action: "start",
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(404, { detail: "director workflow not found" }))
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf" }))
      .mockResolvedValueOnce(response(201, snapshot.workflow))
      .mockResolvedValueOnce(response(200, snapshot));

    await expect(ensureDirectorWorkspace("project-1")).resolves.toEqual(snapshot);
    expect(fetchMock.mock.calls.map((call) => [call[0], (call[1] as RequestInit | undefined)?.method ?? "GET"])).toEqual([
      ["/api/v1/projects/project-1/director/workspace-snapshot", "GET"],
      ["/api/v1/auth/csrf", "GET"],
      ["/api/v1/projects/project-1/director/workflow", "POST"],
      ["/api/v1/projects/project-1/director/workspace-snapshot", "GET"],
    ]);
  });

  it("sends explicit text authorization with a concept command", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf" }))
      .mockResolvedValueOnce(response(201, { id: "concept-version", payload: { concepts: [] } }));

    await generateConcepts("project-1", {
      entry_mode: "no_idea",
      creation_goal: "self_expression",
      authorize_text_call: true,
      idempotency_key: "concepts:1",
    });
    const [, request] = vi.mocked(globalThis.fetch).mock.calls[1];
    expect(JSON.parse(String(request?.body))).toMatchObject({
      entry_mode: "no_idea",
      creation_goal: "self_expression",
      authorize_text_call: true,
      idempotency_key: "concepts:1",
    });
  });

  it("uses only the real trial endpoints for budget, materialization, inspection, and review", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf-1" }))
      .mockResolvedValueOnce(response(201, { id: "budget-1" }))
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf-2" }))
      .mockResolvedValueOnce(response(201, { batch: { id: "batch-1" }, node_runs: [] }))
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf-3" }))
      .mockResolvedValueOnce(response(201, { id: "quality-1" }))
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf-4" }))
      .mockResolvedValueOnce(response(201, { id: "review-1" }));

    await authorizeDirectorBudget("project-1", {
      authorization_kind: "trial_budget",
      idempotency_key: "budget:key",
      pricing_snapshot_id: "prices-1",
      limit_amount: "2.00",
      currency: "CNY",
      expires_at: "2026-08-12T15:00:00Z",
    });
    await materializeTrial("project-1", "trial:key");
    await inspectTrial("project-1", "batch-1", "inspect:key");
    await reviewTrial("project-1", {
      batch_id: "batch-1",
      decision: "repair",
      user_note: "人物不像",
      idempotency_key: "review:key",
    });

    const calls = vi.mocked(globalThis.fetch).mock.calls;
    expect(calls[1][0]).toBe("/api/v1/projects/project-1/director/budget-authorizations");
    expect(JSON.parse(String(calls[1][1]?.body))).toMatchObject({
      authorization_kind: "trial_budget",
      limit_amount: "2.00",
    });
    expect(calls[3][0]).toBe("/api/v1/projects/project-1/director/trial/materialize");
    expect(calls[5][0]).toBe("/api/v1/projects/project-1/director/trial/inspect");
    expect(calls[7][0]).toBe("/api/v1/projects/project-1/director/trial/review");
    expect(JSON.parse(String(calls[7][1]?.body))).toMatchObject({
      decision: "repair",
      user_note: "人物不像",
    });
  });

  it("uses the controlled formal production, exact export, and repair planning endpoints", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf-1" }))
      .mockResolvedValueOnce(response(201, { batch: { id: "batch-1" }, node_runs: [] }))
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf-2" }))
      .mockResolvedValueOnce(response(201, { id: "quality-1" }))
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf-3" }))
      .mockResolvedValueOnce(response(201, { id: "review-1" }))
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf-4" }))
      .mockResolvedValueOnce(response(201, { export_id: "export-1", export_status: "completed" }))
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf-5" }))
      .mockResolvedValueOnce(response(201, { repair_plan_version: { id: "repair-1" }, options: [] }));

    await materializeProduction("project-1", "production:key");
    await inspectProduction("project-1", "batch-1", "inspect:key");
    await reviewProduction("project-1", { batch_id: "batch-1", decisions: { "shot-1": "accept" }, user_note: "通过", idempotency_key: "review:key" });
    await exportProduction("project-1", "batch-1");
    await planRepairs("project-1", { batch_id: "batch-1", quality_report_version_id: "quality-1", idempotency_key: "repair:key" });

    const calls = vi.mocked(globalThis.fetch).mock.calls;
    expect(calls[1][0]).toBe("/api/v1/projects/project-1/director/production/materialize");
    expect(calls[3][0]).toBe("/api/v1/projects/project-1/director/production/inspect");
    expect(calls[5][0]).toBe("/api/v1/projects/project-1/director/production/review");
    expect(JSON.parse(String(calls[5][1]?.body))).toMatchObject({ decisions: { "shot-1": "accept" } });
    expect(calls[7][0]).toBe("/api/v1/projects/project-1/director/production/export");
    expect(JSON.parse(String(calls[7][1]?.body))).toEqual({ batch_id: "batch-1", try_ffmpeg: true });
    expect(calls[9][0]).toBe("/api/v1/projects/project-1/director/repairs/plan");
  });

  it("sends the selected repair option and its separate budget authorization to the repair executor", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response(200, { csrf_token: "csrf" }))
      .mockResolvedValueOnce(response(201, { batch: { id: "repair-batch" }, node_runs: [] }));
    await authorizeAndMaterializeRepair("project-1", {
      repair_option_id: "repair-0123456789ab",
      budget_authorization_id: "budget-1",
      idempotency_key: "repair-execute:key",
    });
    const [, request] = vi.mocked(globalThis.fetch).mock.calls[1];
    expect(vi.mocked(globalThis.fetch).mock.calls[1][0]).toBe(
      "/api/v1/projects/project-1/director/repairs/repair-0123456789ab/authorize",
    );
    expect(JSON.parse(String(request?.body))).toEqual({
      repair_option_id: "repair-0123456789ab",
      budget_authorization_id: "budget-1",
      idempotency_key: "repair-execute:key",
    });
  });
});
