import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ProductionMonitor } from "../features/production/ProductionMonitor";
import { ProfessionalWorkbench } from "../features/production/ProfessionalWorkbench";
import { WorkflowNavigator } from "../features/production/WorkflowNavigator";
import { CreativeCapabilitiesPanel } from "../features/production/CreativeCapabilitiesPanel";
import { listModelCandidates } from "../features/production/modelCandidatesApi";
import { fetchScenes } from "../features/scenes/api";
import { createShotExecution } from "../features/shots/api";
import { recycleAsset, restoreAsset } from "../features/assets/api";
import {
  createExperiment,
  createProjectAsset,
  createReviewAnnotation,
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
  updateShotCanvas,
} from "../lib/api";
import type { ProjectSnapshot } from "../lib/api";
import { queryKeys } from "../lib/queryKeys";
import { nodeRunStatusLabel } from "../lib/runLabels";
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

function ProductionDetail({
  children,
  description,
  testId,
  title,
}: {
  children: ReactNode;
  description: string;
  testId: string;
  title: string;
}) {
  const [open, setOpen] = useState(() => window.innerWidth > 720);

  useEffect(() => {
    let wideViewport = window.innerWidth > 720;
    const resetForViewport = () => {
      const nextWideViewport = window.innerWidth > 720;
      if (nextWideViewport !== wideViewport) {
        wideViewport = nextWideViewport;
        setOpen(nextWideViewport);
      }
    };
    window.addEventListener("resize", resetForViewport);
    return () => window.removeEventListener("resize", resetForViewport);
  }, []);

  return (
    <details
      className="production-detail"
      data-testid={testId}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <span>
          <strong>{title}</strong>
          <small>{description}</small>
        </span>
        <ChevronDown size={18} aria-hidden="true" />
      </summary>
      <div className="production-detail-body">{children}</div>
    </details>
  );
}

export function ProductionPage({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [msg, setMsg] = useState<string | null>(null);
  const [msgTone, setMsgTone] = useState<"ok" | "err">("ok");
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
  const modelCandidates = useQuery({
    queryKey: queryKeys.model.candidates(projectId, "video.generate"),
    queryFn: () => listModelCandidates(projectId, "video.generate"),
    enabled: projectId !== "demo",
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
    setMsgTone("ok");
    try {
      const r = await fn();
      setMsg(`${label}：${nodeRunStatusLabel(r.status)} — ${r.message}`);
      await qc.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) });
      await qc.invalidateQueries({ queryKey: queryKeys.production.snapshot(projectId) });
    } catch (e) {
      setMsgTone("err");
      setMsg(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div data-testid="production-mode">
      <nav className="qc-local-tabs" aria-label="制作视图">
        <Link to="/projects/$projectId/production" params={{ projectId }} aria-current="page">
          生产概览
        </Link>
        <Link to="/projects/$projectId/review" params={{ projectId }}>
          待审内容
        </Link>
      </nav>
      <div className="page-title-row">
        <div>
          <h1 style={{ margin: 0 }}>跨场景生产监控</h1>
        </div>
      </div>

      <div className="callout">
        这里汇总全部场景的生产进度；单个镜头的实际制作在场景工作区完成，付费生成、修复与导出都需要你确认。
      </div>

      {msg && (
        <div
          className={`flash ${msgTone}`}
          data-testid="production-msg"
          role={msgTone === "err" ? "alert" : "status"}
        >
          {msg}
        </div>
      )}

      <ProductionMonitor
        projectId={projectId}
        scenes={Array.isArray(scenes.data) ? scenes.data : []}
        shots={shots.data ?? []}
        snapshot={snapshot.data}
        experimentCount={Array.isArray(experiments.data) ? experiments.data.length : 0}
      />

      <ProductionDetail
        title="镜头工作流"
        description="按场景查看镜头级进度"
        testId="production-workflow-disclosure"
      >
        <WorkflowNavigator projectId={projectId} />
      </ProductionDetail>

      {revisionShotId && (
        <ProductionDetail
          title="创意能力"
          description="调整当前镜头的创作策略"
          testId="production-capabilities-disclosure"
        >
          <CreativeCapabilitiesPanel
            projectId={projectId}
            sceneId={selectedSceneId}
            shotId={revisionShotId}
          />
        </ProductionDetail>
      )}

      <ProductionDetail
        title="高级镜头工具"
        description="资产、实验、审片与画布"
        testId="production-workbench-disclosure"
      >
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
          modelCandidates={Array.isArray(modelCandidates.data) ? modelCandidates.data : []}
          directorBoard={directorBoard.data}
          selectedShotId={selectedShotId}
          onSelectShot={setSelectedShotId}
          onCreateAsset={async (input) => {
            await createProjectAsset(projectId, {
              kind: input.kind,
              name: input.name,
              description: input.description,
              metadata: {},
              status: "active",
              tags: input.tags,
            });
            await qc.invalidateQueries({ queryKey: queryKeys.asset.root(projectId) });
          }}
          onUpdateAsset={async (asset, input) => {
            if (input.status === "recycled") await recycleAsset(projectId, asset.id);
            else await restoreAsset(projectId, asset.id);
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
        />

        <div className="pipeline-rail" aria-label="镜头生产链">
          {NODES.map((n) => (
            <span key={n} className={`pipeline-node ${nodeRailClass[n] ?? ""}`}>
              {zhNode(n)}
            </span>
          ))}
        </div>
      </ProductionDetail>
    </div>
  );
}
