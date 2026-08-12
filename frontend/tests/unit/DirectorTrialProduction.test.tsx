import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProductionStage } from "../../src/features/director/ProductionStage";
import { TrialStage } from "../../src/features/director/TrialStage";
import type {
  DirectorArtifactKind,
  DirectorArtifactVersion,
  DirectorWorkspaceSnapshot,
} from "../../src/features/director/types";

function artifact(
  kind: DirectorArtifactKind,
  payload: Record<string, unknown>,
): DirectorArtifactVersion<Record<string, unknown>> {
  return { id: kind, project_id: "p", workflow_run_id: "w", artifact_kind: kind, revision_no: 1, supersedes_version_id: null, source_kind: "service", payload, content_hash: kind, status: "draft" };
}

function snapshot(status: DirectorWorkspaceSnapshot["workflow"]["status"]): DirectorWorkspaceSnapshot {
  return {
    project_id: "project-1",
    project_name: "试拍作品",
    aspect_ratio: "9:16",
    workflow: { id: "workflow-1", project_id: "project-1", template_id: "live_action_dialogue_short", template_version: "1.0.0", status, current_stage: status.includes("trial") ? "trial" : "production", current_artifact_versions: {}, version: 4 },
    current_artifacts: {
      trial_plan: artifact("trial_plan", { representative_shot_id: "shot-2", selection_reason: "正面对话最容易暴露问题", quality_dimensions: ["identity", "mouth_motion"] }),
      cost_estimate: artifact("cost_estimate", {
        pricing_snapshot_id: "prices-1", currency: "CNY",
        trial: [{ purpose: "video", quantity: 1, unit_amount: "1.00", estimated_amount: "1.00", currency: "CNY", status: "known" }],
        production: [{ purpose: "video", quantity: 4, unit_amount: "1.00", estimated_amount: "4.00", currency: "CNY", status: "known" }],
        repair: [], trial_total: "1.00", production_total: "4.00", repair_total: "0.00", requires_user_budget_limit: true, disclaimer: "估算并非最终账单",
      }),
    },
    approvals: [], budget_authorizations: [], pending_changes: [], issues: [], step_runs: [], production_batches: [], budget_reservations: [], latest_delivery: null, allowed_actions: [], next_action: "",
  };
}

function renderWithQuery(ui: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
}

afterEach(() => vi.restoreAllMocks());

describe("Director trial and production stages", () => {
  it("shows a budget gate before exposing the trial materialization action", () => {
    renderWithQuery(<TrialStage projectId="project-1" snapshot={snapshot("awaiting_trial_authorization")} refresh={vi.fn()} onMessage={vi.fn()} onError={vi.fn()} />);
    expect(screen.getByTestId("trial-budget-panel")).toHaveTextContent("1.00 CNY");
    expect(screen.getByRole("button", { name: "确认并授权试拍预算" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "开始代表镜头试拍" })).not.toBeInTheDocument();
  });

  it("recovers a trial batch and enables inspection only when all batch runs are terminal", async () => {
    const value = snapshot("trial_running");
    value.production_batches = [{ id: "batch-1", batch_kind: "trial", status: "running", budget_authorization_id: "budget-1", locked_version_refs: {}, selected_shot_ids: ["shot-2"], template_keys: ["keyframe", "video"], quality_policy_id: "live-dialogue-quality-v1", selection_snapshot: {}, semantic_hash: "hash" }];
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ project_id: "project-1", name: "试拍作品", artifacts: [], node_runs: [{ id: "run-1", status: "completed", result_artifact_id: null, output_summary: {}, input_snapshot: { production_batch_id: "batch-1" }, idempotency_key: "run", attempt_no: 1, node_key: "video", provider_cost: "1.00", started_at: null, finished_at: null, error_code: null, error_summary: null, upstream_dependencies: [] }] }), { status: 200, headers: { "Content-Type": "application/json" } }));
    renderWithQuery(<TrialStage projectId="project-1" snapshot={value} refresh={vi.fn()} onMessage={vi.fn()} onError={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "运行已结束，生成质量报告" })).toBeEnabled();
  });

  it("shows formal pricing and keeps production materialization behind a separate budget action", () => {
    renderWithQuery(<ProductionStage projectId="project-1" snapshot={snapshot("awaiting_production_authorization")} refresh={vi.fn()} onMessage={vi.fn()} onError={vi.fn()} />);
    expect(screen.getByTestId("production-budget-panel")).toHaveTextContent("4.00 CNY");
    expect(screen.getByRole("button", { name: "确认并授权正式生产预算" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "开始正式生产" })).not.toBeInTheDocument();
  });

  it("shows repair changes and keeps repair materialization behind a separate extra-budget confirmation", () => {
    const value = snapshot("awaiting_repair_authorization");
    value.current_artifacts.repair_plan = artifact("repair_plan", {
      batch_id: "batch-1",
      quality_report_version_id: "quality-1",
      additional_budget_required: true,
      options: [{
        repair_option_id: "repair-0123456789ab",
        title: "强化人物锚点",
        diagnosis: "人物身份漂移",
        affected_shot_ids: ["shot-2"],
        invalidated_node_keys: ["keyframe", "video"],
        reusable_artifact_ids: [],
        changes: [{ target: "reference", summary: "重新注入角色参考图", preview_before_ref: null, preview_after_ref: null }],
        estimated_cost: "1.50",
        currency: "CNY",
        estimated_time_seconds: 90,
        residual_risks: ["表演仍需验收"],
      }],
    });
    renderWithQuery(<ProductionStage projectId="project-1" snapshot={value} refresh={vi.fn()} onMessage={vi.fn()} onError={vi.fn()} />);
    expect(screen.getByText("人物身份漂移")).toBeInTheDocument();
    expect(screen.queryByTestId("repair-budget-panel")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "选择这个方案" }));
    expect(screen.getByTestId("repair-budget-panel")).toHaveTextContent("1.50 CNY");
    expect(screen.getByRole("button", { name: "授权额外预算并开始局部修复" })).toBeDisabled();
  });
});
