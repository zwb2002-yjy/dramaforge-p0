import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Field, Select, SegmentedControl, Tabs, PageHeader } from "../components/ui";
import { useState } from "react";

import { fetchProductionSummary } from "../features/production/api";
import { ProductionHistoryPanel } from "../features/production/ProductionHistoryPanel";
import { ProductionMonitor } from "../features/production/ProductionMonitor";
import { BatchFillActions, ProductionTodoQueue } from "../features/production";
import { ExperimentBranchPanel } from "../features/production/ExperimentBranchPanel";
import { WorkflowNavigator } from "../features/production/WorkflowNavigator";
import { CreativeCapabilitiesPanel } from "../features/production/CreativeCapabilitiesPanel";
import { listModelCandidates } from "../features/production/modelCandidatesApi";
import { fetchShotWorkbench } from "../features/shots/api";
import { stageOutcomeUnknown } from "../features/production/sceneRunState";
import { fetchScenes } from "../features/scenes/api";
import { ApiError, getSelectedWorkspaceId } from "../lib/api";
import {
  createExperiment,
  decideExperiment,
  fetchExperiments,
  startExperiment,
} from "../features/production/api";
import { fetchProjectShots } from "../features/shots/api";
import { listModels } from "../features/model-controls/api";
import { queryKeys } from "../lib/queryKeys";
import { productionCopy as copy } from "../features/production/productionCopy";

