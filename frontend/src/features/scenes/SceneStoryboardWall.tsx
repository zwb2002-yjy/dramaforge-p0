import { PageHeader, EmptyState, Button } from "../../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { SceneMediaGallery } from "./SceneMediaGallery";
import {
  SCENE_MEDIA_FILTERS as FILTERS,
  sceneMatchesFilter,
  type SceneMediaFilter,
} from "./sceneOverviewState";
import { SCENE_ACTIVE_REFETCH_MS } from "../production";
import "../resonance/resonance.css";
import "./scene-wall-surface.css";

import { queryKeys } from "../../lib/queryKeys";
import { timeOfDayLabel } from "../../lib/sceneLabels";
import { copyScene, fetchScenes, reorderScene } from "./api";

type SceneStoryboardWallProps = { projectId: string };
type WallSelection = { projectId: string; filter: SceneMediaFilter; sceneId: string | null };

function readSelection(projectId: string): WallSelection {
  const fallback: WallSelection = { projectId, filter: "all", sceneId: null };
  try {
    const raw = sessionStorage.getItem("df:scene-wall:" + projectId);
    if (!raw) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return fallback;
    const stored = parsed as Partial<WallSelection>;
    if (!FILTERS.some((row) => row.value === stored.filter)) return fallback;
    return {
      projectId,
      filter: stored.filter!,
      sceneId: typeof stored.sceneId === "string" ? stored.sceneId : null,
    };
  } catch {
    return fallback;
  }
}

