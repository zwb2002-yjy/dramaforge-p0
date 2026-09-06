import { useRef, useState } from "react";
import { artifactContentUrl } from "../../lib/api";

export function FinalFilmPlayback({
  projectId,
  artifactId,
}: {
  projectId: string;
  artifactId: string;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState(false);
  return (
    <>
      <video
        ref={video}
        controls
        playsInline
        preload="metadata"
        aria-label="成片播放器"
        data-testid="final-film-player"
        src={artifactContentUrl(projectId, artifactId)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => setError(true)}
      >
        当前浏览器不支持视频播放。
      </video>
      <div className="film-playback-actions">
        <button
          type="button"
          disabled={playing || error}
          onClick={() => {
            void video.current?.play().catch(() => setError(true));
          }}
        >
          播放成片
        </button>
        <button type="button" disabled={!playing} onClick={() => video.current?.pause()}>
          暂停成片
        </button>
      </div>
      {error && <p role="alert">成片媒体暂时不可读取。保留历史记录，不会自动重新导出。</p>}
    </>
  );
}