export function ProductionPage({
  projectId,
  initialView,
  initialShotId,
}: {
  projectId: string;
  initialView?: "experiments";
  initialShotId?: string;
}) {
  const workspaceId = getSelectedWorkspaceId();
  const qc = useQueryClient();
  const [view, setView] = useState(initialView ?? "progress");
  const [overrideScope, setOverrideScope] = useState<"scene" | "shot">("scene");
  const [selectedShotId, setSelectedShotId] = useState<string | null>(initialShotId ?? null);

  const summary = useQuery({
    queryKey: queryKeys.production.summary(projectId),
    queryFn: ({ signal }) => fetchProductionSummary(projectId, signal),
    enabled: Boolean(projectId),
    refetchInterval: (query) => ((query.state.data?.running_runs ?? 0) > 0 ? 10000 : false),
  });
  const shots = useQuery({
    queryKey: queryKeys.shot.list(projectId),
    queryFn: () => fetchProjectShots(projectId),
    enabled: Boolean(projectId),
  });
  const scenes = useQuery({
    queryKey: queryKeys.scene.list(projectId),
    queryFn: () => fetchScenes(projectId),
    enabled: Boolean(projectId),
  });

  const revisionShotId = selectedShotId ?? shots.data?.[0]?.id ?? null;
  const selectedShot = (shots.data ?? []).find((s) => s.id === revisionShotId) ?? null;
  const selectedSceneId = selectedShot?.scene_id ?? null;
  // Scene scope is the shared configuration for the Scene; it falls back to
  // the first Scene so the Owner can configure it before any Shot exists.
  const [chosenSceneId, setChosenSceneId] = useState<string | null>(null);
  const firstSceneId = scenes.data?.[0]?.id ?? null;
  const sceneCapabilityId = chosenSceneId ?? selectedSceneId ?? firstSceneId ?? null;
  const experiments = useQuery({
    queryKey: queryKeys.experiment.list(projectId),
    queryFn: () => fetchExperiments(projectId),
    enabled: Boolean(projectId) && view === "experiments",
  });
  const availableModels = useQuery({
    queryKey: queryKeys.model.catalog(workspaceId),
    queryFn: ({ signal }) => listModels(undefined, workspaceId, signal),
    enabled: view === "experiments",
  });
  // Eligibility is per stage: an image model has a keyframe binding, a video
  // model has a video binding, and an experiment may branch either stage. Both
  // views come from the same engine the runtime resolver uses.
  const keyframeCandidates = useQuery({
    queryKey: queryKeys.model.candidates(projectId, "image.generate"),
    queryFn: () => listModelCandidates(projectId, "image.generate"),
    enabled: Boolean(projectId) && view === "experiments",
  });
  const videoCandidates = useQuery({
    queryKey: queryKeys.model.candidates(projectId, "video.generate"),
    queryFn: () => listModelCandidates(projectId, "video.generate"),
    enabled: Boolean(projectId) && view === "experiments",
  });

  return (
    <div className="production-workspace" data-testid="production-mode">
      <PageHeader title="项目总览" actions={<BatchFillActions projectId={projectId} />} />

      <Tabs
        label="制作内容"
        type="line"
        activeKey={view}
        onChange={setView}
        destroyOnHidden={false}
        items={copy.views.map((item) => ({
          key: item.id,
          label: item.label,
          children: {
            progress: (
              <section>
                <ProductionMonitor
                  projectId={projectId}
                  scenes={Array.isArray(scenes.data) ? scenes.data : []}
                  shots={shots.data ?? []}
                  summary={summary.data}
                  experimentCount={experiments.data?.length}
                  scenesLoading={scenes.isPending}
                  scenesError={scenes.isError}
                  shotsLoading={shots.isPending}
                  shotsError={shots.isError}
                  summaryError={summary.isError}
                  summaryFailure={summary.error}
                  onRetry={() => {
                    void scenes.refetch();
                    void shots.refetch();
                    void summary.refetch();
                  }}
                />
                <ProductionTodoQueue projectId={projectId} active={view === "progress"} />
                <ProductionHistoryPanel projectId={projectId} active={view === "progress"} />
              </section>
            ),
            workflow: (
              <section>
                <WorkflowNavigator projectId={projectId} active={view === "workflow"} />
              </section>
            ),
            advanced: (
              <section>
                <p className="muted">默认沿用项目选择，仅在个别画面需要不同效果时修改。</p>
                <SegmentedControl
                  label={copy.scopeLabel}
                  value={overrideScope}
                  onChange={setOverrideScope}
                  options={copy.scopes}
                />
                <div hidden={overrideScope !== "scene"}>
                  {sceneCapabilityId && (
                    <section>
                      {(scenes.data?.length ?? 0) > 1 && (
                        <Field>
                          场景
                          <Select
                            aria-label="场景创作能力目标场景"
                            value={sceneCapabilityId}
                            onChange={(e) => setChosenSceneId(e)}
                          >
                            {(scenes.data ?? []).map((scene) => (
                              <option key={scene.id} value={scene.id}>
                                {scene.location_name || `场景 ${scene.scene_number}`}
                              </option>
                            ))}
                          </Select>
                        </Field>
                      )}
                      <CreativeCapabilitiesPanel
                        projectId={projectId}
                        sceneId={sceneCapabilityId}
                        active={view === "advanced" && overrideScope === "scene"}
                        scope="scene"
                      />
                    </section>
                  )}
                </div>
                <div hidden={overrideScope !== "shot"}>
                  <Field>
                    镜头
                    <Select
                      aria-label="设置目标镜头"
                      value={revisionShotId ?? ""}
                      onChange={(event) => setSelectedShotId(event)}
                    >
                      {(shots.data ?? []).map((shot) => (
                        <option key={shot.id} value={shot.id}>
                          镜头 {shot.shot_number}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {revisionShotId && (
                    <section>
                      <CreativeCapabilitiesPanel
                        projectId={projectId}
                        sceneId={selectedSceneId}
                        shotId={revisionShotId}
                        active={view === "advanced" && overrideScope === "shot"}
                      />
                    </section>
                  )}
                </div>
                {!sceneCapabilityId && !revisionShotId && (
                  <p>先在剧本页准备故事，再到这里调整具体画面。</p>
                )}
              </section>
            ),
            experiments: (
              <section>
                <Field>
                  尝试哪个镜头
                  <Select
                    aria-label="实验目标镜头"
                    value={revisionShotId ?? ""}
                    onChange={(event) => setSelectedShotId(event)}
                  >
                    {(shots.data ?? []).map((shot) => (
                      <option key={shot.id} value={shot.id}>
                        镜头 {shot.shot_number}
                      </option>
                    ))}
                  </Select>
                </Field>
                <ExperimentBranchPanel
                  key={revisionShotId ?? "no-shot"}
                  projectId={projectId}
                  experiments={
                    Array.isArray(experiments.data)
                      ? experiments.data.filter((item) => item.source_shot_id === revisionShotId)
                      : []
                  }
                  models={Array.isArray(availableModels.data) ? availableModels.data : []}
                  modelCandidates={{
                    // `undefined` keeps "not loaded yet" distinct from "no binding".
                    keyframe: keyframeCandidates.data,
                    video: videoCandidates.data,
                  }}
                  onCreateExperiment={async (input) => {
                    // The key is derived from the experiment's identity, not from the
                    // clock: the server treats a repeated key as the same draft, so a
                    // double click or a retry cannot create a second branch that would
                    // later run (and bill) twice. A genuinely new experiment changes the
                    // name, stage, model or target shot.
                    const identity = [
                      revisionShotId ?? "no-shot",
                      input.targetNodeKey,
                      input.selected_model,
                      input.name,
                      input.promptOverride ?? "saved-shot-prompt",
                    ].join("|");
                    await createExperiment(projectId, {
                      idempotency_key: `experiment:${identity}`,
                      name: input.name,
                      source_shot_id: revisionShotId,
                      selected_model: input.selected_model,
                      // The stage is part of the experiment's identity: it selects the
                      // model purpose and which adoption scopes the branch can offer.
                      parameters: {
                        target_node_key: input.targetNodeKey,
                        ...(input.promptOverride ? { prompt_override: input.promptOverride } : {}),
                      },
                    });
                    await qc.invalidateQueries({ queryKey: queryKeys.experiment.list(projectId) });
                  }}
                  onStartExperiment={async (experimentId, targetNodeKey) => {
                    const experiment = experiments.data?.find((item) => item.id === experimentId);
                    if (!experiment?.source_shot_id) throw new Error("实验目标镜头不可用");
                    // A new variant is not a way around an unresolved paid submission.
                    // Re-read immediately before dispatch; a failed read fails closed.
                    const workbench = await fetchShotWorkbench(
                      projectId,
                      experiment.source_shot_id,
                    );
                    if (
                      stageOutcomeUnknown(
                        workbench.trace,
                        targetNodeKey === "keyframe" ? "image_keyframe" : "video",
                      )
                    ) {
                      throw new ApiError("该阶段提交结果待对账", 409, "SUBMISSION_OUTCOME_UNKNOWN");
                    }
                    await startExperiment(projectId, experimentId, targetNodeKey);
                    await qc.invalidateQueries({ queryKey: queryKeys.experiment.list(projectId) });
                    await qc.invalidateQueries({
                      queryKey: queryKeys.production.snapshot(projectId),
                    });
                    await qc.invalidateQueries({
                      queryKey: queryKeys.production.summary(projectId),
                    });
                  }}
                  onDecideExperiment={async (experimentId, input) => {
                    await decideExperiment(projectId, experimentId, input);
                    await qc.invalidateQueries({ queryKey: queryKeys.experiment.list(projectId) });
                    await qc.invalidateQueries({
                      queryKey: queryKeys.production.snapshot(projectId),
                    });
                    await qc.invalidateQueries({
                      queryKey: queryKeys.production.summary(projectId),
                    });
                    await qc.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) });
                  }}
                />
              </section>
            ),
          }[item.id],
        }))}
      />
    </div>
  );
}
