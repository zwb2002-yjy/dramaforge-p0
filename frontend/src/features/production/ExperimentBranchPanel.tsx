import { useMemo, useState } from "react";

import type { ExperimentRead, ModelRead } from "../../lib/api";
import { Button } from "../../components/ui";
import { candidateModelKey, type ModelCandidateRead } from "./modelCandidatesApi";
import {
  EXPERIMENT_STAGE_LABEL,
  EXPERIMENT_STAGE_ORDER,
  EXPERIMENT_STAGE_SHORT_LABEL,
  certificationNotice,
  experimentErrorDetail,
  experimentErrorMessage,
  experimentStageOf,
  modelIssueLabels,
  type ExperimentStage,
} from "./experimentStage";

const EXPERIMENT_STATUS_LABEL: Record<string, string> = {
  proposed: "待选择",
  running: "运行中",
  accepted: "已采用",
  rejected: "已拒绝",
  kept: "已保留",
};

/**
 * A stored vocabulary value the UI does not recognise must not be printed on an
 * ordinary surface; the raw value stays in the collapsed diagnostics blocks.
 */
function vocabularyLabel(labels: Record<string, string>, value: string, fallback: string): string {
  const key = (value ?? "").trim();
  if (!key) return fallback;
  return labels[key] ?? fallback;
}

export type ExperimentBranchPanelProps = {
  projectId: string;
  experiments?: ExperimentRead[];
  models?: ModelRead[];
  /**
   * Project-scoped eligibility for the experiment target, from the same engine
   * the runtime resolver uses, grouped by the stage the experiment branches.
   * An absent group means "unknown" (the read is still loading or failed) and
   * never blocks, while an empty group means "this stage has no binding".
   */
  modelCandidates?: Partial<Record<ExperimentStage, ModelCandidateRead[] | undefined>>;
  onCreateExperiment?: (input: {
    name: string;
    selected_model: string;
    targetNodeKey: ExperimentStage;
  }) => Promise<void>;
  onStartExperiment?: (experimentId: string, targetNodeKey: ExperimentStage) => Promise<void>;
  onDecideExperiment?: (
    experimentId: string,
    input: {
      decision: "accepted" | "rejected" | "kept";
      adoption_scope?: "current_node" | "keyframe_keep_video" | "keyframe_rerun_downstream";
      candidate_artifact_id?: string | null;
    },
  ) => Promise<void>;
};

/**
 * Formal line versus experimental line.
 *
 * This is the only workbench surface the application still mounts: the old
 * canvas/asset/review tabs were unreachable dead code and were deleted
 * (decision 2026-09-19), while the canonical Scene workspace owns design
 * editing. The wrapper keeps the `professional-workbench` test id the routes and
 * end-to-end journeys assert.
 */