/** Read-only Scene/Shot projection: one expanded scene avoids eager per-scene workspace requests. */
export function SceneStoryboardWall({ projectId }: SceneStoryboardWallProps) {
  const queryClient = useQueryClient();
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [selection, setSelection] = useState<WallSelection>(() => readSelection(projectId));
  const current = selection.projectId === projectId ? selection : readSelection(projectId);
  useEffect(() => {
    if (selection.projectId !== projectId) setSelection(readSelection(projectId));
  }, [projectId, selection.projectId]);
  useEffect(() => {
    if (selection.projectId !== projectId) return;
    try {
      sessionStorage.setItem(
        "df:scene-wall:" + projectId,
        JSON.stringify({
          filter: selection.filter,
          sceneId: selection.sceneId,
        }),
      );
    } catch {
      // Browser storage is optional; navigation still works without it.
    }
  }, [projectId, selection]);

  const scenes = useQuery({
    queryKey: queryKeys.scene.summaries(projectId),
    queryFn: () => fetchScenes(projectId),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      query.state.data?.some((scene) => scene.generating_count > 0)
        ? SCENE_ACTIVE_REFETCH_MS
        : false,
  });
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.scene.summaries(projectId) });
  };
  const copy = useMutation({
    mutationFn: (sceneId: string) => copyScene(projectId, sceneId),
    onSuccess: invalidate,
  });
  const reorder = useMutation({
    mutationFn: ({ sceneId, number: next }: { sceneId: string; number: number }) =>
      reorderScene(projectId, sceneId, next),
    onSuccess: invalidate,
  });

  const rows = useMemo(() => scenes.data ?? [], [scenes.data]);
  const restoredProject = useRef<string | null>(null);
  useEffect(() => {
    if (!scenes.isSuccess || restoredProject.current === projectId) return;
    restoredProject.current = projectId;
    const previousSceneId = readSelection(projectId).sceneId;
    if (!previousSceneId || !rows.some((scene) => scene.id === previousSceneId)) return;
    document.getElementById("scene-media-" + previousSceneId)?.scrollIntoView?.({
      block: "center",
    });
  }, [projectId, rows, scenes.isSuccess]);

  const filteredRows = rows.filter((scene) => sceneMatchesFilter(scene, current.filter));
  const activeSceneId =
    filteredRows.find((scene) => scene.id === current.sceneId)?.id ?? filteredRows[0]?.id ?? null;
  const totalShots = rows.reduce((count, scene) => count + scene.shot_count, 0);
  const formalVideos = rows.reduce((count, scene) => count + scene.formal_video_count, 0);

  const onDrop = (targetIndex: number) => {
    if (dragIndex === null || dragIndex === targetIndex) {
      setDragIndex(null);
      return;
    }
    const source = rows[dragIndex];
    const target = rows[targetIndex];
    if (source && target) reorder.mutate({ sceneId: source.id, number: target.scene_number });
    setDragIndex(null);
  };

  return (
    <div data-testid="scene-storyboard-wall" className="qc-scene-wall scene-browser">
      <PageHeader
        title="分镜总览"
        description="按场景查看全片镜头。展开场景后可直接查看正式画面、视频和缺失位置。"
      />
      {scenes.isError && (
        <div className="flash err" role="alert">
          无法读取场景：{String(scenes.error)}
          <Button onClick={() => void scenes.refetch()}>重新读取场景</Button>
        </div>
      )}
      {scenes.isSuccess && rows.length > 0 && (
        <>
          <div className="scene-wall-summary" aria-label="全片制作素材概览">
            <strong>{rows.length} 场景</strong>
            <span>{totalShots} 镜头</span>
            <span>
              正式视频 {formalVideos} / {totalShots}
            </span>
          </div>
          <div className="scene-wall-filters" role="group" aria-label="筛选分镜">
            {FILTERS.map((option) => (
              <Button
                key={option.value}
                aria-pressed={current.filter === option.value}
                onClick={() => setSelection({ projectId, filter: option.value, sceneId: null })}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </>
      )}
      {(copy.isError || reorder.isError) && <p role="alert">场景操作失败，请检查后重试。</p>}
      <ul className="qc-scene-wall-grid">
        {filteredRows.map((scene) => {
          const index = rows.findIndex((row) => row.id === scene.id);
          const expanded = activeSceneId === scene.id;
          return (
            <li key={scene.id} className="qc-scene-card" data-testid="scene-card">
              <header
                draggable
                onDragStart={() => setDragIndex(index)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => onDrop(index)}
              >
                <a
                  href={"/projects/" + projectId + "/scenes/" + scene.id}
                  className="qc-scene-enter"
                >
                  {scene.location_name}
                </a>
                <span>
                  {scene.episode_number}.{scene.scene_number} · {timeOfDayLabel(scene.time_of_day)}
                </span>
                <div className="scene-header-actions">
                  <span className="scene-wall-count">{scene.shot_count} 镜头</span>
                  <span className="scene-wall-count">
                    画面 {scene.formal_keyframe_count}/{scene.shot_count}
                  </span>
                  <span className="scene-wall-count">
                    视频 {scene.formal_video_count}/{scene.shot_count}
                  </span>
                  {scene.risk_count > 0 && <span className="qc-risk">{scene.risk_count} 风险</span>}
                  {scene.pending_review_count > 0 && (
                    <span className="scene-wall-count">待审 {scene.pending_review_count}</span>
                  )}
                  {scene.generating_count > 0 && (
                    <span className="scene-wall-count">生成中 {scene.generating_count}</span>
                  )}
                  {scene.failed_count > 0 && (
                    <span className="scene-wall-count">失败或阻断 {scene.failed_count}</span>
                  )}
                  {scene.unknown_count > 0 && (
                    <span className="scene-wall-count">待核对 {scene.unknown_count}</span>
                  )}
                  <Button
                    aria-expanded={expanded}
                    aria-controls={"scene-media-" + scene.id}
                    onClick={() =>
                      setSelection({ projectId, filter: current.filter, sceneId: scene.id })
                    }
                  >
                    {expanded ? "正在查看镜头" : "查看镜头"}
                  </Button>
                  <Button
                    disabled={copy.isPending}
                    onClick={() => copy.mutate(scene.id)}
                    title={"复制「" + scene.location_name + "」为新的场景草稿"}
                  >
                    复制场景
                  </Button>
                </div>
              </header>
              {scene.synopsis && <p className="qc-scene-card-synopsis">{scene.synopsis}</p>}
              <div id={"scene-media-" + scene.id}>
                {expanded && (
                  <SceneMediaGallery
                    key={projectId + ":" + scene.id}
                    projectId={projectId}
                    scene={scene}
                    filter={current.filter}
                  />
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {scenes.isSuccess && rows.length > 0 && filteredRows.length === 0 && (
        <p role="status">没有符合当前筛选的场景。可切换到“全部镜头”查看所有场景。</p>
      )}
      {scenes.isPending && (
        <p className="muted" data-testid="scene-wall-loading" role="status">
          正在读取场景…
        </p>
      )}
      {scenes.isSuccess && rows.length === 0 && (
        <EmptyState
          title="先写下你的故事"
          description="导入剧本并确认分场后，这里会按顺序呈现每一段故事。"
        >
          <Link className="df-btn primary" to="/projects/$projectId/script" params={{ projectId }}>
            去写剧本
          </Link>
        </EmptyState>
      )}
    </div>
  );
}
