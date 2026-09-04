import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ProductionMonitor } from "../features/production/ProductionMonitor";
import { ProfessionalWorkbench } from "../features/production/ProfessionalWorkbench";
import { WorkflowNavigator } from "../features/production/WorkflowNavigator";
import { CreativeCapabilitiesPanel } from "../features/production/CreativeCapabilitiesPanel";
import { fetchScenes } from "../features/scenes/api";
import { createShotExecution } from "../features/shots/api";
import {
  confirmShotChangeProposal,
  createExperiment,
  createProjectAsset,
  createReviewAnnotation,
  createShotChangeProposal,
  decideExperiment,
  fetchDirectorBoard,
  fetchExperiments,
  fetchOpenCutManifest,
  fetchProjectAssets,
  fetchProjectShots,
  fetchReviewAnnotations,
  fetchShotCanvasRevisions,
  fetchSnapshot,
  listModels,
  saveDirectorBoard,
  startExperiment,
  updateProjectAsset,
  updateShotCanvas,
} from "../lib/api";
import type { ProjectSnapshot } from "../lib/api";
import { queryKeys } from "../lib/queryKeys";
import { zhNode } from "../lib/zh";

const NODES = [
  "prompt",
  "keyframe",
  "identity_review",
  "video",
  "video_drift_review",
  "voice",
  "subtitle",
  "composite",
  "continuity_review",
] as const;

function nodeRailForRuns(runs: ProjectSnapshot["node_runs"]): Record<string, string> {
  const map: Record<string, string> = {};
  const completed = runs.filter((run) =>
    ["completed", "cached", "completed_after_cancel"].includes(run.status),
  ).length;
  for (const node of NODES) {
    const matching = runs.filter((run) => {
      const input = run.input_snapshot ?? {};
      const summary = run.output_summary ?? {};
      const key = String(
        run.node_key ??
          input.node_key ??
          summary.node_key ??
          summary.node_type ??
          summary.node_name ??
          summary.kind ??
          "",
      );
      return key === node || key.includes(node);
    });
    if (matching.some((run) => run.status === "failed")) map[node] = "fail";
    else if (matching.some((run) => ["queued", "running", "leased"].includes(run.status)))
      map[node] = "run";
    else if (
      matching.some((run) => ["completed", "cached", "completed_after_cancel"].includes(run.status))
    )
      map[node] = "done";
    else map[node] = "";
  }

  if (!Object.values(map).some(Boolean) && runs.length > 0) {
    const ratio = completed / runs.length;
    NODES.forEach((node, index) => {
      if (index / NODES.length < ratio) map[node] = "done";
    });
    if (runs.some((run) => run.status === "failed")) {
      map[NODES[Math.min(NODES.length - 1, Math.floor(ratio * NODES.length))]] = "fail";
    }
    if (runs.some((run) => ["queued", "running", "leased"].includes(run.status))) {
      map[NODES[Math.min(NODES.length - 1, Math.ceil(ratio * NODES.length))]] = "run";
    }
  }
  return map;
}

