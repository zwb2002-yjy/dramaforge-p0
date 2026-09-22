import { PageHeader, EmptyState, Button } from "../../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { SceneMediaGallery } from "./SceneMediaGallery";
import "../resonance/resonance.css";
// Must load after resonance.css: it settles the workbench container radius on
// this surface against the resonance world's unscoped .rs-scene-* rules.
import "./scene-wall-surface.css";

import { queryKeys } from "../../lib/queryKeys";
import { timeOfDayLabel } from "../../lib/sceneLabels";
import { copyScene, fetchScenes, reorderScene } from "./api";

type SceneStoryboardWallProps = {
  projectId: string;
};

/**
 * Scene-grouped shot and media browser. Counts are direct view switches;
 * previewing never changes the formal selection.
 */
export function SceneStoryboardWall({ projectId }: SceneStoryboardWallProps) {
  const queryClient = useQueryClient();
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const scenes = useQuery({
    queryKey: queryKeys.scene.summaries(projectId),
    queryFn: () => fetchScenes(projectId),
    enabled: Boolean(projectId),
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

  const rows = scenes.data ?? [];

  const onDrop = (targetIndex: number) => {
    if (dragIndex === null || dragIndex === targetIndex) {
      setDragIndex(null);
      return;
    }
    const source = rows[dragIndex];
    const target = rows[targetIndex];
    if (source && target) {
      reorder.mutate({ sceneId: source.id, number: target.scene_number });
    }
    setDragIndex(null);
  };

  return (
    <div data-testid="scene-storyboard-wall" className="qc-scene-wall scene-browser">
      <PageHeader
        title="分镜总览"
        description={
          rows.length > 0
            ? `${rows.length} 个场景 · 点击关键帧放大，点击视频播放`
            : "把故事分成场景，再把每个场景拍成镜头"
        }
      />

      {scenes.isError && <div className="flash err">无法读取场景：{String(scenes.error)}</div>}

      {(copy.isError || reorder.isError) && <p role="alert">场景操作失败，请检查后重试。</p>}
      <ul className="qc-scene-wall-grid">
        {rows.map((scene, index) => (
          <li
            key={scene.id}
            className="qc-scene-card"
            data-testid="scene-card"
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => onDrop(index)}
          >
            <header draggable onDragStart={() => setDragIndex(index)}>
              <a href={`/projects/${projectId}/scenes/${scene.id}`} className="qc-scene-enter">
                {scene.location_name}
              </a>
              <span>
                {scene.episode_number}.{scene.scene_number} · {timeOfDayLabel(scene.time_of_day)}
              </span>
              <div className="scene-header-actions">
                {scene.risk_count > 0 && <span className="qc-risk">⚠ {scene.risk_count} 风险</span>}
                <Button
                  disabled={copy.isPending}
                  onClick={() => copy.mutate(scene.id)}
                  title={`复制「${scene.location_name}」为新的场景草稿`}
                >
                  复制场景
                </Button>
              </div>
            </header>
            {scene.synopsis && <p className="qc-scene-card-synopsis">{scene.synopsis}</p>}
            <SceneMediaGallery projectId={projectId} scene={scene} />
          </li>
        ))}
      </ul>
      {scenes.isPending && (
        <p className="muted" role="status" data-testid="scene-wall-loading">
          正在读取场景…
        </p>
      )}
      {!scenes.isPending && !scenes.isError && rows.length === 0 && (
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
