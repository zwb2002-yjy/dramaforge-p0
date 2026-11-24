import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ActionLink, Alert, Badge, Button, Disclosure } from "../../components/ui";
import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import type { components } from "../../shared/api/generated";
import { applyDirectorAgentProposal } from "./api";
import { BusinessFlowPanel } from "./BusinessFlowPanel";

type Goal = components["schemas"]["RunRead"];
type Plan = components["schemas"]["PlanRead"];
type Page = components["schemas"]["RunPage"];
type Receipt = components["schemas"]["ControlReceipt"];

const statuses: Record<string, string> = {
  planning: "等待计划",
  waiting: "等待核验",
  running: "进行中",
  paused: "已暂停",
  succeeded: "已完成",
  cancelled: "已取消",
  failed: "未完成",
  stopping: "正在停止",
};
const reasons: Record<string, string> = {
  STORY_EPISODE_CHANGED: "已采纳分集的版本有变化",
  STORY_RECEIPT_INVALID: "分集采纳回执无效",
  STORY_EPISODE_APPLY_MISSING: "还有分集未按计划采纳",
  DELIVERY_OUTPUT_SLOT_UNAVAILABLE: "计划交付步骤不可用",
  DELIVERY_PLAN_EXPORT_MISSING: "此剪辑版本尚未按本计划导出",
  DELIVERY_EPISODE_MISSING: "分集不存在",
  DELIVERY_SESSION_MISSING: "尚未保存剪辑",
  DELIVERY_CURRENT_EXPORT_MISSING: "当前剪辑尚无对应成片",
  DELIVERY_TIMELINE_CHANGED: "剪辑版本已改变",
  DELIVERY_MP4_MISSING: "缺少可用视频",
  DELIVERY_SRT_MISSING: "缺少可用字幕",
  DELIVERY_SRT_MISMATCH: "字幕与导出回执不符",
  DELIVERY_ITEMS_INCOMPLETE: "导出片段记录不完整",
  DELIVERY_RENDER_MISMATCH: "渲染与剪辑版本不符",
  DELIVERY_RESULT_MISMATCH: "导出结果不一致",
  DELIVERY_WORK_TYPE_CHANGED: "项目作品类型已改变",
  DELIVERY_EPISODE_COUNT_MISMATCH: "项目计划集数已改变",
  PLAN_INPUT_CHANGED: "计划所依据的版本已变化",
  DELIVERY_EPISODE_CHANGED: "分集安排已变化",
};
const base = (projectId: string) => `/api/v1/projects/${projectId}/director/master-runs`;

