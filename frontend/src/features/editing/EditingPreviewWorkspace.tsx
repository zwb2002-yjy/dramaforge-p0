import { useEffect, useRef, useState } from "react";
import { Button, Tab, Tabs } from "../../components/ui";
import { EditingSourcePreview } from "./EditingSourcePreview";
import { EditingTimeline } from "./EditingTimeline";
import { EditingCompositionPlayer } from "./EditingCompositionPlayer";
import { previewEditTimeline, type TimelinePreviewRead } from "./api";
import type { EditableTimeline } from "./useTimelineDraft";
import { timelineGeometry } from "./timelineGeometry";
import { timelineCopy as copy } from "./timelineCopy";

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
  const [error, setError] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState(0);
  const [seekRequest, setSeekRequest] = useState({ value: 0, revision: 0 });
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
  const seek = (value: number) => {
    setPlayhead(value);
    setSeekRequest((before) => ({ value, revision: before.revision + 1 }));
  };
  async function updatePreview() {
    setPending(true);
    setError(null);
    const captured = signature;
    try {
      const compiled = await previewEditTimeline(projectId, sessionId, draft, baselineVersion);
      if (mounted.current && current.current === captured) {
        setLoaded({ signature: captured, plan: compiled });
        seek(0);
      }
    } catch (failure) {
      if (mounted.current && current.current === captured)
        setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      if (mounted.current) setPending(false);
    }
  }
  return (
    <section className="editing-preview-workspace">
      <Tabs label="剪辑播放方式">
        <Tab active={mode === "source"} onClick={() => setMode("source")}>
          {copy.source}
        </Tab>
        <Tab active={mode === "composition"} onClick={() => setMode("composition")}>
          {copy.composition}
        </Tab>
      </Tabs>
      {mode === "source" ? (
        <EditingSourcePreview
          projectId={projectId}
          clips={draft.clips}
          selectedIndex={selectedIndex}
        />
      ) : (
        <div role="tabpanel" aria-label={copy.composition}>
          <p data-testid="editing-preview-status">{dirty ? copy.draft : copy.saved}</p>
          <Button
            onClick={() => void updatePreview()}
            disabled={pending || draft.clips.length === 0}
          >
            {pending ? copy.preparing : copy.updatePreview}
          </Button>
          {error && <p role="alert">{error}</p>}
          {!plan && <p role="status">{loaded ? copy.stale : copy.noPreview}</p>}
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
              onClipChange={(id) => {
                const index = draft.clips.findIndex((clip) => clip.id === id);
                if (index >= 0) onSelectClip(index);
              }}
            />
          )}
        </div>
      )}
      <EditingTimeline
        clips={draft.clips}
        selectedIndex={selectedIndex}
        plan={plan}
        onUpdateClip={onUpdateClip}
        onReorder={(from, to) => {
          onReorder(from, to);
          const reordered = [...draft.clips];
          const [moved] = reordered.splice(from, 1);
          reordered.splice(to, 0, moved);
          seek(timelineGeometry(reordered).items[to]?.startMs ?? 0);
        }}
        playheadMs={playhead}
        onSeek={seek}
        onSelectClip={(index) => {
          onSelectClip(index);
          seek(timelineGeometry(draft.clips, plan).items[index]?.startMs ?? 0);
        }}
      />
    </section>
  );
}