export function ExperimentBranchPanel({
  projectId,
  experiments = [],
  models = [],
  modelCandidates = {},
  onCreateExperiment,
  onStartExperiment,
  onDecideExperiment,
}: ExperimentBranchPanelProps) {
  const [experimentName, setExperimentName] = useState("");
  const [experimentModel, setExperimentModel] = useState("");
  // Keyframe is the default because it is the stage whose adoption scopes
  // (keep video / rerun downstream) the product offers beyond "replace this
  // node"; the choice stays explicit and visible in the form.
  const [experimentStage, setExperimentStage] = useState<ExperimentStage>("keyframe");
  const [experimentNotice, setExperimentNotice] = useState<string | null>(null);
  const [experimentError, setExperimentError] = useState<string | null>(null);
  const [experimentErrorRaw, setExperimentErrorRaw] = useState<unknown>(null);
  const [experimentBusy, setExperimentBusy] = useState(false);

  const experimentModelRecord = models.find((model) => model.id === experimentModel);
  const stageCandidates = modelCandidates[experimentStage];
  const candidateByModel = useMemo(() => {
    const map = new Map<string, ModelCandidateRead>();
    for (const candidate of stageCandidates ?? []) {
      // The catalog names a model "provider/model"; the candidate view splits
      // the two, so index both spellings to keep matching exact.
      map.set(candidateModelKey(candidate), candidate);
      map.set(candidate.model_id, candidate);
    }
    return map;
  }, [stageCandidates]);
  const selectedCandidate = experimentModel
    ? (candidateByModel.get(experimentModel) ?? null)
    : null;
  const selectedIneligible = Boolean(selectedCandidate && !selectedCandidate.eligible);
  // Only a known-empty candidate list proves the model cannot branch this
  // stage; an unloaded list must not lock the form.
  const selectedHasNoBinding = Boolean(experimentModel && stageCandidates && !selectedCandidate);
  const candidateArtifactIds = (item: ExperimentRead): string[] =>
    item.candidate_artifact_ids ?? [];

  /**
   * Run one experiment action, keeping the failure on the product surface.
   *
   * `start` re-resolves the frozen binding for the experiment's stage, so a
   * model without a binding for that stage is refused there; without this the
   * Owner only saw an unchanged panel and a console error.
   */
  async function runExperimentAction(
    stage: ExperimentStage,
    action: () => Promise<void>,
    done: string,
  ) {
    setExperimentBusy(true);
    setExperimentNotice(null);
    setExperimentError(null);
    setExperimentErrorRaw(null);
    try {
      await action();
      setExperimentNotice(done);
    } catch (error) {
      setExperimentError(experimentErrorMessage(error, stage));
      setExperimentErrorRaw(error);
    } finally {
      setExperimentBusy(false);
    }
  }
  async function createExperimentBranch() {
    if (!onCreateExperiment) return;
    await runExperimentAction(
      experimentStage,
      async () => {
        await onCreateExperiment({
          name: experimentName.trim(),
          selected_model: experimentModel.trim(),
          targetNodeKey: experimentStage,
        });
        setExperimentName("");
        setExperimentModel("");
      },
      `实验分支已创建：${EXPERIMENT_STAGE_SHORT_LABEL[experimentStage]}阶段，运行后生成对照候选。`,
    );
  }

  return (
    <section
      className="professional-workbench"
      data-testid="professional-workbench"
      data-project-id={projectId}
    >
      <section className="panel experiment-branch-panel" data-testid="experiment-branches">
        <div className="panel-header">
          <div>
            <h3>尝试不同版本</h3>
          </div>
          <strong>{experiments.length} 个实验</strong>
        </div>
        <div className="director-professional-columns">
          <section>
            <h4>实验分支</h4>
            {(experimentNotice || experimentError) && (
              <p
                data-testid="experiment-message"
                className={experimentError ? "status-bad" : "status-ok"}
              >
                {experimentError ?? experimentNotice}
              </p>
            )}
            <ul className="dense">
              {experiments.map((item) => {
                const candidates = candidateArtifactIds(item);
                const targetNodeKey = experimentStageOf(item.parameters.target_node_key);
                const firstCandidate = candidates[0] ?? null;
                const runStates = Array.isArray(item.comparison?.run_states)
                  ? item.comparison.run_states
                  : [];
                return (
                  <li key={item.id} className="experiment-row">
                    <div>
                      <strong>{item.name}</strong>
                      <small data-testid={`experiment-stage-${item.id}`}>
                        {EXPERIMENT_STAGE_SHORT_LABEL[targetNodeKey]}阶段 ·{" "}
                        {item.selected_model ?? "未选模型"} ·{" "}
                        {vocabularyLabel(EXPERIMENT_STATUS_LABEL, item.status, "状态待同步")} · 候选{" "}
                        {candidates.length}
                      </small>
                      {runStates.length > 0 && <small>执行证据：{runStates.length} 次运行</small>}
                    </div>
                    <div className="suggestion-actions">
                      <Button
                        tone="ghost"
                        disabled={
                          experimentBusy ||
                          !onStartExperiment ||
                          item.status === "accepted" ||
                          item.status === "rejected"
                        }
                        onClick={() =>
                          void runExperimentAction(
                            targetNodeKey,
                            async () => {
                              await onStartExperiment?.(item.id, targetNodeKey);
                            },
                            `实验已提交运行：${EXPERIMENT_STAGE_SHORT_LABEL[targetNodeKey]}阶段，完成后在这里对比候选。`,
                          )
                        }
                      >
                        运行实验
                      </Button>
                      <Button
                        tone="primary"
                        disabled={
                          experimentBusy ||
                          !onDecideExperiment ||
                          !firstCandidate ||
                          item.status === "accepted" ||
                          item.status === "rejected"
                        }
                        onClick={() =>
                          void runExperimentAction(
                            targetNodeKey,
                            async () => {
                              await onDecideExperiment?.(item.id, {
                                decision: "accepted",
                                adoption_scope:
                                  targetNodeKey === "keyframe"
                                    ? "keyframe_rerun_downstream"
                                    : "current_node",
                                candidate_artifact_id: firstCandidate,
                              });
                            },
                            "已采用该候选；后续生成会以它为新的事实源。",
                          )
                        }
                      >
                        采纳候选
                      </Button>
                      <Button
                        tone="ghost"
                        disabled={
                          experimentBusy ||
                          !onDecideExperiment ||
                          item.status === "accepted" ||
                          item.status === "rejected"
                        }
                        onClick={() =>
                          void runExperimentAction(
                            targetNodeKey,
                            async () => {
                              await onDecideExperiment?.(item.id, { decision: "kept" });
                            },
                            "已保留实验，正式结果不变。",
                          )
                        }
                      >
                        保留实验
                      </Button>
                      <Button
                        tone="ghost"
                        disabled={
                          experimentBusy ||
                          !onDecideExperiment ||
                          item.status === "accepted" ||
                          item.status === "rejected"
                        }
                        onClick={() =>
                          void runExperimentAction(
                            targetNodeKey,
                            async () => {
                              await onDecideExperiment?.(item.id, { decision: "rejected" });
                            },
                            "已拒绝该实验，正式结果不变。",
                          )
                        }
                      >
                        拒绝
                      </Button>
                    </div>
                  </li>
                );
              })}
              {experiments.length === 0 && <li className="muted">正式结果不会被实验覆盖</li>}
            </ul>
          </section>
          <section>
            <h4>创建模型实验</h4>
            <div className="asset-create-form">
              <input
                aria-label="实验名称"
                value={experimentName}
                onChange={(event) => setExperimentName(event.target.value)}
                placeholder="例如：换模型验证转头稳定性"
              />
              <select
                aria-label="实验阶段"
                value={experimentStage}
                onChange={(event) => setExperimentStage(experimentStageOf(event.target.value))}
              >
                {EXPERIMENT_STAGE_ORDER.map((stage) => (
                  <option key={stage} value={stage}>
                    {EXPERIMENT_STAGE_LABEL[stage]}
                  </option>
                ))}
              </select>
              <select
                aria-label="实验模型"
                value={experimentModel}
                onChange={(event) => setExperimentModel(event.target.value)}
              >
                <option value="">选择模型</option>
                {models.map((model) => {
                  // Two hard stops remain: no binding for the chosen stage, and a
                  // binding the eligibility engine refuses. Quality certification is
                  // evidence, not a stop: an uncertified binding is selectable and
                  // labelled so the Owner knows what formal support evidence is
                  // still missing.
                  const candidate = candidateByModel.get(model.id) ?? null;
                  return (
                    <option
                      key={model.id}
                      value={model.id}
                      disabled={Boolean(stageCandidates && (!candidate || !candidate.eligible))}
                    >
                      {model.display_name}
                      {candidate
                        ? candidate.eligible
                          ? candidate.certified
                            ? " · 可用"
                            : " · 未认证"
                          : " · 不可用"
                        : stageCandidates
                          ? ` · 无${EXPERIMENT_STAGE_SHORT_LABEL[experimentStage]}阶段绑定`
                          : ""}
                    </option>
                  );
                })}
              </select>
              {experimentModelRecord && (
                <small>动态能力：{experimentModelRecord.capabilities.join(" · ")}</small>
              )}
              {selectedCandidate && (
                <small
                  data-testid="experiment-model-eligibility"
                  className={selectedCandidate.eligible ? "status-ok" : "status-bad"}
                >
                  {selectedCandidate.eligible
                    ? `该模型可用于${EXPERIMENT_STAGE_SHORT_LABEL[experimentStage]}阶段${
                        selectedCandidate.certified
                          ? "，并已通过质量验收。"
                          : `；${certificationNotice()}`
                      }`
                    : `该模型不可用于${EXPERIMENT_STAGE_SHORT_LABEL[experimentStage]}阶段：${
                        selectedCandidate.issues.length
                          ? modelIssueLabels(selectedCandidate.issues.map((issue) => issue.code))
                          : selectedCandidate.unmet_preferences.length
                            ? selectedCandidate.unmet_preferences.join("；")
                            : "未满足资格条件"
                      }。`}
                </small>
              )}
              {selectedHasNoBinding && (
                <small data-testid="experiment-model-eligibility" className="status-bad">
                  该模型没有可用于{EXPERIMENT_STAGE_SHORT_LABEL[experimentStage]}
                  阶段的绑定，请改选阶段或模型。
                </small>
              )}
              {experimentError && (
                <details data-testid="experiment-error-diagnostics">
                  <summary>开发 / 诊断详情（只读）</summary>
                  <small>{experimentErrorDetail(experimentErrorRaw)}</small>
                </details>
              )}
              <Button
                tone="primary"
                disabled={
                  experimentBusy ||
                  !experimentName.trim() ||
                  !experimentModel.trim() ||
                  !onCreateExperiment ||
                  selectedIneligible ||
                  selectedHasNoBinding
                }
                onClick={() => void createExperimentBranch()}
              >
                创建实验分支
              </Button>
            </div>
          </section>
        </div>
      </section>
    </section>
  );
}
