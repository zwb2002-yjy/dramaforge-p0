import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { queryKeys } from "../../lib/queryKeys";
import { reviewTargetHref } from "../review/reviewTarget";
import { fetchProductionTodos, type ProductionTodo } from "./batchApi";

const CATEGORY_LABEL: Record<ProductionTodo["category"], string> = {
  not_generated: "尚未生成",
  generating: "生成中 / 已排队",
  awaiting_review: "已有候选，待审片",
  awaiting_formal: "已通过，待设为正式",
  failed: "失败待处理",
};

function TodoLink({
  projectId,
  item,
  children,
}: {
  projectId: string;
  item: ProductionTodo;
  children: ReactNode;
}) {
  const review = item.category === "awaiting_review" || item.category === "awaiting_formal";
  if (item.category === "awaiting_review" && item.artifact_id) {
    return (
      <a
        href={reviewTargetHref(projectId, {
          shotId: item.shot_id,
          artifactId: item.artifact_id,
          stage: item.stage === "image_keyframe" ? "formal_keyframe" : "formal_video",
          reviewKind: item.stage === "image_keyframe" ? "identity" : "video_drift",
        })}
      >
        {children}
      </a>
    );
  }
  return (
    <Link
      to="/projects/$projectId/scenes/$sceneId"
      params={{ projectId, sceneId: item.scene_id }}
      search={{
        shotId: item.shot_id,
        tool: review ? undefined : "generate",
        review: review ? true : undefined,
      }}
    >
      {children}
    </Link>
  );
}

export function ProductionTodoQueue({ projectId }: { projectId: string }) {
  const query = useQuery({
    queryKey: queryKeys.production.todos(projectId),
    queryFn: () => fetchProductionTodos(projectId),
    enabled: Boolean(projectId),
    refetchInterval: 10_000,
  });
  const items = Array.isArray(query.data?.items) ? query.data.items : [];
  const counts =
    query.data?.counts && typeof query.data.counts === "object" ? query.data.counts : {};
  const risks = Array.isArray(query.data?.consistency_risks) ? query.data.consistency_risks : [];
  return (
    <section className="panel" data-testid="production-todo-queue" aria-label="制作待办队列">
      <header className="panel-header">
        <div>
          <h2>制作待办</h2>
          <p className="muted">按服务端事实分类，点击后直接定位下一条镜头。</p>
        </div>
        <strong>{items.length} 项</strong>
      </header>
      {query.isPending ? (
        <p role="status">正在分类镜头状态…</p>
      ) : query.isError ? (
        <p role="alert">待办状态读取失败；不会把未知状态当作未生成。</p>
      ) : (
        <>
          <div className="monitor-filters" role="group" aria-label="待办分类">
            {(Object.keys(CATEGORY_LABEL) as ProductionTodo["category"][]).map((key) => (
              <span key={key}>
                {items.find((item) => item.category === key) ? (
                  <TodoLink
                    projectId={projectId}
                    item={items.find((item) => item.category === key)!}
                  >
                    {CATEGORY_LABEL[key]} {counts[key] ?? 0} · 处理下一条
                  </TodoLink>
                ) : (
                  <span aria-disabled="true">
                    {CATEGORY_LABEL[key]} {counts[key] ?? 0}
                  </span>
                )}
              </span>
            ))}
          </div>
          {items.length ? (
            <ul className="dense">
              {items.slice(0, 20).map((item) => {
                const label = `镜头 ${item.shot_number} · ${
                  item.stage === "image_keyframe" ? "关键帧" : "视频"
                } · ${CATEGORY_LABEL[item.category]}`;
                return (
                  <li key={`${item.stage}:${item.shot_id}`}>
                    <TodoLink projectId={projectId} item={item}>
                      {label}
                    </TodoLink>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p role="status">当前分类没有待处理镜头。</p>
          )}
          <section aria-label="跨镜头一致性风险" data-testid="continuity-risk-queue">
            <h3>跨镜头一致性风险 {risks.length}</h3>
            <p className="muted">
              汇总自动连续性检查与同场景时代 / 色调 / 画幅的明确冻结事实，并标记相邻正式
              关键帧完全重复风险；缺失事实、服装和空间变化不会被简单字符串比较误判。
            </p>
            {risks.length ? (
              <ul className="dense">
                {risks.slice(0, 20).map((risk, index) => (
                  <li key={`${risk.code}:${risk.shot_id}:${index}`}>
                    <Link
                      to="/projects/$projectId/scenes/$sceneId"
                      params={{ projectId, sceneId: risk.scene_id }}
                      search={{ shotId: risk.shot_id, tool: undefined, review: true }}
                    >
                      {risk.layer} · {risk.message}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p role="status">当前没有已记录的一致性风险。</p>
            )}
          </section>
        </>
      )}
    </section>
  );
}
