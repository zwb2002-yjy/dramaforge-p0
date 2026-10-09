import { useState } from "react";
import { Button } from "../../components/ui";
import { artifactContentUrl, artifactVideoFrameUrl } from "../../lib/api";
import type { ShotLite } from "./api";
import type { ShotCandidate } from "./shotCandidates";
import "./shot-continuity.css";

/** Evidence comparison only: existing media, explicit source labels, no production mutation. */
export function ShotContinuityCompare({
  projectId,
  shots,
  shotId,
  candidate,
}: {
  projectId: string;
  shots: ShotLite[];
  shotId: string | null;
  candidate?: ShotCandidate | null;
}) {
  const [open, setOpen] = useState(false);
  const ordered = [...shots].sort(
    (a, b) => a.sort_order - b.sort_order || a.shot_number - b.shot_number,
  );
  const index = ordered.findIndex((shot) => shot.id === shotId);
  if (index < 0) return null;
  return (
    <section className="shot-continuity" aria-label="相邻镜头连续性对照">
      <Button tone="ghost" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        相邻镜头对照
      </Button>
      {open && (
        <div className="shot-continuity-grid" data-testid="shot-continuity-grid">
          {[
            { offset: -1, title: "前镜末帧" },
            { offset: 0, title: "当前镜头首帧" },
            { offset: 1, title: "后镜首帧" },
          ].map(({ offset, title }) => {
            const shot = ordered[index + offset];
            const selected = offset === 0 ? candidate : null;
            const video =
              selected?.stage === "video"
                ? selected.artifactId
                : selected
                  ? null
                  : shot?.formal_video_artifact_id;
            const image =
              selected?.stage === "image_keyframe"
                ? selected.artifactId
                : selected
                  ? null
                  : shot?.formal_keyframe_artifact_id;
            return (
              <ComparisonMedia
                key={`${projectId}:${shot?.id ?? offset}:${video ?? image}:${selected ? "candidate" : "formal"}`}
                projectId={projectId}
                title={title}
                shot={shot}
                videoId={video}
                imageId={image}
                end={offset < 0}
                source={selected ? "所选候选（非正式）" : "正式素材"}
              />
            );
          })}
          <p className="shot-continuity-note">
            只对照已有证据，不自动判断连续性或生成缺失画面。视频读取首/末帧采样；静帧不代表视频首/末帧证据。
          </p>
        </div>
      )}
    </section>
  );
}

function ComparisonMedia({
  projectId,
  title,
  shot,
  videoId,
  imageId,
  end,
  source,
}: {
  projectId: string;
  title: string;
  shot?: ShotLite;
  videoId?: string | null;
  imageId?: string | null;
  end: boolean;
  source: string;
}) {
  const [error, setError] = useState(false);
  return (
    <figure className="shot-continuity-item" aria-label={title}>
      <figcaption>
        {title}
        {shot ? ` · 镜头 ${shot.shot_number}` : ""} · {source}
      </figcaption>
      {videoId ? (
        <>
          <img
            src={artifactVideoFrameUrl(projectId, videoId, end ? "end" : "start")}
            alt={`${title}视频采样帧`}
            onError={() => setError(true)}
          />
          <small>来自此视频的{end ? "末帧" : "首帧"}采样</small>
        </>
      ) : imageId ? (
        <>
          <img
            src={artifactContentUrl(projectId, imageId)}
            alt={`${title} · ${source === "正式素材" ? "正式静帧" : "所选候选静帧"}`}
            onError={() => setError(true)}
          />
          <small>仅有静帧，尚无视频首/末帧证据</small>
        </>
      ) : (
        <p role="status">{shot ? "此镜头缺少可对照素材" : "没有相邻镜头"}</p>
      )}
      {error && <p role="alert">已有素材读取失败，请检查该镜头；不会当作缺失素材自动补生成。</p>}
    </figure>
  );
}
