import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { artifactContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
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
    <div data-testid="scene-storyboard-wall" className="qc-scene-wall">
      <header className="qc-page-heading">
        <p>场景</p>
        <h1>场景总览 / 故事板墙</h1>
        <span>项目首页是视觉故事板墙：场景代表画面、名称、镜头数与少量状态。</span>
      </header>

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
            <SceneThumbnail scene={scene} projectId={projectId} />
            <header>
              <a href={`/projects/${projectId}/scenes/${scene.id}`} className="qc-scene-enter">
                {scene.location_name}
              </a>
              <span>
                {scene.episode_number}.{scene.scene_number} · {scene.time_of_day}
              </span>
            </header>
            <footer>
              <span>{scene.shot_count} 镜头</span>
              <span>
                {scene.formal_keyframe_count} 关键帧 · {scene.formal_video_count} 视频
              </span>
              {scene.risk_count > 0 && <span className="qc-risk">⚠ {scene.risk_count} 风险</span>}
              <button type="button" onClick={() => copy.mutate(scene.id)}>
                复制
              </button>
            </footer>
          </li>
        ))}
      </ul>
      {rows.length === 0 && <p className="muted">暂无场景。导入剧本后会在这里生成故事板墙。</p>}
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
        <span className="qc-scene-placeholder">无代表图</span>
      )}
    </div>
  );
}
