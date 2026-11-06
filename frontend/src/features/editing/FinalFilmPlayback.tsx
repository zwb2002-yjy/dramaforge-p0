import { useRef, useState } from "react";
import { artifactContentUrl } from "../../lib/api";
import { Button, Alert } from "../../components/ui";
import { deliveryCopy as copy } from "./deliveryCopy";

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
        className="final-film-video"
        ref={video}
        controls
        playsInline
        preload="metadata"
        aria-label={copy.playback}
        data-testid="final-film-player"
        src={artifactContentUrl(projectId, artifactId)}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onError={() => setError(true)}
      >
        {copy.browserUnsupported}
      </video>
      <div className="film-playback-actions">
        <Button
          type="button"
          disabled={playing || error}
          onClick={() => {
            void video.current?.play().catch(() => setError(true));
          }}
        >
          {copy.play}
        </Button>
        <Button type="button" disabled={!playing} onClick={() => video.current?.pause()}>
          {copy.pause}
        </Button>
      </div>
      {error && <Alert role="alert" type="error" showIcon description={<>{copy.mediaError}</>} />}
    </>
  );
}