function GoalDetail({ projectId, goal }: { projectId: string; goal: Goal }) {
  const client = useQueryClient();
  const plans = useQuery({
    queryKey: [...queryKeys.director.goals(projectId), goal.id, "plans"],
    queryFn: ({ signal }) =>
      apiGet<Plan[]>(`${base(projectId)}/${goal.id}/plans?limit=1`, undefined, signal),
    retry: false,
  });
  const plan = plans.data?.[0];
  const check = plan?.delivery_check;
  const decide = useMutation({
    mutationFn: async (action: "accepted" | "rejected" | "verify") => {
      if (action === "verify")
        return apiSend<Receipt>(
          "POST",
          `${base(projectId)}/${goal.id}/verify`,
          { expected_revision: goal.revision },
          await fetchCsrf(),
        );
      if (!plan) throw new Error("请先读取计划");
      const result = await applyDirectorAgentProposal(projectId, plan.proposal_id, {
        decisions: [{ item_id: plan.decision_ref, decision: action }],
      });
      if (!result[action]?.includes(plan.decision_ref))
        throw new Error(String(result.failed?.[0]?.error ?? "计划已变化，请重新查看"));
      return null;
    },
    onSettled: () => client.invalidateQueries({ queryKey: queryKeys.director.goals(projectId) }),
  });
  return (
    <article aria-label={goal.goal}>
      <strong>{goal.goal}</strong> <Badge>{statuses[goal.status] ?? goal.status}</Badge>
      {plans.isError && <p role="alert">无法读取计划</p>}
      {check && (
        <p>
          计划 v{plan.revision} · 核对 MP4 和字幕 ·{" "}
          {check.output_slot?.field === "episode_ids"
            ? `按剧本中实际采纳的第 1 至 ${check.planned_episode_count} 集核对交付`
            : check.output_slot
              ? `依次交付第 1 至 ${check.planned_episode_count} 集，逐集关联本计划导出`
              : (check.targets ?? [])
                  .map((t) =>
                    t.episode_id === null
                      ? "项目成片"
                      : t.episode_number
                        ? `第 ${t.episode_number} 集`
                        : t.episode_id,
                  )
                  .join("、")}
        </p>
      )}
      {check &&
        plan.decision_status === "pending" &&
        !["cancelled", "succeeded", "failed"].includes(goal.status) && (
          <>
            <Button disabled={decide.isPending} onClick={() => decide.mutate("accepted")}>
              确认核验计划
            </Button>
            <Button disabled={decide.isPending} onClick={() => decide.mutate("rejected")}>
              拒绝计划
            </Button>
          </>
        )}
      {plan?.decision_status === "rejected" && <p>此计划已拒绝</p>}
      {plan &&
        check?.output_slot?.field === "episode_exports" &&
        plan.decision_status === "accepted" &&
        goal.current_plan_id === plan.id &&
        goal.available_actions.includes("verify") && (
          <ActionLink
            tone="ghost"
            to="/projects/$projectId/edit"
            params={{ projectId }}
            search={{ sessionId: undefined, goalId: goal.id, planId: plan.id }}
          >
            按此计划导出分集
          </ActionLink>
        )}
      {plan &&
        check?.output_slot?.field === "episode_ids" &&
        goal.progress.completed_steps < goal.progress.required_steps &&
        plan.decision_status === "accepted" &&
        goal.current_plan_id === plan.id &&
        goal.available_actions.includes("verify") && (
          <ActionLink
            tone="ghost"
            to="/projects/$projectId/script"
            params={{ projectId }}
            search={{ goalId: goal.id, planId: plan.id, goalEpoch: goal.control_epoch }}
          >
            按此计划采纳分集
          </ActionLink>
        )}
      {goal.available_actions.includes("verify") && (
        <Button disabled={decide.isPending} onClick={() => decide.mutate("verify")}>
          核验已确认计划
        </Button>
      )}
      {decide.isError && <Alert type="error" role="alert" description={String(decide.error)} />}
      {goal.last_verification && (
        <div aria-label="上次核验结果">
          <strong>{goal.last_verification.satisfied ? "交付核验通过" : "交付核验待补齐"}</strong>
          {goal.last_verification.checks.map((entry, index) => (
            <div key={index}>
              {entry.reason_code && <p>{reasons[entry.reason_code] ?? entry.reason_code}</p>}
              {entry.missing_episode_ranges?.map(([first, last]) => (
                <p key={first}>
                  {first === last ? `第 ${first} 集` : `第 ${first}–${last} 集`} ·{" "}
                  {entry.reason_code?.startsWith("STORY_") ? "缺少有效采纳回执" : "尚未建立分集"}
                </p>
              ))}
              {entry.evidence_refs?.map((e, i) => (
                <p key={i}>
                  {e.episode_number
                    ? `第 ${e.episode_number} 集`
                    : e.episode_id
                      ? "指定分集"
                      : "项目成片"}{" "}
                  ·{" "}
                  {e.blockers.length
                    ? e.blockers.map((b) => reasons[b] ?? b).join("、")
                    : `v${e.timeline_version} · MP4 与字幕齐全`}
                </p>
              ))}
            </div>
          ))}
        </div>
      )}
      <Disclosure title="查看流程与执行记录" lazy compact>
        <BusinessFlowPanel projectId={projectId} runId={goal.id} />
      </Disclosure>
    </article>
  );
}

export function DeliveryGoals({ projectId }: { projectId: string }) {
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const goals = useQuery({
    queryKey: [...queryKeys.director.goals(projectId), "page", offset],
    queryFn: ({ signal }) =>
      apiGet<Page>(`${base(projectId)}?limit=10&offset=${offset}`, undefined, signal),
    retry: false,
  });
  const current = goals.data?.items.find((item) => item.id === selected) ?? goals.data?.items[0];
  return (
    <section aria-label="项目持续目标">
      {goals.isPending && <p role="status">正在读取目标…</p>}
      {goals.isError && <p role="alert">无法读取项目目标</p>}
      {goals.data?.items.length === 0 && <p>暂无持续目标</p>}
      {(goals.data?.items.length ?? 0) > 1 &&
        goals.data?.items.map((item) => (
          <Button
            key={item.id}
            aria-pressed={current?.id === item.id}
            onClick={() => setSelected(item.id)}
          >
            {item.goal}
          </Button>
        ))}
      {current && <GoalDetail key={current.id} goal={current} projectId={projectId} />}
      {offset > 0 && (
        <Button onClick={() => setOffset(Math.max(0, offset - 10))}>上一页目标</Button>
      )}
      {goals.data?.next_offset != null && (
        <Button onClick={() => setOffset(goals.data!.next_offset!)}>下一页目标</Button>
      )}
    </section>
  );
}
