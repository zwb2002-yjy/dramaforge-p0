import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Field, Select, Tab, Tabs, PageHeader } from "../components/ui";
import { useState } from "react";

import { fetchProductionSummary } from "../features/production/api";
import { ProductionHistoryPanel } from "../features/production/ProductionHistoryPanel";
import { ProductionMonitor } from "../features/production/ProductionMonitor";
import { ExperimentBranchPanel } from "../features/production/ExperimentBranchPanel";
import { WorkflowNavigator } from "../features/production/WorkflowNavigator";
import { CreativeCapabilitiesPanel } from "../features/production/CreativeCapabilitiesPanel";
import { listModelCandidates } from "../features/production/modelCandidatesApi";
import { fetchScenes } from "../features/scenes/api";
import {
  createExperiment,
  decideExperiment,
  fetchExperiments,
  fetchProjectShots,
  listModels,
  startExperiment,
} from "../lib/api";
import { queryKeys } from "../lib/queryKeys";

export function ProductionPage({ projectId }: { projectId: string }) {
  const qc = useQueryClient();
  const [view, setView] = useState("progress");
  const [overrideScope, setOverrideScope] = useState<"scene" | "shot">("scene");
  const views = [
    { id: "progress", label: "作品进度" },
    { id: "workflow", label: "生成任务" },
    { id: "experiments", label: "版本尝试" },
    { id: "advanced", label: "导演手法" },
  ];
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);

  const summary = useQuery({
    queryKey: queryKeys.production.summary(projectId),
    queryFn: ({ signal }) => fetchProductionSummary(projectId, signal),
    enabled: projectId !== "demo",
    refetchInterval: (query) => ((query.state.data?.running_runs ?? 0) > 0 ? 4000 : 30000),
  });
  const shots = useQuery({
    queryKey: queryKeys.shot.list(projectId),
    queryFn: () => fetchProjectShots(projectId),
    enabled: projectId !== "demo",
    refetchInterval: 30000,
  });
  const scenes = useQuery({
    queryKey: queryKeys.scene.list(projectId),
    queryFn: () => fetchScenes(projectId),
    enabled: projectId !== "demo",
    refetchInterval: 30000,
  });

  const revisionShotId = selectedShotId ?? shots.data?.[0]?.id ?? null;
  const selectedShot = (shots.data ?? []).find((s) => s.id === revisionShotId) ?? null;
  const selectedSceneId = selectedShot?.scene_id ?? null;
  // Scene scope is the shared configuration for the Scene; it falls back to
  // the first Scene so the Owner can configure it before any Shot exists.
  const [chosenSceneId, setChosenSceneId] = useState<string | null>(null);
  const firstSceneId = scenes.data?.[0]?.id ?? null;
  const sceneCapabilityId =
    projectId === "demo" ? null : (chosenSceneId ?? selectedSceneId ?? firstSceneId ?? null);
  const experiments = useQuery({
    queryKey: queryKeys.experiment.list(projectId),
    queryFn: () => fetchExperiments(projectId),
    enabled: projectId !== "demo",
  });
  const availableModels = useQuery({
    queryKey: queryKeys.model.catalog(),
    queryFn: () => listModels(),
  });
  // Eligibility is per stage: an image model has a keyframe binding, a video
  // model has a video binding, and an experiment may branch either stage. Both
  // views come from the same engine the runtime resolver uses.
  const keyframeCandidates = useQuery({
    queryKey: queryKeys.model.candidates(projectId, "image.generate"),
    queryFn: () => listModelCandidates(projectId, "image.generate"),
    enabled: projectId !== "demo",
  });
  const videoCandidates = useQuery({
    queryKey: queryKeys.model.candidates(projectId, "video.generate"),
    queryFn: () => listModelCandidates(projectId, "video.generate"),
    enabled: projectId !== "demo",
  });

  return (
    <div data-testid="production-mode">
      <PageHeader title="作品总览" description="查看作品现状，从下一步继续创作。" />

      <Tabs label="制作内容">
        {views.map((item) => (
          <Tab
            key={item.id}
            id={`production-tab-${item.id}`}
            active={view === item.id}
            aria-controls={`production-panel-${item.id}`}
            tabIndex={view === item.id ? 0 : -1}
            onClick={() => setView(item.id)}
          >
            {item.label}
          </Tab>
        ))}
      </Tabs>
      <section
        id="production-panel-progress"
        role="tabpanel"
        aria-labelledby="production-tab-progress"
        hidden={view !== "progress"}
      >
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
        <ProductionHistoryPanel projectId={projectId} />
      </section>
      <section
        id="production-panel-workflow"
        role="tabpanel"
        aria-labelledby="production-tab-workflow"
        hidden={view !== "workflow"}
      >
        <WorkflowNavigator projectId={projectId} />
      </section>
      <section
        id="production-panel-advanced"
        role="tabpanel"
        aria-labelledby="production-tab-advanced"
        hidden={view !== "advanced"}
      >
        <p className="muted">默认沿用项目选择，仅在个别画面需要不同效果时修改。</p>
        <Field className="df-field">
          修改范围
          <Select
            aria-label="修改范围"
            value={overrideScope}
            onChange={(event) => setOverrideScope(event.target.value as "scene" | "shot")}
          >
            <option value="scene">整个场景</option>
            <option value="shot">单个镜头</option>
          </Select>
        </Field>
        <div hidden={overrideScope !== "scene"}>
          {sceneCapabilityId && (
            <section>
              {(scenes.data?.length ?? 0) > 1 && (
                <Field className="df-field">
                  场景
                  <Select
                    aria-label="场景创作能力目标场景"
                    value={sceneCapabilityId}
                    onChange={(e) => setChosenSceneId(e.target.value)}
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
                scope="scene"
              />
            </section>
          )}
        </div>
        <div hidden={overrideScope !== "shot"}>
          <Field className="df-field">
            镜头
            <Select
              aria-label="设置目标镜头"
              value={revisionShotId ?? ""}
              onChange={(event) => setSelectedShotId(event.target.value)}
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
              />
            </section>
          )}
        </div>
        {!sceneCapabilityId && !revisionShotId && <p>先在剧本页准备故事，再到这里调整具体画面。</p>}
      </section>
      <section
        id="production-panel-experiments"
        role="tabpanel"
        aria-labelledby="production-tab-experiments"
        hidden={view !== "experiments"}
      >
        <Field className="df-field">
          尝试哪个镜头
          <Select
            aria-label="实验目标镜头"
            value={revisionShotId ?? ""}
            onChange={(event) => setSelectedShotId(event.target.value)}
          >
            {(shots.data ?? []).map((shot) => (
              <option key={shot.id} value={shot.id}>
                镜头 {shot.shot_number}
              </option>
            ))}
          </Select>
        </Field>
        <ExperimentBranchPanel
          projectId={projectId}
          experiments={Array.isArray(experiments.data) ? experiments.data : []}
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
            ].join("|");
            await createExperiment(projectId, {
              idempotency_key: `experiment:${identity}`,
              name: input.name,
              source_shot_id: revisionShotId,
              selected_model: input.selected_model,
              // The stage is part of the experiment's identity: it selects the
              // model purpose and which adoption scopes the branch can offer.
              parameters: { target_node_key: input.targetNodeKey },
            });
            await qc.invalidateQueries({ queryKey: queryKeys.experiment.list(projectId) });
          }}
          onStartExperiment={async (experimentId, targetNodeKey) => {
            await startExperiment(projectId, experimentId, targetNodeKey);
            await qc.invalidateQueries({ queryKey: queryKeys.experiment.list(projectId) });
            await qc.invalidateQueries({ queryKey: queryKeys.production.snapshot(projectId) });
            await qc.invalidateQueries({ queryKey: queryKeys.production.summary(projectId) });
          }}
          onDecideExperiment={async (experimentId, input) => {
            await decideExperiment(projectId, experimentId, input);
            await qc.invalidateQueries({ queryKey: queryKeys.experiment.list(projectId) });
            await qc.invalidateQueries({ queryKey: queryKeys.production.snapshot(projectId) });
            await qc.invalidateQueries({ queryKey: queryKeys.production.summary(projectId) });
            await qc.invalidateQueries({ queryKey: queryKeys.shot.list(projectId) });
          }}
        />
      </section>
    </div>
  );
}
