import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { reviewTargetHref } from "./reviewTarget";
import { queryKeys } from "../../lib/queryKeys";
import {
  REPAIR_OPTION_LABEL,
  createRepair,
  executeRepairStep,
  fetchRepairPlan,
  listRepairs,
  repairStageLabel,
  repairStepActionLabel,
  type RepairOption,
  type RepairRequestRead,
  type RepairStepRead,
} from "./repairApi";

type RepairPlanPanelProps = {
  projectId: string;
  shotId: string;
  /** Close the side panel. */
  onClose?: () => void;
};

function stepSummary(step: RepairStepRead): string {
  const parts = [`第 ${step.ordinal} 步 · ${repairStageLabel(step.stage)}`];
  if (step.node_run_status) parts.push(`运行状态 ${step.node_run_status}`);
  parts.push(repairStepActionLabel(step.next_action));
  return parts.join(" · ");
}

/**
 * Repair side panel: preview the plan, confirm one option, then walk its steps.
 *
 * Results come from the server's stored repair and its NodeRuns, so closing the
 * panel, refreshing or switching pages never loses the current step.
 */
export function RepairPlanPanel({ projectId, shotId, onClose }: RepairPlanPanelProps) {
  const queryClient = useQueryClient();
  const [option, setOption] = useState<RepairOption | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const confirmKey = useRef(`repair:${globalThis.crypto.randomUUID()}`);
  const stepKey = useRef(`repair-step:${globalThis.crypto.randomUUID()}`);

  const plan = useQuery({
    queryKey: queryKeys.review.repairPlan(projectId, shotId),
    queryFn: () => fetchRepairPlan(projectId, shotId),
    enabled: projectId !== "demo" && Boolean(shotId),
  });
  const repairs = useQuery({
    queryKey: queryKeys.review.repairs(projectId, shotId),
    queryFn: () => listRepairs(projectId, shotId),
    enabled: projectId !== "demo" && Boolean(shotId),
  });

  const selected: RepairOption =
    option ?? (plan.data?.suggested_option as RepairOption | undefined) ?? "rerun_video";
  const active = (repairs.data ?? []).find((item) => item.closed_reason === null) ?? null;

  const confirm = useMutation({
    mutationFn: async () => {
      if (!plan.data) throw new Error("修复计划尚未加载");
      return createRepair(projectId, shotId, {
        repair_option: selected,
        plan_hash: plan.data.plan_hash,
        idempotency_key: confirmKey.current,
      });
    },
    onSuccess: async (created) => {
      confirmKey.current = `repair:${globalThis.crypto.randomUUID()}`;
      setFeedback(`已确认修复计划；下一步：${repairStepActionLabel(created.next_action)}。`);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.review.repairs(projectId, shotId),
      });
    },
    onError: (error: unknown) => {
      setFeedback(`确认修复失败：${error instanceof Error ? error.message : String(error)}`);
      // A changed plan must be previewed again; refresh the preview.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.review.repairPlan(projectId, shotId),
      });
    },
  });

  const runStep = useMutation({
    mutationFn: (request: RepairRequestRead) =>
      executeRepairStep(projectId, shotId, request.id, {
        idempotency_key: stepKey.current,
      }),
    onSuccess: async (result) => {
      stepKey.current = `repair-step:${globalThis.crypto.randomUUID()}`;
      setFeedback(
        `已提交本步（运行 ${result.node_run_id.slice(0, 8)}）；下一步：${repairStepActionLabel(result.next_action)}。`,
      );
      await queryClient.invalidateQueries({
        queryKey: queryKeys.review.repairs(projectId, shotId),
      });
    },
    onError: (error: unknown) => {
      setFeedback(`提交本步失败：${error instanceof Error ? error.message : String(error)}`);
    },
  });

  return (
    <section className="qc-repair-panel" data-testid="repair-plan-panel">
      <header>
        <h3>创建修复计划</h3>
        {onClose && (
          <button type="button" className="secondary" onClick={onClose} data-testid="repair-close">
            关闭
          </button>
        )}
      </header>

      {plan.isError && (
        <p className="flash err" data-testid="repair-plan-error" role="alert">
          无法读取修复计划。
        </p>
      )}

      {plan.data && (
        <>
          <p className="muted" data-testid="repair-plan-summary">
            当前问题：{plan.data.annotation_count} 条待处理标注 · 影响节点
            {plan.data.affected_nodes.join("、") || "无"} · 保留素材
            {plan.data.retained_assets.join("、") || "无"}
          </p>
          <p className="muted" data-testid="repair-plan-cost">
            {plan.data.cost_estimate_note}
          </p>
          <fieldset data-testid="repair-options">
            <legend>修复选项</legend>
            {plan.data.repair_options.map((value) => (
              <label key={value}>
                <input
                  type="radio"
                  name="repair-option"
                  value={value}
                  checked={selected === value}
                  onChange={() => setOption(value as RepairOption)}
                  disabled={Boolean(active)}
                />
                {REPAIR_OPTION_LABEL[value as RepairOption] ?? value}
              </label>
            ))}
          </fieldset>
          <ol data-testid="repair-plan-steps">
            {plan.data.steps.map((stage) => (
              <li key={stage}>{repairStageLabel(stage)}</li>
            ))}
          </ol>
          <button
            type="button"
            data-testid="repair-confirm"
            disabled={confirm.isPending || Boolean(active)}
            onClick={() => confirm.mutate()}
          >
            确认修复计划
          </button>
        </>
      )}

      {active && (
        <div data-testid="repair-active" data-next-action={active.next_action}>
          <p>
            进行中的修复：{REPAIR_OPTION_LABEL[active.option] ?? active.option} · 下一步
            {repairStepActionLabel(active.next_action)}
          </p>
          <ol data-testid="repair-steps">
            {active.steps.map((step) => (
              <li key={step.id} data-testid={`repair-step-${step.ordinal}`}>
                {stepSummary(step)}
                {step.result_artifact_id &&
                  ["completed", "cached", "completed_after_cancel"].includes(
                    step.node_run_status ?? "",
                  ) &&
                  (step.stage === "keyframe_regenerate" || step.stage === "video_rerun") && (
                    <a
                      href={reviewTargetHref(projectId, {
                        shotId,
                        artifactId: step.result_artifact_id,
                        stage:
                          step.stage === "keyframe_regenerate" ? "formal_keyframe" : "formal_video",
                        reviewKind:
                          step.stage === "keyframe_regenerate" ? "identity" : "video_drift",
                        repairRequestId: active.id,
                        repairStepId: step.id,
                      })}
                    >
                      审查本步候选
                    </a>
                  )}
              </li>
            ))}
          </ol>
          {active.next_action === "human_decision" && (
            <p className="flash" data-testid="repair-review-hint" role="status">
              请等待本步生成完成，再通过“审查本步候选”检查对应结果。修复尚未完成。
            </p>
          )}
          {active.next_action === "execute_step" && (
            <button
              type="button"
              data-testid="repair-execute-step"
              disabled={runStep.isPending}
              onClick={() => runStep.mutate(active)}
            >
              生成下一步候选
            </button>
          )}
          {active.next_action === "closed" && (
            <p className="muted" data-testid="repair-finished">
              该修复已结束。
            </p>
          )}
        </div>
      )}

      {feedback && (
        <p className="muted" data-testid="repair-feedback" role="status">
          {feedback}
        </p>
      )}
      <p className="muted">修复不会自动覆盖正式版本，也不会自动关闭标注。</p>
    </section>
  );
}
