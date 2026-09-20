import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Tab, Tabs } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { shotTypeLabel } from "../../lib/shotLabels";
import { fetchSceneWorkspace, type SceneSummary, type ShotLite } from "./api";

type View = "shots" | "keyframes" | "videos";
type Preview = { shot: ShotLite; kind: "keyframe" | "video"; artifactId: string };

/** Read-only browser over the canonical scene snapshot, never a second production state. */
export function SceneMediaGallery({
  projectId,
  scene,
}: {
  projectId: string;
  scene: SceneSummary;
}) {
  const [view, setView] = useState<View>("shots");
  const [preview, setPreview] = useState<Preview | null>(null);
  const workspace = useQuery({
    queryKey: queryKeys.scene.workspace(projectId, scene.id),
    queryFn: () => fetchSceneWorkspace(projectId, scene.id),
  });
  const shots = workspace.data?.shots ?? [];
  const shotCount = workspace.data ? shots.length : scene.shot_count;
  const keyframeCount = workspace.data
    ? shots.filter((s) => s.formal_keyframe_artifact_id).length
    : scene.formal_keyframe_count;
  const videoCount = workspace.data
    ? shots.filter((s) => s.formal_video_artifact_id).length
    : scene.formal_video_count;
  const tabs: { id: View; label: string }[] = [
    { id: "shots", label: `${shotCount} 镜头` },
    { id: "keyframes", label: `${keyframeCount} 关键帧` },
    { id: "videos", label: `${videoCount} 视频` },
  ];
  const shotUrl = (shot: ShotLite) => `/projects/${projectId}/scenes/${scene.id}?shotId=${shot.id}`;
  const open = (shot: ShotLite, kind: Preview["kind"]) => {
    const artifactId =
      kind === "video" ? shot.formal_video_artifact_id : shot.formal_keyframe_artifact_id;
    if (artifactId) setPreview({ shot, kind, artifactId });
  };
  return (
    <section className="scene-media-gallery" aria-label={`${scene.location_name} 镜头与素材`}>
      <Tabs label={`${scene.location_name} 内容切换`}>
        {tabs.map((tab) => (
          <Tab
            key={tab.id}
            id={`${scene.id}-${tab.id}`}
            aria-controls={`${scene.id}-media-panel`}
            active={view === tab.id}
            onClick={() => setView(tab.id)}
          >
            {tab.label}
          </Tab>
        ))}
      </Tabs>
      <div role="tabpanel" id={`${scene.id}-media-panel`} aria-labelledby={`${scene.id}-${view}`}>
        {workspace.isPending ? (
          <p role="status">正在读取镜头与素材…</p>
        ) : workspace.isError ? (
          <div role="alert">
            <p>镜头与素材读取失败，不能据此判断素材缺失。</p>
            <Button onClick={() => void workspace.refetch()}>重新读取</Button>
          </div>
        ) : shots.length === 0 ? (
          <p>此场景尚无镜头。</p>
        ) : (
          <>
            {view === "videos" && videoCount < shotCount && (
              <p className="scene-media-note">
                {videoCount} 个正式视频 · {shotCount - videoCount} 个镜头尚无正式视频
              </p>
            )}
            <ol
              className="scene-shot-grid"
              aria-label={
                view === "videos"
                  ? "场景视频列表"
                  : view === "keyframes"
                    ? "场景关键帧列表"
                    : "场景镜头列表"
              }
            >
              {shots.map((shot) => {
                const kind = view === "videos" ? "video" : "keyframe";
                const available =
                  kind === "video"
                    ? shot.formal_video_artifact_id
                    : shot.formal_keyframe_artifact_id;
                return (
                  <li key={shot.id} className="scene-shot-card">
                    <header>
                      <strong>镜头 {shot.shot_number}</strong>
                      <span>{shotTypeLabel(shot.shot_type)}</span>
                    </header>
                    <Button
                      className="scene-shot-thumbnail"
                      aria-label={`${kind === "video" ? "播放视频" : "放大关键帧"} · 镜头 ${shot.shot_number}`}
                      disabled={!available}
                      onClick={() => open(shot, kind)}
                    >
                      {shot.formal_keyframe_artifact_id ? (
                        <img
                          loading="lazy"
                          src={artifactContentUrl(projectId, shot.formal_keyframe_artifact_id)}
                          alt={`镜头 ${shot.shot_number} 正式关键帧`}
                        />
                      ) : (
                        <span>暂无正式关键帧</span>
                      )}
                      <span className="scene-shot-media-label">
                        {available
                          ? kind === "video"
                            ? "▶ 播放视频"
                            : "放大关键帧"
                          : kind === "video"
                            ? "暂无正式视频"
                            : "暂无正式关键帧"}
                      </span>
                    </Button>
                    {view === "shots" && (
                      <p className="scene-shot-description">
                        {shot.visual_description || shot.dialogue || "暂无镜头描述"}
                      </p>
                    )}
                    <div className="scene-shot-actions">
                      {view === "shots" && (
                        <>
                          <Button
                            disabled={!shot.formal_keyframe_artifact_id}
                            onClick={() => open(shot, "keyframe")}
                            aria-label={`查看关键帧 · 镜头 ${shot.shot_number}`}
                          >
                            {shot.formal_keyframe_artifact_id ? "查看关键帧" : "暂无关键帧"}
                          </Button>
                          <Button
                            disabled={!shot.formal_video_artifact_id}
                            onClick={() => open(shot, "video")}
                            aria-label={`播放视频 · 镜头 ${shot.shot_number}`}
                          >
                            {shot.formal_video_artifact_id ? "播放视频" : "暂无视频"}
                          </Button>
                        </>
                      )}
                      <a
                        href={`${shotUrl(shot)}&tool=prompts`}
                        aria-label={`编辑提示词 · 镜头 ${shot.shot_number}`}
                      >
                        编辑提示词
                      </a>
                      <a href={shotUrl(shot)} aria-label={`编辑镜头 ${shot.shot_number}`}>
                        编辑镜头 →
                      </a>
                    </div>
                  </li>
                );
              })}
            </ol>
          </>
        )}
      </div>
      {preview && (
        <MediaPreview
          key={preview.artifactId}
          projectId={projectId}
          preview={preview}
          shotUrl={shotUrl(preview.shot)}
          onClose={() => setPreview(null)}
        />
      )}
    </section>
  );
}