export function ProductionPage({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string | null>(null);
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);

  const snapshot = useQuery({
    queryKey: queryKeys.production.snapshot(projectId),
    queryFn: () => fetchSnapshot(projectId),
    enabled: projectId !== "demo",
    refetchInterval: 4000,
  });
  const shots = useQuery({
    queryKey: queryKeys.shot.list(projectId),
    queryFn: () => fetchProjectShots(projectId),
    enabled: projectId !== "demo",
  });
  const scenes = useQuery({
    queryKey: queryKeys.scene.list(projectId),
    queryFn: () => fetchScenes(projectId),
    enabled: projectId !== "demo",
  });

  const revisionShotId = selectedShotId ?? shots.data?.[0]?.id ?? null;
  const selectedShot = (shots.data ?? []).find((s) => s.id === revisionShotId) ?? null;
  const selectedSceneId = selectedShot?.scene_id ?? null;
  const projectAssets = useQuery({
    queryKey: queryKeys.asset.root(projectId),
    queryFn: () => fetchProjectAssets(projectId),
    enabled: projectId !== "demo",
  });
  const experiments = useQuery({
    queryKey: queryKeys.experiment.list(projectId),
    queryFn: () => fetchExperiments(projectId),
    enabled: projectId !== "demo",
  });
  const directorBoard = useQuery({
    queryKey: queryKeys.director.board(projectId, revisionShotId),
    queryFn: () => fetchDirectorBoard(projectId, revisionShotId!),
    enabled: projectId !== "demo" && Boolean(revisionShotId),
  });
  const reviewAnnotations = useQuery({
    queryKey: queryKeys.review.annotations(projectId, revisionShotId),
    queryFn: () => fetchReviewAnnotations(projectId, revisionShotId!),
    enabled: projectId !== "demo" && Boolean(revisionShotId),
  });
  const availableModels = useQuery({
    queryKey: queryKeys.model.catalog(),
    queryFn: () => listModels(),
  });
  const openCutManifest = useQuery({
    queryKey: queryKeys.production.opencutManifest(projectId),
    queryFn: () => fetchOpenCutManifest(projectId),
    enabled: projectId !== "demo",
  });
  const canvasRevisions = useQuery({
    queryKey: queryKeys.production.canvasRevisions(projectId, revisionShotId),
    queryFn: () => fetchShotCanvasRevisions(projectId, revisionShotId!),
    enabled: projectId !== "demo" && Boolean(revisionShotId),
  });

  const runs = useMemo(() => snapshot.data?.node_runs ?? [], [snapshot.data?.node_runs]);
  const nodeRailClass = useMemo(() => nodeRailForRuns(runs), [runs]);

  async function runShotOp(
    label: string,
    fn: () => Promise<{ status: string; message: string }>,
    shotId: string | null = selectedShotId,
  ) {
    if (!shotId) return;
    setMsg(null);
    try {
      const r = await fn();
      setMsg(`${label}: ${r.status} — ${r.message}`);
      await qc.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) });
      await qc.invalidateQueries({ queryKey: queryKeys.production.snapshot(projectId) });
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div data-testid="production-mode">
      <div className="page-title-row">
        <div>
          <h2 style={{ margin: 0 }}>跨场景生产监控</h2>
          <p className="muted" style={{ margin: "0.25rem 0 0" }}>
            场景、镜头、资产、生产链、审片与交付共享同一 Project 事实源；实际制作在场景工作区完成
          </p>
        </div>
      </div>

      <div className="callout">
        此处监控 Project 生产全貌（NodeRun / Artifact / 正式结果 /
        实验）。剧本导入与旧分镜主工作区已迁移到场景工作区；媒体生成、修复和导出仍受用户确认、Provider
        能力和质量门控制。
      </div>

      <WorkflowNavigator projectId={projectId} />

      {revisionShotId && (
        <CreativeCapabilitiesPanel
          projectId={projectId}
          sceneId={selectedSceneId}
          shotId={revisionShotId}
        />
      )}

      <ProductionMonitor
        projectId={projectId}
        scenes={Array.isArray(scenes.data) ? scenes.data : []}
        shots={shots.data ?? []}
        snapshot={snapshot.data}
        experimentCount={Array.isArray(experiments.data) ? experiments.data.length : 0}
      />

      <ProfessionalWorkbench
        projectId={projectId}
        shots={shots.data ?? []}
        snapshot={snapshot.data}
        revisions={canvasRevisions.data ?? []}
        assets={Array.isArray(projectAssets.data) ? projectAssets.data : []}
        experiments={Array.isArray(experiments.data) ? experiments.data : []}
        annotations={Array.isArray(reviewAnnotations.data) ? reviewAnnotations.data : []}
        openCutManifest={openCutManifest.data}
        models={Array.isArray(availableModels.data) ? availableModels.data : []}
        directorBoard={directorBoard.data}
        selectedShotId={selectedShotId}
        onSelectShot={setSelectedShotId}
        onCreateAsset={async (input) => {
          await createProjectAsset(projectId, {
            kind: input.kind,
            name: input.name,
            description: input.description,
            metadata: { tags: input.tags },
            status: "active",
          });
          await qc.invalidateQueries({ queryKey: queryKeys.asset.root(projectId) });
        }}
        onUpdateAsset={async (asset, input) => {
          await updateProjectAsset(projectId, asset.id, {
            expected_version: asset.version,
            kind: asset.kind,
            name: asset.name,
            description: asset.description,
            metadata: asset.metadata,
            status: input.status,
          });
          await qc.invalidateQueries({ queryKey: queryKeys.asset.root(projectId) });
        }}
        onCreateExperiment={async (input) => {
          await createExperiment(projectId, {
            idempotency_key: `experiment-${Date.now()}-${input.name}`,
            name: input.name,
            source_shot_id: revisionShotId,
            selected_model: input.selected_model,
            parameters: { target_node_key: "video" },
          });
          await qc.invalidateQueries({ queryKey: queryKeys.experiment.list(projectId) });
        }}
        onStartExperiment={async (experimentId, targetNodeKey) => {
          await startExperiment(projectId, experimentId, targetNodeKey);
          await qc.invalidateQueries({ queryKey: queryKeys.experiment.list(projectId) });
          await qc.invalidateQueries({ queryKey: queryKeys.production.snapshot(projectId) });
        }}
        onDecideExperiment={async (experimentId, input) => {
          await decideExperiment(projectId, experimentId, input);
          await qc.invalidateQueries({ queryKey: queryKeys.experiment.list(projectId) });
          await qc.invalidateQueries({ queryKey: queryKeys.production.snapshot(projectId) });
          await qc.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) });
        }}
        onCreateAnnotation={async (input) => {
          if (!revisionShotId) return;
          await createReviewAnnotation(projectId, revisionShotId, input);
          await qc.invalidateQueries({
            queryKey: queryKeys.review.annotations(projectId, revisionShotId),
          });
        }}
        onSaveDirectorBoard={async (input) => {
          if (!revisionShotId) return;
          await saveDirectorBoard(projectId, revisionShotId, {
            expected_version: directorBoard.data?.version ?? null,
            ...input,
          });
          await qc.invalidateQueries({
            queryKey: queryKeys.director.board(projectId, revisionShotId),
          });
        }}
        onStart={(shotId) =>
          void runShotOp(
            "生成关键帧",
            async () => {
              const shot = (shots.data ?? []).find((item) => item.id === shotId);
              if (!shot) throw new Error("镜头不存在");
              const result = await createShotExecution(
                projectId,
                shotId,
                {
                  stage: "image_keyframe",
                  prompt: shot.visual_description,
                  semantic_intent: { intent: "shot_keyframe", shot_id: shotId },
                  mode_id: "text_to_image",
                  requested_model_id: null,
                  requested_binding_id: null,
                  accept_approximations: false,
                  references: [],
                  expected_shot_version: shot.version,
                },
                `production-start-${shotId}-${shot.version}`,
              );
              return { status: result.status, message: `NodeRun ${result.node_run_id}` };
            },
            shotId,
          )
        }
        onRerun={(shotId) =>
          void runShotOp(
            "局部重跑视频",
            async () => {
              const shot = (shots.data ?? []).find((item) => item.id === shotId);
              if (!shot) throw new Error("镜头不存在");
              const result = await createShotExecution(
                projectId,
                shotId,
                {
                  stage: "video",
                  prompt: shot.visual_description,
                  semantic_intent: { intent: "shot_video", shot_id: shotId },
                  mode_id: "first_frame",
                  requested_model_id: null,
                  requested_binding_id: null,
                  accept_approximations: false,
                  references: [],
                  expected_shot_version: shot.version,
                },
                `production-rerun-${shotId}-${shot.version}`,
              );
              return { status: result.status, message: `NodeRun ${result.node_run_id}` };
            },
            shotId,
          )
        }
        onSave={async (shot, input) => {
          const result = await updateShotCanvas(projectId, shot.id, {
            expected_version: shot.version,
            visual_description: input.visual_description,
            shot_type: input.shot_type,
            camera_move: input.camera_move,
            dialogue: input.dialogue,
            duration_seconds: input.duration_seconds,
            source: "user",
          });
          await qc.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) });
          await qc.invalidateQueries({ queryKey: queryKeys.production.snapshot(projectId) });
          await qc.invalidateQueries({
            queryKey: queryKeys.production.canvasRevisions(projectId, shot.id),
          });
          return result;
        }}
        onPropose={async (shot, input) =>
          createShotChangeProposal(projectId, shot.id, {
            idempotency_key: `canvas-${shot.id}-${shot.version}-${input.summary}`,
            summary: input.summary,
            expected_version: shot.version,
            replacement_payload: input.replacement_payload,
            affected_node_keys: input.affected_node_keys,
            reusable_artifact_ids: input.reusable_artifact_ids,
          })
        }
        onConfirmProposal={(shotId, proposalId) =>
          confirmShotChangeProposal(projectId, shotId, proposalId).then(() => undefined)
        }
      />

      <div className="pipeline-rail" aria-label="shot-p0-v1">
        {NODES.map((n) => (
          <span key={n} className={`pipeline-node ${nodeRailClass[n] ?? ""}`}>
            {zhNode(n)}
          </span>
        ))}
      </div>

      {msg && (
        <div className="flash ok" data-testid="production-msg">
          {msg}
        </div>
      )}
    </div>
  );
}
