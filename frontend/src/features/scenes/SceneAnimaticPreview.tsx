import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import type { ShotLite } from "./api";
import "./scene-animatic.css";

/** Client-only playback of server-selected media. Never creates a production run or Formal. */
function plannedSeconds(shot: ShotLite): number {
  const value = Number(shot.duration_seconds);
  return Number.isFinite(value) && value > 0 ? value : 3;
}

export function SceneAnimaticPreview({
  projectId,
  shots,
}: {
  projectId: string;
  shots: ShotLite[];
}) {
  const ordered = useMemo(() => [...shots].sort((a, b) => a.shot_number - b.shot_number), [shots]);
  const mediaIdentity = ordered
    .map((shot) =>
      [shot.id, shot.formal_keyframe_artifact_id, shot.formal_video_artifact_id].join(":"),
    )
    .join("|");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const shot = ordered[index] ?? null;
  const duration = shot ? plannedSeconds(shot) : 0;
  const videoId = shot?.formal_video_artifact_id ?? null;
  const frameId = shot?.formal_keyframe_artifact_id ?? null;
  const kind = videoId ? "video" : frameId ? "image" : "missing";
  const total = ordered.reduce((sum, item) => sum + plannedSeconds(item), 0);
  const passed = ordered.slice(0, index).reduce((sum, item) => sum + plannedSeconds(item), 0);
  const goNext = useCallback(() => {
    setElapsed(0);
    setMediaError(null);
    if (index >= ordered.length - 1) {
      setPlaying(false);
      return;
    }
    setIndex(index + 1);
  }, [index, ordered.length]);

  useEffect(() => {
    setIndex(0);
    setPlaying(false);
    setElapsed(0);
    setMediaError(null);
  }, [projectId, mediaIdentity]);

  useEffect(() => {
    if (!playing || kind === "video" || mediaError || !shot) return;
    const interval = setInterval(() => {
      setElapsed((current) => Math.min(duration, current + 0.25));
    }, 250);
    return () => clearInterval(interval);
  }, [playing, kind, mediaError, shot, duration]);

  useEffect(() => {
    if (playing && kind !== "video" && elapsed >= duration && shot) goNext();
  }, [playing, kind, elapsed, duration, shot, goNext]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || kind !== "video") return;
    if (!playing) {
      video.pause();
      return;
    }
    void video.play().catch(() => {
      setPlaying(false);
      setMediaError("浏览器未能开始播放，请检查媒体或再次点击播放。");
    });
  }, [playing, index, kind]);

  if (!shot) return <p>当前场景尚无可预览镜头。</p>;
  const choose = (next: number) => {
    setPlaying(false);
    setIndex(next);
    setElapsed(0);
    setMediaError(null);
  };
  const playOrPause = () => {
    if (!playing && index === ordered.length - 1 && elapsed >= duration) {
      setIndex(0);
      setElapsed(0);
    }
    setMediaError(null);
    setPlaying((wasPlaying) => !wasPlaying);
  };

  return (
    <section
      className="scene-animatic"
      data-testid="scene-animatic"
      data-shot-id={shot.id}
      aria-label="动态分镜预览"
    >
      <header>
        <strong>
          动态分镜 · {index + 1}/{ordered.length} 镜头
        </strong>
        <p>只读预览 · 正式素材优先 · 视频静音 · 不代表剪辑成片</p>
      </header>
      <div className="scene-animatic-media">
        {kind === "video" ? (
          <video
            ref={videoRef}
            key={videoId}
            src={artifactContentUrl(projectId, videoId!)}
            muted
            playsInline
            preload="metadata"
            aria-label="动态分镜视频"
            onTimeUpdate={(event) => {
              const time = event.currentTarget.currentTime;
              if (!Number.isFinite(time)) return;
              setElapsed(Math.min(duration, time));
              if (time >= duration) goNext();
            }}
            onEnded={(event) => {
              if (event.currentTarget.currentTime < duration - 0.1) {
                setPlaying(false);
                setMediaError("正式视频早于镜头计划时长结束，请检查片段长度后继续下一镜。");
              } else goNext();
            }}
            onError={() => {
              setPlaying(false);
              setMediaError("正式视频读取失败，不能视为没有素材。");
            }}
          />
        ) : kind === "image" ? (
          <img
            key={frameId}
            src={artifactContentUrl(projectId, frameId!)}
            alt={"镜头 " + shot.shot_number + " 正式画面"}
            onError={() => {
              setPlaying(false);
              setMediaError("正式画面读取失败，不能视为没有素材。");
            }}
          />
        ) : (
          <p className="scene-animatic-missing" role="status">
            镜头 {shot.shot_number} 尚无正式视频或正式画面（按计划时长显示占位）。
          </p>
        )}
      </div>
      {shot.dialogue && <p className="scene-animatic-dialogue">对白参考：{shot.dialogue}</p>}
      {mediaError && <p role="alert">{mediaError}</p>}
      <progress aria-label="动态分镜播放头" value={Math.min(total, passed + elapsed)} max={total} />
      <div className="scene-animatic-controls">
        <Button onClick={playOrPause} data-testid="animatic-play-toggle">
          {playing ? "暂停" : "播放"}
        </Button>
        <Button onClick={goNext} disabled={index >= ordered.length - 1}>
          下一镜
        </Button>
        <span>
          当前镜头 {elapsed.toFixed(1)} / {duration.toFixed(1)} 秒
        </span>
      </div>
      <nav aria-label="动态分镜镜头序列">
        {ordered.map((item, position) => (
          <Button key={item.id} aria-pressed={index === position} onClick={() => choose(position)}>
            #{item.shot_number}
          </Button>
        ))}
      </nav>
    </section>
  );
}
