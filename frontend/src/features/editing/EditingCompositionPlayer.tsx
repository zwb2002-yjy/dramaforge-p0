import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../../components/ui";
import { artifactContentUrl } from "../../lib/api";
import type { TimelinePreviewRead } from "./api";
import { timelineCopy as copy } from "./timelineCopy";

/** Native-media playback of compiled hard cuts; source video audio is never mixed in. */
export function EditingCompositionPlayer({
  projectId,
  plan,
  seekRequest,
  onPosition,
  onClipChange,
}: {
  projectId: string;
  plan: TimelinePreviewRead;
  seekRequest: { value: number; revision: number };
  onPosition: (milliseconds: number) => void;
  onClipChange: (clipId: string) => void;
}) {
  const [index, setIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const callbacks = useRef({ onPosition, onClipChange });
  callbacks.current = { onPosition, onClipChange };
  const clip = plan.clips[index];
  const position = clip ? clip.start_ms + elapsed : 0;
  const rate = clip ? (clip.source_out_ms - clip.source_in_ms) / clip.duration_ms : 1;
  const seek = useCallback(
    (value: number) => {
      const bounded = Math.min(plan.duration_ms, Math.max(0, value));
      const next = plan.clips.findIndex((item) => bounded < item.end_ms);
      const selected = next < 0 ? plan.clips.length - 1 : next;
      setPlaying(false);
      setReady(false);
      setError(null);
      setIndex(selected);
      setElapsed(bounded - (plan.clips[selected]?.start_ms ?? 0));
    },
    [plan],
  );
  useEffect(() => {
    seek(seekRequest.value);
  }, [seekRequest, seek]);
  useEffect(() => {
    callbacks.current.onPosition(position);
    if (clip) callbacks.current.onClipChange(clip.clip_id);
  }, [position, clip]);
  const fail = () => {
    setError(copy.playerError);
    setPlaying(false);
  };
  const prepareVideo = useCallback(() => {
    const video = videoRef.current;
    if (!video || !clip || video.readyState < 1) return;
    try {
      video.playbackRate = rate;
    } catch {
      setError(copy.playerError);
      setPlaying(false);
      return;
    }
    const target = (clip.source_in_ms + elapsed * rate) / 1000;
    if (Math.abs(video.currentTime - target) > 0.02) video.currentTime = target;
    else setReady(true);
  }, [clip, elapsed, rate]);
  useEffect(() => {
    if (!ready) prepareVideo();
  }, [ready, prepareVideo, seekRequest]);
  useEffect(() => {
    const video = videoRef.current;
    const audio = audioRef.current;
    if (!video || !clip) return;
    let active = true;
    if (playing && ready) {
      void video.play().catch(() => {
        if (active) {
          setError(copy.playerError);
          setPlaying(false);
        }
      });
      if (audio) {
        audio.volume = clip.audio_volume;
        audio.currentTime = elapsed / 1000;
        void audio.play().catch(() => {
          if (active) {
            setError(copy.playerError);
            setPlaying(false);
          }
        });
      }
    } else {
      video.pause();
      audio?.pause();
    }
    return () => {
      active = false;
      video.pause();
      audio?.pause();
    };
    // elapsed is the resume point, not a reason to restart a playing media element.
  }, [playing, ready, clip]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!playing || !ready || !clip) return;
    let frame = 0;
    const tick = () => {
      const video = videoRef.current;
      if (!video) return;
      const progress = Math.min(
        clip.duration_ms,
        Math.max(0, (video.currentTime * 1000 - clip.source_in_ms) / rate),
      );
      setElapsed(progress);
      const audio = audioRef.current;
      if (
        audio &&
        Number.isFinite(audio.duration) &&
        !audio.ended &&
        Math.abs(audio.currentTime * 1000 - progress) > 80
      )
        audio.currentTime = Math.min(audio.duration, progress / 1000);
      if (progress >= clip.duration_ms - 1) {
        if (index === plan.clips.length - 1) {
          setElapsed(clip.duration_ms);
          setPlaying(false);
        } else {
          setReady(false);
          setElapsed(0);
          setIndex(index + 1);
        }
      } else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, ready, clip, rate, index, plan]);
  useEffect(() => {
    const pauseHidden = () => {
      if (document.hidden) setPlaying(false);
    };
    document.addEventListener("visibilitychange", pauseHidden);
    return () => document.removeEventListener("visibilitychange", pauseHidden);
  }, []);
  if (!clip) return null;
  return (
    <section
      aria-label={copy.composition}
      data-testid="editing-composition-player"
      data-clip-id={clip.clip_id}
    >
      <div className="editing-composition-screen">
        <video
          key={clip.clip_id}
          ref={videoRef}
          muted
          playsInline
          preload="auto"
          src={artifactContentUrl(projectId, clip.video_artifact_id)}
          aria-label={copy.playback}
          onLoadedMetadata={prepareVideo}
          onLoadedData={prepareVideo}
          onSeeked={() => setReady(true)}
          onError={fail}
          onEnded={() => {
            if (elapsed < clip.duration_ms - 100) fail();
            else if (index === plan.clips.length - 1) {
              setElapsed(clip.duration_ms);
              setPlaying(false);
            } else {
              setReady(false);
              setElapsed(0);
              setIndex(index + 1);
            }
          }}
        />
        {clip.subtitle_text && (
          <p className="editing-composition-subtitle" data-testid="editing-composition-subtitle">
            {clip.subtitle_text}
          </p>
        )}
      </div>
      {clip.audio_state === "available" && clip.audio_artifact_id && (
        <audio
          key={clip.clip_id}
          ref={audioRef}
          preload="auto"
          src={artifactContentUrl(projectId, clip.audio_artifact_id)}
          aria-label={copy.audioPlayback}
          onError={fail}
        />
      )}
      <p role="status">
        {clip.audio_state === "muted"
          ? copy.mute
          : clip.audio_state === "none"
            ? copy.noAudio
            : `配音音量 ${Math.round(clip.audio_volume * 100)}%`}
      </p>
      {error && <p role="alert">{error}</p>}
      <progress aria-label="剪辑预览播放头" max={plan.duration_ms} value={position} />
      <Button
        data-testid="editing-composition-toggle"
        disabled={!ready || !!error}
        onClick={() => {
          if (position >= plan.duration_ms) {
            seek(0);
            setPlaying(true);
          } else setPlaying((value) => !value);
        }}
      >
        {playing ? copy.pause : copy.play}
      </Button>
    </section>
  );
}
