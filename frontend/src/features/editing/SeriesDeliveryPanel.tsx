import { useQuery } from "@tanstack/react-query";
import { ActionLink, Alert, Badge, Button, Card, SectionHeader } from "../../components/ui";
import { queryKeys } from "../../lib/queryKeys";
import { fetchEpisodeDeliveries } from "./api";

const labels: Record<string, string> = {
  DELIVERY_SESSION_MISSING: "尚未建立分集剪辑",
  DELIVERY_CURRENT_EXPORT_MISSING: "当前剪辑版本尚无成片",
  DELIVERY_RENDER_MISMATCH: "渲染记录与当前版本不符",
  DELIVERY_ITEMS_INCOMPLETE: "导出片段记录不完整",
  DELIVERY_MP4_MISSING: "缺少可用 MP4",
  DELIVERY_SRT_MISSING: "缺少可用字幕",
  DELIVERY_SRT_MISMATCH: "字幕与导出记录不符",
  DELIVERY_RESULT_MISMATCH: "成片与导出记录不符",
};

export function SeriesDeliveryPanel({ projectId }: { projectId: string }) {
  const query = useQuery({
    queryKey: queryKeys.editing.episodeDeliveries(projectId),
    queryFn: ({ signal }) => fetchEpisodeDeliveries(projectId, signal),
  });
  const summary = query.data?.summary;
  return (
    <Card aria-label="连续剧交付">
      <SectionHeader
        title="连续剧交付"
        actions={
          <Button disabled={query.isFetching} onClick={() => void query.refetch()}>
            刷新交付状态
          </Button>
        }
      >
        {summary && <Badge>{summary.ready ? "各集 MP4 与字幕齐全" : "待补齐"}</Badge>}
      </SectionHeader>
      {query.isPending && <p role="status">正在核对分集交付…</p>}
      {query.isError && <Alert type="error" description="无法读取分集交付记录" />}
      {summary && (
        <>
          <p>
            按每集最近保存的剪辑核对，已齐备 {summary.ready_episodes} 集
            {summary.planned_episodes != null && `，计划 ${summary.planned_episodes} 集`}。
          </p>
          {summary.planned_episodes == null && <p>尚未设置计划集数</p>}
          {summary.missing_episode_ranges.length > 0 && (
            <p>
              尚未建立分集：
              {summary.missing_episode_ranges
                .map(([a, b]) => (a === b ? `第 ${a} 集` : `第 ${a}–${b} 集`))
                .join("、")}
            </p>
          )}
          {summary.episodes.length > 0 && (
            <ul>
              {summary.episodes.map((episode) => (
                <li key={episode.episode_id}>
                  第 {episode.episode_number} 集
                  {episode.timeline_version != null && ` · v${episode.timeline_version}`} ·{" "}
                  {episode.blockers.length
                    ? episode.blockers.map((b) => labels[b] ?? b).join("、")
                    : "MP4 与字幕齐全"}
                  {summary.planned_episodes != null &&
                    episode.episode_number > summary.planned_episodes &&
                    " · 计划外分集"}
                  {episode.edit_session_id && (
                    <ActionLink
                      to="/projects/$projectId/edit"
                      params={{ projectId }}
                      search={{ sessionId: episode.edit_session_id }}
                      tone="ghost"
                    >
                      打开第 {episode.episode_number} 集剪辑
                    </ActionLink>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