function MediaPreview({
  projectId,
  preview,
  shotUrl,
  onClose,
}: {
  projectId: string;
  preview: Preview;
  shotUrl: string;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  const title = `镜头 ${preview.shot.shot_number} · ${preview.kind === "video" ? "正式视频" : "正式关键帧"}`;
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="scene-media-preview"
      aria-label={title}
      onCancel={onClose}
      onClose={onClose}
    >
      <header>
        <h2>{title}</h2>
        <Button onClick={onClose} autoFocus>
          关闭预览
        </Button>
      </header>
      {preview.kind === "video" ? (
        <video
          ref={video}
          controls
          autoPlay
          preload="metadata"
          src={artifactContentUrl(projectId, preview.artifactId)}
          aria-label={title}
          onError={() => setFailed(true)}
        />
      ) : (
        <img
          src={artifactContentUrl(projectId, preview.artifactId)}
          alt={title}
          onError={() => setFailed(true)}
        />
      )}
      {failed && <p role="alert">素材加载失败，请关闭后重试；不会重新生成素材。</p>}
      <footer>
        {preview.kind === "video" && (
          <>
            <Button
              onClick={() => {
                void video.current?.play().catch(() => setFailed(true));
              }}
            >
              播放视频
            </Button>
            <Button onClick={() => video.current?.pause()}>暂停视频</Button>
          </>
        )}
        <a href={shotUrl}>编辑此镜头</a>
      </footer>
    </dialog>
  );
}
