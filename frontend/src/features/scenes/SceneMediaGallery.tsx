import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Badge, Button, Dialog } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { shotTypeLabel } from "../../lib/shotLabels";
import { fetchSceneWorkspace, type SceneSummary, type ShotLite } from "./api";
import { SceneAnimaticPreview } from "./SceneAnimaticPreview";
import { shotMatchesFilter, type SceneMediaFilter } from "./sceneOverviewState";
import { SCENE_ACTIVE_REFETCH_MS } from "../production";

type Preview = { shot: ShotLite; kind: "keyframe" | "video"; artifactId: string };

/** Project-scoped, server-owned Shot facts. Filter never mutates Candidate or Formal. */
export function SceneMediaGallery({
  projectId,
  scene,
  filter = "all",
  eager = true,
}: {
  projectId: string;
  scene: SceneSummary;
  filter?: SceneMediaFilter;
  eager?: boolean;
}) {
  const gallery = useRef<HTMLElement>(null);
  const [inViewport, setInViewport] = useState(eager);
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") {
      setInViewport(true);
      return;
    }
    const element = gallery.current;
    if (!element) return;
    const observer = new IntersectionObserver((entries) => {
      setInViewport(entries.some((entry) => entry.isIntersecting));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [animaticOpen, setAnimaticOpen] = useState(false);
  const workspace = useQuery({
    queryKey: queryKeys.scene.workspace(projectId, scene.id),
    queryFn: () => fetchSceneWorkspace(projectId, scene.id),
    enabled: eager || inViewport,
    refetchInterval: (query) =>
      inViewport &&
      Object.values(query.state.data?.overview ?? {}).some((facts) => facts.generating)
        ? SCENE_ACTIVE_REFETCH_MS
        : false,
  });
  const shots = workspace.data?.shots ?? [];
  const displayedShots = shots.filter((shot) =>
    shotMatchesFilter(shot, workspace.data?.overview?.[shot.id], filter),
  );
  const shotUrl = (shot: ShotLite) =>
    "/projects/" + projectId + "/scenes/" + scene.id + "?shotId=" + shot.id;
  const open = (shot: ShotLite, kind: Preview["kind"]) => {
    const artifactId =
      kind === "video" ? shot.formal_video_artifact_id : shot.formal_keyframe_artifact_id;
    if (artifactId) setPreview({ shot, kind, artifactId });
  };

  return (
    <section
      ref={gallery}
      className="scene-media-gallery"
      data-deferred={workspace.isPending}
      aria-label={scene.location_name + " 镜头与素材"}
    >
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
          <Button
            onClick={() => setAnimaticOpen((value) => !value)}
            aria-expanded={animaticOpen}
            data-testid="scene-animatic-toggle"
          >
            {animaticOpen ? "关闭动态分镜" : "播放动态分镜"}
          </Button>
          {animaticOpen && (
            <SceneAnimaticPreview
              projectId={projectId}
              shots={shots}
              candidates={workspace.data?.candidates}
            />
          )}
          {displayedShots.length === 0 ? (
            <p role="status">本场景没有符合当前筛选的镜头。</p>
          ) : (
            <ol
              className="scene-shot-grid"
              aria-label="场景镜头列表"
              style={{
                maxWidth: `calc(${displayedShots.length} * var(--df-storyboard-card-max) + ${Math.max(0, displayedShots.length - 1)} * var(--df-space-4))`,
              }}
            >
              {displayedShots.map((shot) => {
                const frameId = shot.formal_keyframe_artifact_id;
                const videoId = shot.formal_video_artifact_id;
                const previewKind = videoId ? "video" : "keyframe";
                return (
                  <li
                    key={shot.id}
                    className="scene-shot-card"
                    data-testid="scene-shot-card"
                    data-shot-id={shot.id}
                  >
                    <header>
                      <strong>镜头 {shot.shot_number}</strong>
                      <span>{shotTypeLabel(shot.shot_type)}</span>
                    </header>
                    <Button
                      className="scene-shot-thumbnail"
                      aria-label={"预览镜头 " + shot.shot_number}
                      disabled={!frameId && !videoId}
                      onClick={() => open(shot, previewKind)}
                    >
                      <span className="scene-shot-thumbnail-content">
                        {frameId ? (
                          <img
                            loading="lazy"
                            src={artifactContentUrl(projectId, frameId)}
                            alt={"镜头 " + shot.shot_number + " 正式关键帧"}
                          />
                        ) : (
                          <span className="scene-shot-placeholder">
                            {videoId ? "有正式视频，暂无正式关键帧" : "暂无正式素材"}
                          </span>
                        )}
                      </span>
                    </Button>
                    <div className="scene-shot-status" aria-label="镜头制作状态">
                      {workspace.data?.overview?.[shot.id]?.pending_review && (
                        <Badge tone="warning">待审候选</Badge>
                      )}
                      {workspace.data?.overview?.[shot.id]?.generating && (
                        <Badge tone="info">生成中</Badge>
                      )}
                      {workspace.data?.overview?.[shot.id]?.generation_failed && (
                        <Badge tone="danger">生成失败或阻断</Badge>
                      )}
                      {workspace.data?.overview?.[shot.id]?.outcome_unknown && (
                        <Badge tone="warning" title="进入镜头查看已有执行">
                          状态待核对
                        </Badge>
                      )}
                    </div>
                    <div
                      className="scene-shot-evidence"
                      aria-label={"镜头 " + shot.shot_number + " 素材状态"}
                    >
                      <span data-present={Boolean(frameId)}>
                        正式画面：{frameId ? "已选定" : "未选定"}
                      </span>
                      <span data-present={Boolean(videoId)}>
                        正式视频：{videoId ? "已选定" : "未选定"}
                      </span>
                    </div>
                    <p className="scene-shot-description">
                      {shot.visual_description || shot.dialogue || "暂无镜头描述"}
                    </p>
                    <div className="scene-shot-actions">
                      <Button
                        disabled={!frameId}
                        onClick={() => open(shot, "keyframe")}
                        aria-label={"查看关键帧 · 镜头 " + shot.shot_number}
                      >
                        查看画面
                      </Button>
                      <Button
                        disabled={!videoId}
                        onClick={() => open(shot, "video")}
                        aria-label={"播放视频 · 镜头 " + shot.shot_number}
                      >
                        播放视频
                      </Button>
                      <a href={shotUrl(shot)} aria-label={"编辑镜头 " + shot.shot_number}>
                        进入工作台 →
                      </a>
                      {(frameId || videoId) && (
                        <a
                          href={`/projects/${encodeURIComponent(projectId)}/review?shotId=${encodeURIComponent(shot.id)}`}
                          aria-label={`审片镜头 ${shot.shot_number}`}
                        >
                          审片
                        </a>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </>
      )}
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
  onClose: onClosed,
}: {
  projectId: string;
  preview: Preview;
  shotUrl: string;
  onClose: () => void;
}) {
  const [open, setOpen] = useState(true);
  const onClose = () => setOpen(false);
  const video = useRef<HTMLVideoElement>(null);
  const [failed, setFailed] = useState(false);
  const title = `镜头 ${preview.shot.shot_number} · ${preview.kind === "video" ? "正式视频" : "正式关键帧"}`;
  return (
    <Dialog
      open={open}
      afterClose={onClosed}
      title={title}
      onClose={onClose}
      size="wide"
      actions={<Button onClick={onClose}>关闭预览</Button>}
    >
      <div className="scene-media-content">
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
      </div>
    </Dialog>
  );
}
