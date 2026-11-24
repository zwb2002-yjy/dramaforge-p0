import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card } from "../../components/ui";
import { listBusinessFlowAttempts, listBusinessFlowSteps, listBusinessFlows } from "./api";

const labels: Record<string, string> = {
  proposal: "提案",
  artifact: "产物",
  asset_version: "素材版本",
  node_run: "执行任务",
  export: "导出",
  shot_prompt_review: "镜头提示词审查",
  scene_prompt_review: "场景提示词审查",
  shot_model_contract_review: "镜头模型核对",
  project_asset_audit: "项目素材核对",
  episode_delivery: "分集交付",
  episode_arrangement: "分集安排",
  read_shot: "读取镜头",
  read_scene: "读取场景",
  list_shots: "列出镜头",
  propose_prompt: "提出提示词修改",
  read_capabilities: "核对模型能力",
  compile_preview: "预览模型输入",
  list_assets: "列出素材",
  read_asset: "查看素材",
  collect_exports: "核对导出文件",
  apply_episodes: "采纳分集",
  pending: "待开始",
  running: "进行中",
  waiting: "等待中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  ready: "可执行",
  flow_progress_pending: "等待流程推进",
  blocked: "受阻",
  unknown_submission: "提交结果未知",
};
const label = (value: string) => labels[value] ?? value;

function usePage<T>(
  key: string[],
  fetchPage: (
    offset: number,
    signal: AbortSignal,
  ) => Promise<{ items: T[]; next_offset: number | null }>,
) {
  return useInfiniteQuery({
    queryKey: key,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => fetchPage(pageParam, signal),
    getNextPageParam: (last) => last.next_offset ?? undefined,
    retry: false,
  });
}

function PageActions({
  page,
}: {
  page: {
    isPending: boolean;
    isError: boolean;
    isFetching: boolean;
    hasNextPage: boolean;
    fetchNextPage: () => Promise<unknown>;
    refetch: () => Promise<unknown>;
  };
}) {
  return (
    <>
      {page.isPending && <p role="status">正在读取…</p>}
      {page.isError && (
        <p role="alert">
          读取失败。<Button onClick={() => void page.refetch()}>重试</Button>
        </p>
      )}
      {page.hasNextPage && (
        <Button disabled={page.isFetching} onClick={() => void page.fetchNextPage()}>
          更多记录
        </Button>
      )}
    </>
  );
}

function Attempts({
  projectId,
  flowId,
  stepId,
}: {
  projectId: string;
  flowId: string;
  stepId: string;
}) {
  const page = usePage(["business-flow-attempts", projectId, flowId, stepId], (offset, signal) =>
    listBusinessFlowAttempts(projectId, flowId, stepId, offset, signal),
  );
  const rows = page.data?.pages.flatMap((p) => p.items);
  return (
    <>
      <ul aria-label="执行尝试">
        {rows?.map((r) => (
          <li key={r.id}>
            第 {r.attempt_no} 次 · {label(r.status)} {r.error_code && `（${r.error_code}）`}
            {r.unresolved_external && <span> · 外部提交结果待核对</span>}
            {r.receipt && (
              <p>
                执行回执 · {label(r.receipt.status)} · {r.receipt.node_run_id}
              </p>
            )}
            {r.result_refs.length > 0 && <p>结果数量 {r.result_refs.length}</p>}
          </li>
        ))}
      </ul>
      {rows?.length === 0 && <p>尚无执行记录。</p>}
      <PageActions page={page} />
    </>
  );
}

function Steps({ projectId, flowId }: { projectId: string; flowId: string }) {
  const [selected, setSelected] = useState<string | null>(null);
  const page = usePage(["business-flow-steps", projectId, flowId], (offset, signal) =>
    listBusinessFlowSteps(projectId, flowId, offset, signal),
  );
  return (
    <>
      <ul className="business-flow-steps">
        {page.data?.pages
          .flatMap((p) => p.items)
          .map((s) => (
            <li key={s.id}>
              <Button
                tone="ghost"
                aria-expanded={selected === s.id}
                onClick={() => setSelected(selected === s.id ? null : s.id)}
              >
                {label(s.step_key)} · {label(s.status)}
                {s.wait_reason ? `（${label(s.wait_reason)}）` : ""}
              </Button>
              {selected === s.id && (
                <>
                  {s.dependencies.length > 0 && (
                    <p>依赖步骤：{s.dependencies.map(label).join("、")}</p>
                  )}
                  {s.result_refs.length > 0 && (
                    <ul aria-label="步骤结果">
                      {s.result_refs.map((ref) => (
                        <li key={ref.kind + ref.id}>{ref.display_name}</li>
                      ))}
                    </ul>
                  )}
                  <Attempts projectId={projectId} flowId={flowId} stepId={s.id} />
                </>
              )}
            </li>
          ))}
      </ul>
      <PageActions page={page} />
    </>
  );
}

export function BusinessFlowPanel({ projectId, runId }: { projectId: string; runId: string }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const page = usePage(["business-flows", projectId, runId], (offset, signal) =>
    listBusinessFlows(projectId, runId, offset, signal),
  );
  const flows = page.data?.pages.flatMap((p) => p.items);
  return (
    <Card aria-label="业务流程">
      <div className="panel-header">
        <h3>业务流程</h3>
        <Button
          tone="ghost"
          disabled={page.isFetching}
          onClick={() => {
            setExpanded(null);
            void page.refetch();
          }}
        >
          刷新
        </Button>
      </div>
      {flows?.length === 0 && <p>当前目标还没有业务流程。</p>}
      <ul className="business-flow-list">
        {flows?.map((f) => (
          <li key={f.id}>
            <Button
              tone="ghost"
              aria-expanded={expanded === f.id}
              onClick={() => setExpanded(expanded === f.id ? null : f.id)}
            >
              {label(f.definition_key)} · {label(f.status)}
              {f.wait_reason ? `（${label(f.wait_reason)}）` : ""}
            </Button>
            {expanded === f.id && <Steps projectId={projectId} flowId={f.id} />}
          </li>
        ))}
      </ul>
      <PageActions page={page} />
    </Card>
  );
}
