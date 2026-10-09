import { useCallback, useEffect, useRef, useState } from "react";
import { Edit3, Pause, Play, SkipBack, SkipForward } from "lucide-react";

import { Button, Dialog } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import { shotTypeLabel } from "../../lib/shotLabels";
import type { ShotLite } from "../shots/api";

type SceneAnimaticPlayerProps = {
  projectId: string;
  sceneName?: string;
  shots: ShotLite[];
  onClose: () => void;
  onSelectShot?: (shotId: string) => void;
};

export function SceneAnimaticPlayer({
  projectId,
  sceneName,
  shots,
  onClose,
  onSelectShot,
}: SceneAnimaticPlayerProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const videoRef = useRef<HTMLVideoElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const currentShot = shots[currentIndex] ?? null;
  const hasVideo = Boolean(currentShot?.formal_video_artifact_id);
  const hasKeyframe = Boolean(currentShot?.formal_keyframe_artifact_id);
  const durationSec = Math.max(1, Number(currentShot?.duration_seconds) || 3);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const advance = useCallback(() => {
    clearTimer();
    setCurrentIndex((prev) => {
      if (prev + 1 < shots.length) {
        return prev + 1;
      }
      setIsPlaying(false);
      return 0;
    });
  }, [shots.length]);

  const goPrevious = () => {
    clearTimer();
    setCurrentIndex((prev) => (prev > 0 ? prev - 1 : 0));
  };

  const goNext = () => {
    clearTimer();
    setCurrentIndex((prev) => (prev + 1 < shots.length ? prev + 1 : 0));
  };

  // When media is an image or placeholder (no video), advance after duration if playing
  useEffect(() => {
    clearTimer();
    if (!isPlaying || hasVideo || !currentShot) return;

    timerRef.current = setTimeout(() => {
      advance();
    }, durationSec * 1000);

    return () => clearTimer();
  }, [advance, currentIndex, isPlaying, hasVideo, durationSec, currentShot]);

  // Handle play/pause toggle for video
  useEffect(() => {
    if (!videoRef.current) return;
    if (isPlaying) {
      try {
        const playPromise = videoRef.current.play();
        if (playPromise !== undefined && typeof playPromise?.catch === "function") {
          playPromise.catch(() => {});
        }
      } catch {
        // Autoplay may be restricted or mock in test environment
      }
    } else {
      try {
        videoRef.current.pause();
      } catch {
        // Ignore mock errors in test
      }
    }
  }, [isPlaying, currentIndex]);

  if (!shots.length) {
    return (
      <Dialog title="场景连播" onClose={onClose} testId="scene-animatic-player-dialog">
        <p className="muted">当前场景暂无镜头。</p>
      </Dialog>
    );
  }

  const mediaSource = hasVideo
    ? artifactContentUrl(projectId, currentShot.formal_video_artifact_id!)
    : hasKeyframe
      ? artifactContentUrl(projectId, currentShot.formal_keyframe_artifact_id!)
      : null;

  return (
    <Dialog
      title={`场景连播 · ${sceneName ?? "预览"}`}
      kicker="动态分镜连播引擎"
      size="wide"
      onClose={onClose}
      testId="scene-animatic-player-dialog"
      actions={
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            width: "100%",
            alignItems: "center",
          }}
        >
          {onSelectShot && currentShot && (
            <Button
              tone="ghost"
              data-testid="animatic-edit-shot-btn"
              onClick={() => {
                onSelectShot(currentShot.id);
                onClose();
              }}
            >
              <Edit3 size={14} style={{ marginRight: 6 }} aria-hidden="true" />
              定位至镜头 #{currentShot.shot_number}
            </Button>
          )}
          <Button tone="default" onClick={onClose}>
            关闭
          </Button>
        </div>
      }
    >
      <div className="df-animatic-container" data-testid="scene-animatic-container">
        <div className="df-animatic-screen" data-testid="animatic-screen">
          {hasVideo && mediaSource ? (
            <video
              ref={videoRef}
              key={`video-${currentShot.id}-${mediaSource}`}
              src={mediaSource}
              autoPlay={isPlaying}
              playsInline
              data-testid="animatic-video-player"
              onEnded={advance}
              style={{ width: "100%", height: "100%", objectFit: "contain" }}
            />
          ) : hasKeyframe && mediaSource ? (
            <img
              key={`img-${currentShot.id}-${mediaSource}`}
              src={mediaSource}
              alt={`镜头 #${currentShot.shot_number}`}
              data-testid="animatic-keyframe-image"
              style={{ width: "100%", height: "100%", objectFit: "contain" }}
            />
          ) : (
            <div className="df-animatic-placeholder" data-testid="animatic-placeholder">
              <p>镜头 #{currentShot.shot_number} 暂无正式画面</p>
              <small className="muted">{currentShot.visual_description || "待生成"}</small>
            </div>
          )}

          <div className="df-animatic-badge" data-testid="animatic-shot-badge">
            #{currentShot.shot_number} · {shotTypeLabel(currentShot.shot_type)} ·{" "}
            {hasVideo ? "正式视频" : hasKeyframe ? "关键帧" : "占位"}
          </div>

          {currentShot.dialogue && (
            <div className="df-animatic-subtitle" data-testid="animatic-subtitle">
              {currentShot.dialogue}
            </div>
          )}
        </div>

        <div className="df-animatic-controls" data-testid="animatic-controls">
          <div className="df-animatic-buttons">
            <Button
              tone="ghost"
              aria-label="上一镜"
              data-testid="animatic-prev-btn"
              onClick={goPrevious}
              disabled={currentIndex === 0}
            >
              <SkipBack size={16} aria-hidden="true" />
            </Button>
            <Button
              tone="primary"
              aria-label={isPlaying ? "暂停" : "播放"}
              data-testid="animatic-play-toggle-btn"
              onClick={() => setIsPlaying(!isPlaying)}
            >
              {isPlaying ? (
                <Pause size={16} aria-hidden="true" />
              ) : (
                <Play size={16} aria-hidden="true" />
              )}
            </Button>
            <Button
              tone="ghost"
              aria-label="下一镜"
              data-testid="animatic-next-btn"
              onClick={goNext}
              disabled={currentIndex === shots.length - 1}
            >
              <SkipForward size={16} aria-hidden="true" />
            </Button>
          </div>

          <div className="df-animatic-info">
            <span>
              第 <strong>{currentIndex + 1}</strong> / {shots.length} 镜 · {durationSec}秒
            </span>
          </div>
        </div>

        <div className="df-animatic-strip" data-testid="animatic-strip">
          {shots.map((shot, idx) => (
            <button
              key={shot.id}
              type="button"
              className={`df-animatic-thumb ${idx === currentIndex ? "active" : ""}`}
              onClick={() => {
                clearTimer();
                setCurrentIndex(idx);
                setIsPlaying(true);
              }}
              data-testid={`animatic-thumb-${shot.id}`}
              aria-label={`跳转至 #${shot.shot_number}`}
            >
              <span className="df-animatic-thumb-number">#{shot.shot_number}</span>
              <span className="df-animatic-thumb-type">
                {shot.formal_video_artifact_id
                  ? "视频"
                  : shot.formal_keyframe_artifact_id
                    ? "画面"
                    : "无"}
              </span>
            </button>
          ))}
        </div>
      </div>
    </Dialog>
  );
}
