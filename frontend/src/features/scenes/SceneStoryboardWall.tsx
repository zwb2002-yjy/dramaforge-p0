import {
  PageHeader,
  EmptyState,
  Button,
  ActionLink,
  Alert,
  SegmentedControl,
} from "../../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { SceneMediaGallery } from "./SceneMediaGallery";
import {
  SCENE_MEDIA_FILTERS as FILTERS,
  sceneMatchesFilter,
  sceneOverviewCopy as viewCopy,
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

function rememberSelection(selection: WallSelection) {
  try {
    sessionStorage.setItem(
      "df:scene-wall:" + selection.projectId,
      JSON.stringify({
        filter: selection.filter,
        sceneId: selection.sceneId,
      }),
    );
  } catch {
    // Browser storage is optional; browsing still works without it.
  }
}

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

/** Every scene exposes its shots; offscreen galleries defer their own workspace reads. */
export function SceneStoryboardWall({ projectId }: SceneStoryboardWallProps) {
  const queryClient = useQueryClient();
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [collapsedScenes, setCollapsedScenes] = useState<Set<string>>(() => new Set());
  const [selection, setSelection] = useState<WallSelection>(() => readSelection(projectId));
  const current = selection.projectId === projectId ? selection : readSelection(projectId);
  useEffect(() => {
    if (selection.projectId !== projectId) setSelection(readSelection(projectId));
  }, [projectId, selection.projectId]);
  useEffect(() => {
    if (selection.projectId !== projectId) return;
    rememberSelection(selection);
  }, [projectId, selection]);
  const focusScene = (sceneId: string) => {
    if (current.sceneId === sceneId) return;
    const next = { projectId, filter: current.filter, sceneId };
    // Remember before a native link can unload this page.
    rememberSelection(next);
    setSelection(next);
  };

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
      <PageHeader title="分镜总览" />
      {scenes.isError && (
        <Alert
          role="alert"
          type="error"
          showIcon
          description={
            <>
              无法读取场景：{String(scenes.error)}
              <Button onClick={() => void scenes.refetch()}>重新读取场景</Button>
            </>
          }
        />
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
          <div className="scene-wall-filters">
            <SegmentedControl
              label="筛选分镜"
              options={FILTERS}
              value={current.filter}
              onChange={(filter) => {
                setCollapsedScenes(new Set());
                setSelection({ projectId, filter, sceneId: null });
              }}
            />
          </div>
        </>
      )}
      {(copy.isError || reorder.isError) && <p role="alert">场景操作失败，请检查后重试。</p>}
      <ul className="qc-scene-wall-grid">
        {filteredRows.map((scene) => {
          const index = rows.findIndex((row) => row.id === scene.id);
          const sceneKey = `${projectId}:${scene.id}`;
          const expanded = !collapsedScenes.has(sceneKey);
          return (
            <li
              key={scene.id}
              className="qc-scene-card"
              data-testid="scene-card"
              onPointerDownCapture={() => focusScene(scene.id)}
              onFocusCapture={() => focusScene(scene.id)}
            >
              <header
                draggable
                onDragStart={() => setDragIndex(index)}
                onDragOver={(event) => event.preventDefault()}
                onDrop={() => onDrop(index)}
              >
                <div className="scene-heading">
                  <a
                    href={"/projects/" + projectId + "/scenes/" + scene.id}
                    className="qc-scene-enter"
                  >
                    {scene.location_name}
                  </a>
                  <span>
                    {scene.episode_number}.{scene.scene_number} ·{" "}
                    {timeOfDayLabel(scene.time_of_day)}
                  </span>
                </div>
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
                    onClick={() => {
                      setCollapsedScenes((before) => {
                        const next = new Set(before);
                        if (next.has(sceneKey)) next.delete(sceneKey);
                        else next.add(sceneKey);
                        return next;
                      });
                      setSelection({ projectId, filter: current.filter, sceneId: scene.id });
                    }}
                  >
                    {expanded ? viewCopy.collapse : viewCopy.expand}
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
                    eager={activeSceneId === scene.id}
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
          <ActionLink tone="primary" to="/projects/$projectId/script" params={{ projectId }}>
            去写剧本
          </ActionLink>
        </EmptyState>
      )}
    </div>
  );
}
