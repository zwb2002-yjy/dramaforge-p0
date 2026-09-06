import { useEffect, useRef, useState } from "react";
import "./video-review.css";

export interface VideoAnnotation {
  id: string;
  startSeconds: number;
  endSeconds?: number | null;
  note: string;
}
export interface VideoReviewTimelineProps {
  durationSeconds: number;
  annotations: VideoAnnotation[];
  videoUrl?: string;
  note?: string;
  pending?: boolean;
  onAddAnnotation?: (startSeconds: number, endSeconds: number | null) => Promise<void>;
}

/** Playback and selection are local; only the explicit Save button persists a note. */
export function VideoReviewTimeline({
  durationSeconds,
  annotations,
  videoUrl,
  note = "",
  pending = false,
  onAddAnnotation,
}: VideoReviewTimelineProps) {
  const video = useRef<HTMLVideoElement>(null);
  const [mediaDuration, setMediaDuration] = useState<number | null>(null);
  const [position, setPosition] = useState(0);
  const [start, setStart] = useState("0");
  const [end, setEnd] = useState("");
  const [kind, setKind] = useState("point");
  const [mediaError, setMediaError] = useState(false);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    setMediaDuration(null);
    setPosition(0);
    setStart("0");
    setEnd("");
    setKind("point");
    setMediaError(false);
    setPlaying(false);
  }, [videoUrl]);

  const duration = Math.max(mediaDuration ?? durationSeconds, 0.001);
  const startValue = Number(start);
  const endValue = kind === "range" ? Number(end) : startValue;
  const valid =
    start.trim() !== "" &&
    (kind === "point" || end.trim() !== "") &&
    Number.isFinite(startValue) &&
    Number.isFinite(endValue) &&
    startValue >= 0 &&
    endValue >= startValue &&
    endValue <= duration;
  const ready = mediaDuration !== null && !mediaError;
  function seek(value: number) {
    if (!video.current || !ready) return;
    const next = Math.max(0, Math.min(value, duration));
    video.current.currentTime = next;
    setPosition(next);
  }
  return (
    <div data-testid="video-review-timeline">
      {videoUrl && (
        <>
          <video
            key={videoUrl}
            ref={video}
            src={videoUrl}
            aria-label="正式视频审片播放器"
            className="review-video-player"
            controls
            playsInline
            preload="metadata"
            onLoadedMetadata={(event) => {
              const value = event.currentTarget.duration;
              if (Number.isFinite(value) && value > 0) {
                setMediaDuration(value);
                setMediaError(false);
              } else setMediaError(true);
            }}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            onTimeUpdate={(event) => setPosition(event.currentTarget.currentTime)}
            onError={() => {
              setMediaError(true);
              setMediaDuration(null);
            }}
          />
          {mediaError && (
            <p role="alert">无法加载正式视频，不能保存时间批注。请确认产物是否可用。</p>
          )}
          <div className="video-playback-actions">
            <button
              type="button"
              disabled={!ready || playing}
              onClick={() => {
                void video.current?.play().catch(() => setMediaError(true));
              }}
            >
              播放视频
            </button>
            <button
              type="button"
              disabled={!ready || !playing}
              onClick={() => video.current?.pause()}
            >
              暂停视频
            </button>
          </div>
          <label>
            视频播放位置
            <input
              aria-label="视频播放位置"
              type="range"
              min="0"
              max={duration}
              step="0.01"
              value={Math.min(position, duration)}
              disabled={!ready}
              onChange={(event) => seek(Number(event.target.value))}
            />
          </label>
          <output aria-label="当前视频时间">
            {position.toFixed(3)}s / {duration.toFixed(3)}s
          </output>
          {onAddAnnotation && (
            <div className="video-review-controls">
              <label>
                批注类型
                <select
                  aria-label="视频批注类型"
                  value={kind}
                  disabled={pending}
                  onChange={(event) => setKind(event.target.value)}
                >
                  <option value="point">时间点</option>
                  <option value="range">时间段</option>
                </select>
              </label>
              <label>
                开始（秒）
                <input
                  aria-label="批注开始时间"
                  type="number"
                  min="0"
                  max={duration}
                  step="0.001"
                  value={start}
                  disabled={pending}
                  onChange={(event) => setStart(event.target.value)}
                />
              </label>
              <button
                type="button"
                disabled={!ready || pending}
                onClick={() => setStart(position.toFixed(3))}
              >
                使用当前时间作为开始
              </button>
              {kind === "range" && (
                <>
                  <label>
                    结束（秒）
                    <input
                      aria-label="批注结束时间"
                      type="number"
                      min="0"
                      max={duration}
                      step="0.001"
                      value={end}
                      disabled={pending}
                      onChange={(event) => setEnd(event.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={!ready || pending}
                    onClick={() => setEnd(position.toFixed(3))}
                  >
                    使用当前时间作为结束
                  </button>
                </>
              )}
              {!valid && <p role="status">批注时间必须在视频时长内，且结束不早于开始。</p>}
              {!note.trim() && <p>请先填写上方批注说明。</p>}
              <button
                type="button"
                disabled={!ready || !valid || !note.trim() || pending}
                onClick={() => {
                  void onAddAnnotation(startValue, kind === "range" ? endValue : null).catch(
                    () => undefined,
                  );
                }}
              >
                {pending ? "保存批注中…" : "保存视频批注"}
              </button>
            </div>
          )}
        </>
      )}
      <div className="video-annotation-track" aria-label="已保存时间批注">
        {annotations.map((annotation) => (
          <button
            type="button"
            key={annotation.id}
            data-testid="timeline-annotation"
            className="video-annotation-marker"
            style={{
              left: `${Math.min(98, Math.max(0, (annotation.startSeconds / duration) * 100))}%`,
              width: `${Math.max(2, ((Math.min(annotation.endSeconds ?? annotation.startSeconds, duration) - annotation.startSeconds) / duration) * 100)}%`,
            }}
            title={annotation.note}
            aria-label={`跳转到批注 ${annotation.startSeconds.toFixed(2)}秒 ${annotation.note}`}
            disabled={!ready}
            onClick={() => seek(annotation.startSeconds)}
          />
        ))}
      </div>
      <ul>
        {annotations.map((annotation) => (
          <li key={annotation.id}>
            {annotation.startSeconds.toFixed(2)}s
            {annotation.endSeconds != null ? `–${annotation.endSeconds.toFixed(2)}s` : ""}：
            {annotation.note || "（无说明）"}
          </li>
        ))}
      </ul>
    </div>
  );
}
