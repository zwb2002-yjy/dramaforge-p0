import { PageHeader, EmptyState } from "../../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { ArrowUpRight } from "lucide-react";
import "../resonance/resonance.css";
// Must load after resonance.css: it settles the workbench container radius on
// this surface against the resonance world's unscoped .rs-scene-* rules.
import "./scene-wall-surface.css";

import { artifactContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { timeOfDayLabel } from "../../lib/sceneLabels";
import { copyScene, fetchScenes, reorderScene, type SceneSummary } from "./api";

type SceneStoryboardWallProps = {
  projectId: string;
};

/**
 * Phase 3 storyboard wall: project home is a visual scene wall, not a KPI
 * dashboard. Cards show representative image, name, time, shot count, status.
 */
export function SceneStoryboardWall({ projectId }: SceneStoryboardWallProps) {
  const queryClient = useQueryClient();
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const scenes = useQuery({
    queryKey: queryKeys.scene.summaries(projectId),
    queryFn: () => fetchScenes(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
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
    <div data-testid="scene-storyboard-wall" className="qc-scene-wall rs-scene-world">
      <PageHeader
        title="场景总览"
        description={
          rows.length > 0
            ? `${rows.length} 段故事 · 点开查看分镜`
            : "把故事分成场景，再把每个场景拍成镜头"
        }
      />

      {scenes.isError && <div className="flash err">无法读取场景：{String(scenes.error)}</div>}

      <ul className="qc-scene-wall-grid">
        {rows.map((scene, index) => (
          <li
            key={scene.id}
            className="qc-scene-card"
            data-testid="scene-card"
            draggable
            onDragStart={() => setDragIndex(index)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => onDrop(index)}
          >
            <a
              className="rs-scene-portal"
              href={`/projects/${projectId}/scenes/${scene.id}`}
              aria-label={`进入场景：${scene.location_name}`}
            >
              <SceneThumbnail scene={scene} projectId={projectId} />
              <span className="rs-portal-enter" aria-hidden="true">
                <ArrowUpRight size={22} />
              </span>
            </a>
            <header>
              <a href={`/projects/${projectId}/scenes/${scene.id}`} className="qc-scene-enter">
                {scene.location_name}
              </a>
              <span>
                {scene.episode_number}.{scene.scene_number} · {timeOfDayLabel(scene.time_of_day)}
              </span>
            </header>
            {scene.synopsis && <p className="qc-scene-card-synopsis">{scene.synopsis}</p>}
            <footer>
              <span>{scene.shot_count} 镜头</span>
              <span>
                {scene.formal_keyframe_count} 关键帧 · {scene.formal_video_count} 视频
              </span>
              {scene.risk_count > 0 && <span className="qc-risk">⚠ {scene.risk_count} 风险</span>}
              <button
                type="button"
                onClick={() => copy.mutate(scene.id)}
                title={`复制「${scene.location_name}」为新的场景草稿`}
              >
                复制场景
              </button>
            </footer>
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

function SceneThumbnail({ scene, projectId }: { scene: SceneSummary; projectId: string }) {
  const artifact = scene.representative_artifact;
  return (
    <div className="qc-scene-thumb" data-testid="scene-thumb">
      {artifact ? (
        <img
          src={artifactContentUrl(projectId, artifact.id)}
          alt={`${scene.location_name} 代表画面`}
          data-testid="scene-representative"
        />
      ) : (
        <span className="qc-scene-placeholder rs-scene-silhouette" aria-label="尚无代表画面">
          <span aria-hidden="true">{String(scene.scene_number).padStart(2, "0")}</span>
          <small>等待第一张画面</small>
        </span>
      )}
    </div>
  );
}
