import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Play, Pause } from "lucide-react";
import { Button, Select, Tabs } from "../../components/ui";
import { EditingSourcePreview } from "./EditingSourcePreview";
import { EditingTimeline } from "./EditingTimeline";
import { EditingCompositionPlayer } from "./EditingCompositionPlayer";
import { previewEditTimeline, type TimelinePreviewRead } from "./api";
import type { EditableTimeline } from "./useTimelineDraft";
import { timelineGeometry } from "./timelineGeometry";
import { timelineCopy as copy } from "./timelineCopy";
import { ApiError } from "../../lib/api";
import { editingClipLabel, timelineTime } from "./clipPresentation";

export function EditingPreviewWorkspace({
  projectId,
  sessionId,
  baselineVersion,
  draft,
  dirty,
  selectedIndex,
  onSelectClip,
  onReorder,
  onUpdateClip,
}: {
  projectId: string;
  sessionId: string;
  baselineVersion: number;
  draft: EditableTimeline;
  dirty: boolean;
  selectedIndex: number;
  onSelectClip: (index: number) => void;
  onReorder: (from: number, to: number) => void;
  onUpdateClip?: (index: number, clip: EditableTimeline["clips"][number]) => void;
}) {
  const [mode, setMode] = useState<"source" | "composition">("source");
  const [loaded, setLoaded] = useState<{ signature: string; plan: TimelinePreviewRead } | null>(
    null,
  );
  const [pending, setPending] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [playRequest, setPlayRequest] = useState({ playing: false, revision: 0 });
  const playIntent = useRef(0);
  const [error, setError] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(
    () => timelineGeometry(draft.clips).items[selectedIndex]?.startMs ?? 0,
  );
  const [seekRequest, setSeekRequest] = useState({ value: playhead, revision: 0 });
  const playheadRef = useRef(playhead);
  playheadRef.current = playhead;
  const signature = JSON.stringify([projectId, sessionId, baselineVersion, draft]);
  const current = useRef(signature);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  current.current = signature;
  const plan = loaded?.signature === signature ? loaded.plan : null;
  const geometry = timelineGeometry(draft.clips, plan);
  const sourceSeek = useMemo(() => {
    const item = timelineGeometry(draft.clips, plan).items[selectedIndex];
    const progress = item?.durationMs
      ? Math.max(0, Math.min(1, (seekRequest.value - item.startMs) / item.durationMs))
      : 0;
    return { progress, revision: seekRequest.revision };
  }, [draft.clips, selectedIndex, seekRequest, plan]);
  const pause = useCallback(() => {
    playIntent.current++;
    setPlayRequest((before) => ({ playing: false, revision: before.revision + 1 }));
  }, []);
  useLayoutEffect(() => {
    pause();
  }, [signature, pause]);
  useEffect(() => {
    const pauseHidden = () => {
      if (document.hidden) pause();
    };
    document.addEventListener("visibilitychange", pauseHidden);
    return () => document.removeEventListener("visibilitychange", pauseHidden);
  }, [pause]);
  const seek = (value: number) => {
    pause();
    setPlayhead(value);
    setSeekRequest((before) => ({ value, revision: before.revision + 1 }));
  };
  const select = (index: number) => {
    onSelectClip(index);
    seek(geometry.items[index]?.startMs ?? 0);
  };
  async function updatePreview(startPlaying = false) {
    if (pending) return;
    pause();
    setPending(true);
    setError(null);
    const captured = signature;
    const capturedIntent = playIntent.current;
    try {
      const compiled = await previewEditTimeline(projectId, sessionId, draft, baselineVersion);
      if (mounted.current && current.current === captured) {
        setLoaded({ signature: captured, plan: compiled });
        // A late compilation may update the plan, but cannot undo a later pause.
        const resume = startPlaying && playIntent.current === capturedIntent;
        const position = Math.max(0, Math.min(compiled.duration_ms, playheadRef.current));
        seek(resume && position >= compiled.duration_ms ? 0 : position);
        setPlayRequest((before) => ({
          playing: resume && compiled.unsupported.length === 0,
          revision: before.revision + 1,
        }));
      }
    } catch (failure) {
      if (mounted.current && current.current === captured)
        setError(
          failure instanceof ApiError && failure.status === 404
            ? copy.previewUnavailable
            : failure instanceof Error
              ? failure.message
              : String(failure),
        );
    } finally {
      if (mounted.current) setPending(false);
    }
  }
  function togglePlayback() {
    setMode("composition");
    if (!plan) {
      void updatePreview(true);
      return;
    }
    if (playing) pause();
    else {
      seek(playhead >= plan.duration_ms ? 0 : playhead);
      setPlayRequest((before) => ({ playing: true, revision: before.revision + 1 }));
    }
  }
  return (
    <div className="editing-preview-workspace">
      <section className="editing-preview-stage" aria-label="剪辑监看区">
        <Tabs
          label="剪辑播放方式"
          type="card"
          activeKey={mode}
          destroyOnHidden
          onChange={(key) => {
            if (key === "source" || key === "composition") {
              seek(playhead);
              setMode(key);
            }
          }}
          tabBarExtraContent={
            <Button
              tone="primary"
              data-testid="editing-timeline-play"
              aria-label={playing ? copy.pauseTimeline : copy.playTimeline}
              disabled={
                pending || draft.clips.length === 0 || !geometry.valid || !!plan?.unsupported.length
              }
              onClick={togglePlayback}
            >
              {playing ? (
                <Pause size={18} aria-hidden="true" />
              ) : (
                <Play size={18} aria-hidden="true" />
              )}
              {pending ? copy.preparing : playing ? copy.pauseTimeline : copy.playTimeline}
            </Button>
          }
          items={[
            {
              key: "source",
              label: copy.source,
              children: (
                <EditingSourcePreview
                  projectId={projectId}
                  clips={draft.clips}
                  selectedIndex={selectedIndex}
                  seekRequest={sourceSeek}
                  pauseRevision={playRequest.revision}
                  onPosition={(progress) => {
                    const item = geometry.items[selectedIndex];
                    if (item) setPlayhead(item.startMs + progress * item.durationMs);
                  }}
                />
              ),
            },
            {
              key: "composition",
              label: copy.composition,
              children: (
                <div>
                  <p data-testid="editing-preview-status">{dirty ? copy.draft : copy.saved}</p>
                  <Button
                    onClick={() => void updatePreview()}
                    disabled={pending || draft.clips.length === 0}
                  >
                    {pending ? copy.preparing : copy.updatePreview}
                  </Button>
                  {error && <p role="alert">{error}</p>}
                  {!plan && !error && <p role="status">{loaded ? copy.stale : copy.noPreview}</p>}
                  {plan && plan.unsupported.length > 0 && (
                    <div role="alert" data-testid="editing-preview-unsupported">
                      <p>{copy.unsupported}</p>
                      <ul>
                        {plan.unsupported.map((reason) => (
                          <li key={reason}>{copy.unsupportedReasons[reason] ?? reason}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {plan && plan.unsupported.length === 0 && (
                    <EditingCompositionPlayer
                      key={plan.draft_fingerprint}
                      projectId={projectId}
                      plan={plan}
                      seekRequest={seekRequest}
                      onPosition={setPlayhead}
                      playRequest={playRequest}
                      onPlayingChange={setPlaying}
                      onClipChange={(id) => {
                        const index = draft.clips.findIndex((clip) => clip.id === id);
                        if (index >= 0) onSelectClip(index);
                      }}
                    />
                  )}
                </div>
              ),
            },
          ]}
        />
        <nav className="editing-clip-navigation" aria-label={copy.navigation}>
          <Button
            tone="ghost"
            aria-label={copy.previous}
            disabled={selectedIndex <= 0}
            onClick={() => select(selectedIndex - 1)}
          >
            <ChevronLeft size={18} aria-hidden="true" />
          </Button>
          <Select
            aria-label={copy.locate}
            value={selectedIndex}
            disabled={draft.clips.length === 0}
            onChange={(event) => select(Number(event))}
          >
            {draft.clips.map((clip, index) => (
              <option key={String(clip.id ?? index)} value={index}>
                {index + 1} / {draft.clips.length} · {editingClipLabel(clip, index)} ·{" "}
                {timelineTime(geometry.items[index].startMs)}
              </option>
            ))}
          </Select>
          <Button
            tone="ghost"
            aria-label={copy.next}
            disabled={selectedIndex >= draft.clips.length - 1}
            onClick={() => select(selectedIndex + 1)}
          >
            <ChevronRight size={18} aria-hidden="true" />
          </Button>
        </nav>
      </section>
      <EditingTimeline
        projectId={projectId}
        clips={draft.clips}
        selectedIndex={selectedIndex}
        plan={plan}
        onInteractionStart={pause}
        onUpdateClip={onUpdateClip}
        onReorder={(from, to) => {
          onReorder(from, to);
          const reordered = [...draft.clips];
          const [moved] = reordered.splice(from, 1);
          reordered.splice(to, 0, moved);
          seek(timelineGeometry(reordered).items[to]?.startMs ?? 0);
        }}
        playheadMs={playhead}
        onSeek={(value) => {
          seek(value);
          if (mode === "source" && draft.clips.length > 0) {
            const index = geometry.items.findIndex((item) => value < item.endMs);
            onSelectClip(index < 0 ? draft.clips.length - 1 : index);
          }
        }}
        onSelectClip={select}
      />
    </div>
  );
}
