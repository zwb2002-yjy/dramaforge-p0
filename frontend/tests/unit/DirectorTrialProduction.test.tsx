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
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ project_id: "project-1", name: "试拍作品", artifacts: [], provider_operations: [], node_runs: [{ id: "run-1", status: "completed", result_artifact_id: null, output_summary: {}, input_snapshot: { production_batch_id: "batch-1" }, idempotency_key: "run", attempt_no: 1, node_key: "video", provider_cost: "1.00", started_at: null, finished_at: null, error_code: null, error_summary: null, upstream_dependencies: [] }] }), { status: 200, headers: { "Content-Type": "application/json" } }));
    renderWithQuery(<TrialStage projectId="project-1" snapshot={value} refresh={vi.fn()} onMessage={vi.fn()} onError={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "运行已结束，生成质量报告" })).toBeEnabled();
  });

  it("renders real trial media, temporal frames, and sanitized Unified execution evidence", async () => {
    const value = snapshot("awaiting_trial_review");
    value.production_batches = [{ id: "batch-1", batch_kind: "trial", status: "running", budget_authorization_id: "budget-1", locked_version_refs: {}, selected_shot_ids: ["shot-2"], template_keys: ["dialogue-post-dub-shot-v1"], quality_policy_id: "live-dialogue-quality-v1", selection_snapshot: {}, semantic_hash: "hash" }];
    const runs = [
      ["canonical-run", "character_1", "canonical-artifact", "character_reference"],
      ["keyframe-run", "keyframe", "keyframe-artifact", "keyframe"],
      ["video-run", "video", "video-artifact", "video"],
      ["voice-run", "voice", "voice-artifact", "voice"],
    ].map(([id, nodeKey, artifactId, purpose]) => ({ id, status: "completed", result_artifact_id: artifactId, output_summary: {}, input_snapshot: { production_batch_id: "batch-1", source_commit: "acaa6c4f602adb49a1c0bded22d48560acd35bc1", purpose }, idempotency_key: id, attempt_no: 1, node_key: nodeKey, provider_cost: "0", started_at: null, finished_at: null, error_code: null, error_summary: null, upstream_dependencies: [] }));
    const artifact = (id: string, runId: string, mimeType: string) => ({ id, object_key: `projects/project-1/${id}`, content_hash: `${id}-sha256`, byte_size: 1024, mime_type: mimeType, storage_state: "available", produced_by_run_id: runId, width: mimeType.startsWith("video/") ? 720 : mimeType.startsWith("image/") ? 736 : null, height: mimeType.startsWith("video/") ? 1280 : mimeType.startsWith("image/") ? 1312 : null, duration_seconds: mimeType.startsWith("video/") ? "5.042" : null });
    const operation = (id: string, runId: string, model: string) => ({ id, node_run_id: runId, operation_kind: "media.generate", actual_provider: "agnes", actual_model: model, provider_request_id: `${id}-remote`, protocol_profile: "agnes_cn_v1", status: "succeeded", request_fingerprint: `${id}-fingerprint`, request_summary: { effective_request: { common_options: model.includes("video") ? { aspect_ratio: "9:16", frame_rate: 24, num_frames: 121, duration_seconds: 5, generate_audio: false } : { aspect_ratio: "9:16", size: "1K" }, reference_artifact_ids: ["canonical-artifact"], reference_fingerprints: ["canonical-sha256"] }, translation_report: { transformations: [], dropped_options: [] } }, response_summary: { cost_status: "not_reported", provider_reported_cost: null }, model_binding_id: `${id}-binding`, catalog_entry_id: `${id}-catalog`, capability_manifest_hash: `${id}-manifest`, execution_path_version: "unified-v1", provider_cost: null, currency: "CNY", submitted_at: null, completed_at: null });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      project_id: "project-1",
      name: "试拍作品",
      node_runs: runs,
      artifacts: [
        artifact("canonical-artifact", "canonical-run", "image/png"),
        artifact("keyframe-artifact", "keyframe-run", "image/png"),
        artifact("video-artifact", "video-run", "video/mp4"),
        artifact("voice-artifact", "voice-run", "audio/wav"),
      ],
      provider_operations: [
        operation("keyframe-operation", "keyframe-run", "agnes-image-2.1-flash"),
        operation("video-operation", "video-run", "agnes-video-v2.0"),
      ],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    renderWithQuery(<TrialStage projectId="project-1" snapshot={value} refresh={vi.fn()} onMessage={vi.fn()} onError={vi.fn()} />);

    expect(await screen.findByAltText("主角 Canonical")).toHaveAttribute("src", expect.stringContaining("canonical-artifact/content"));
    expect(screen.getByAltText("代表镜头关键帧")).toHaveAttribute("src", expect.stringContaining("keyframe-artifact/content"));
    expect(await screen.findByTestId("trial-video")).toHaveAttribute("src", expect.stringContaining("video-artifact/content"));
    expect(screen.getByTestId("trial-audio")).toHaveAttribute("src", expect.stringContaining("voice-artifact/content"));
    expect(screen.getByTestId("trial-video-frames").querySelectorAll("img")).toHaveLength(3);
    expect(screen.getByTestId("trial-media-evidence")).toHaveTextContent("24 fps · 121 帧 · 5.042 秒");
    expect(screen.getByTestId("trial-execution-evidence")).toHaveTextContent("unified-v1");
    expect(screen.getByTestId("trial-execution-evidence")).toHaveTextContent("Provider 未报告 · not_reported");
    expect(screen.getByTestId("trial-known-limitations")).toHaveTextContent("post-dub");
  });

  it("keeps trial evidence visible when the current quality report belongs to production", async () => {
    const value = snapshot("final_review");
    value.production_batches = [{ id: "trial-batch", batch_kind: "trial", status: "accepted", budget_authorization_id: "budget-1", locked_version_refs: {}, selected_shot_ids: ["shot-2"], template_keys: ["dialogue-post-dub-shot-v1"], quality_policy_id: "live-dialogue-quality-v1", selection_snapshot: {}, semantic_hash: "hash" }];
    value.current_artifacts.quality_report = artifact("quality_report", { policy_id: "live-dialogue-quality-v1", batch_id: "production-batch", overall_status: "warning", hard_blockers: [], shot_reports: [] });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ project_id: "project-1", name: "试拍作品", artifacts: [], provider_operations: [], node_runs: [] }), { status: 200, headers: { "Content-Type": "application/json" } }));

    renderWithQuery(<TrialStage projectId="project-1" snapshot={value} refresh={vi.fn()} onMessage={vi.fn()} onError={vi.fn()} />);

    expect(await screen.findByTestId("trial-media-evidence")).toBeInTheDocument();
    expect(screen.queryByTestId("trial-quality-report")).not.toBeInTheDocument();
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

  it("shows the repaired composite and cached lineage directly in final review", async () => {
    const value = snapshot("final_review");
    value.production_batches = [{ id: "repair-batch", batch_kind: "repair", status: "running", budget_authorization_id: "repair-budget", locked_version_refs: {}, selected_shot_ids: ["shot-2"], template_keys: ["dialogue-post-dub-shot-v1"], quality_policy_id: "live-dialogue-quality-v1", selection_snapshot: {}, semantic_hash: "repair-hash" }];
    value.current_artifacts.quality_report = artifact("quality_report", {
      policy_id: "live-dialogue-quality-v1",
      batch_id: "repair-batch",
      overall_status: "needs_human",
      hard_blockers: [],
      shot_reports: [{
        policy_id: "live-dialogue-quality-v1",
        batch_id: "repair-batch",
        logical_shot_id: "shot-2",
        overall_status: "needs_human",
        hard_blockers: [],
        limitations: [],
        recommended_action: "review",
        dimensions: [],
      }],
    });
    const runs = [
      ["cached-canonical", "character_1", "canonical-artifact", "character_reference", "cached"],
      ["cached-keyframe", "keyframe", "keyframe-artifact", "keyframe", "cached"],
      ["video-run", "video", "video-artifact", "video", "completed"],
      ["cached-voice", "voice", "voice-artifact", "voice", "cached"],
      ["composite-run", "composite", "composite-artifact", "composite", "completed"],
    ].map(([id, nodeKey, artifactId, purpose, status]) => ({ id, status, result_artifact_id: artifactId, output_summary: {}, input_snapshot: { production_batch_id: "repair-batch", source_commit: "candidate", purpose }, idempotency_key: id, attempt_no: 1, node_key: nodeKey, provider_cost: "0", started_at: null, finished_at: null, error_code: null, error_summary: null, upstream_dependencies: [] }));
    const media = (id: string, runId: string, mimeType: string) => ({ id, object_key: `projects/project-1/${id}`, content_hash: `${id}-sha256`, byte_size: 1024, mime_type: mimeType, storage_state: "available", produced_by_run_id: runId, width: mimeType.startsWith("video/") ? 704 : 736, height: mimeType.startsWith("video/") ? 1280 : 1312, duration_seconds: mimeType.startsWith("video/") ? "5.042" : null });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      project_id: "project-1",
      name: "试拍作品",
      node_runs: runs,
      artifacts: [
        media("canonical-artifact", "old-canonical-run", "image/png"),
        media("keyframe-artifact", "old-keyframe-run", "image/png"),
        media("video-artifact", "video-run", "video/mp4"),
        media("voice-artifact", "old-voice-run", "audio/wav"),
        media("composite-artifact", "composite-run", "video/mp4"),
      ],
      provider_operations: [{
        id: "video-operation", node_run_id: "video-run", operation_kind: "video.generate", actual_provider: "agnes", actual_model: "agnes-video-v2.0", provider_request_id: "remote-video", protocol_profile: "agnes_cn_v1", status: "succeeded", request_fingerprint: "fingerprint", request_summary: { effective_request: { common_options: { aspect_ratio: "9:16", frame_rate: 24, num_frames: 121, duration_seconds: 5, generate_audio: false }, reference_artifact_ids: ["keyframe-artifact"] }, translation_report: { transformations: [], dropped_options: [] } }, response_summary: { cost_status: "not_reported" }, model_binding_id: "video-binding", catalog_entry_id: "video-catalog", capability_manifest_hash: "video-manifest", execution_path_version: "unified-v1", provider_cost: null, currency: "USD", submitted_at: null, completed_at: null,
      }],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));

    renderWithQuery(<ProductionStage projectId="project-1" snapshot={value} refresh={vi.fn()} onMessage={vi.fn()} onError={vi.fn()} />);

    expect(await screen.findByTestId("repair-media-evidence")).toHaveTextContent("本次局部修复及其明确复用血缘");
    expect(screen.getByAltText("主角 Canonical")).toHaveAttribute("src", expect.stringContaining("canonical-artifact/content"));
    expect(screen.getByTestId("repair-video")).toHaveAttribute("src", expect.stringContaining("composite-artifact/content"));
    expect(screen.getByTestId("repair-audio")).toHaveAttribute("src", expect.stringContaining("voice-artifact/content"));
    expect(screen.getByTestId("repair-video-frames").querySelectorAll("img")).toHaveLength(3);
    expect(screen.getByTestId("repair-execution-evidence")).toHaveTextContent("video.generate · succeeded");
    expect(screen.getByTestId("repair-execution-evidence")).toHaveTextContent("Provider 未报告 · not_reported");
  });
});
