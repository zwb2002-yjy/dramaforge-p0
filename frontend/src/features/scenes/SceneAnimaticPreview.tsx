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
  const ordered = useMemo(
    () => [...shots].sort((a, b) => a.sort_order - b.sort_order || a.shot_number - b.shot_number),
    [shots],
  );
  const mediaIdentity = ordered
    .map((shot) =>
      [
        shot.id,
        shot.duration_seconds,
        shot.formal_keyframe_artifact_id,
        shot.formal_video_artifact_id,
      ].join(":"),
    )
    .join("|");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [videoEnded, setVideoEnded] = useState(false);
  const [muted, setMuted] = useState(true);
  const videoRef = useRef<HTMLVideoElement>(null);
  const shot = ordered[index] ?? null;
  const duration = shot ? plannedSeconds(shot) : 0;
  const videoId = shot?.formal_video_artifact_id ?? null;
  const frameId = shot?.formal_keyframe_artifact_id ?? null;
  const kind = videoId ? "video" : frameId ? "image" : "missing";
  const total = ordered.reduce((sum, item) => sum + plannedSeconds(item), 0);
  const passed = ordered.slice(0, index).reduce((sum, item) => sum + plannedSeconds(item), 0);
  const goNext = useCallback(() => {
    setMediaError(null);
    setVideoEnded(false);
    if (index >= ordered.length - 1) {
      setElapsed(duration);
      setPlaying(false);
      return;
    }
    setElapsed(0);
    setIndex(index + 1);
  }, [index, ordered.length, duration]);

  useEffect(() => {
    setIndex(0);
    setPlaying(false);
    setElapsed(0);
    setMediaError(null);
    setVideoEnded(false);
    setMuted(true);
    if (videoRef.current) videoRef.current.currentTime = 0;
  }, [projectId, mediaIdentity]);

  useEffect(() => {
    if (!playing || (kind === "video" && !videoEnded) || mediaError || !shot) return;
    const start = performance.now();
    const initialElapsed = elapsed;
    const interval = setInterval(() => {
      setElapsed(Math.min(duration, initialElapsed + (performance.now() - start) / 1000));
    }, 50);
    return () => clearInterval(interval);
    // elapsed is the resume position; changing it during this clock must not restart the clock.
  }, [playing, kind, mediaError, shot, duration, videoEnded]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (playing && (kind !== "video" || videoEnded) && elapsed >= duration && shot) goNext();
  }, [playing, kind, elapsed, duration, shot, goNext, videoEnded]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || kind !== "video") return;
    let live = true;
    if (!playing || videoEnded) video.pause();
    else
      void video.play().catch(() => {
        if (!live) return;
        setPlaying(false);
        setMediaError("浏览器未能开始播放，请检查媒体或再次点击播放。");
      });
    return () => {
      live = false;
      video.pause();
    };
  }, [playing, index, kind, videoEnded]);
  useEffect(() => {
    if (!playing || kind !== "video" || videoEnded) return;
    let frame = 0;
    const tick = () => {
      const current = videoRef.current?.currentTime ?? 0;
      setElapsed(Math.min(duration, current));
      if (current >= duration) goNext();
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, kind, videoEnded, duration, goNext]);
  useEffect(() => {
    const pauseHidden = () => {
      if (document.hidden) {
        setPlaying(false);
        videoRef.current?.pause();
      }
    };
    document.addEventListener("visibilitychange", pauseHidden);
    return () => document.removeEventListener("visibilitychange", pauseHidden);
  }, []);

  if (!shot) return <p>当前场景尚无可预览镜头。</p>;
  const choose = (next: number) => {
    setPlaying(false);
    if (videoRef.current) videoRef.current.currentTime = 0;
    setIndex(next);
    setElapsed(0);
    setMediaError(null);
    setVideoEnded(false);
  };
  const playOrPause = () => {
    if (!playing && index === ordered.length - 1 && elapsed >= duration) {
      setIndex(0);
      setElapsed(0);
      setVideoEnded(false);
      if (videoRef.current) videoRef.current.currentTime = 0;
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
        <p>
          只读预览 · 正式素材优先 · {muted ? "静音" : "使用原视频声音（若有）"} · 不代表剪辑成片
        </p>
      </header>
      <div className="scene-animatic-media">
        {kind === "video" ? (
          <video
            ref={videoRef}
            key={videoId}
            src={artifactContentUrl(projectId, videoId!)}
            muted={muted}
            playsInline
            preload="metadata"
            aria-label="动态分镜视频"
            onTimeUpdate={(event) => {
              if (!playing || videoEnded || event.currentTarget !== videoRef.current) return;
              const time = event.currentTarget.currentTime;
              if (!Number.isFinite(time)) return;
              setElapsed(Math.min(duration, time));
              if (time >= duration) goNext();
            }}
            onEnded={(event) => {
              if (event.currentTarget !== videoRef.current) return;
              if (event.currentTarget.currentTime < duration - 0.1) {
                setElapsed(event.currentTarget.currentTime);
                setVideoEnded(true);
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
      {videoEnded && (
        <p role="status" data-testid="animatic-hold-frame">
          原视频已结束，保持末帧补齐计划时长；补齐部分没有声音。
        </p>
      )}
      <progress aria-label="动态分镜播放头" value={Math.min(total, passed + elapsed)} max={total} />
      <div className="scene-animatic-controls">
        <Button onClick={playOrPause} data-testid="animatic-play-toggle">
          {playing ? "暂停" : "播放"}
        </Button>
        <Button onClick={goNext} disabled={index >= ordered.length - 1}>
          下一镜
        </Button>
        <Button aria-pressed={!muted} onClick={() => setMuted((value) => !value)}>
          {muted ? "使用原视频声音" : "静音"}
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
