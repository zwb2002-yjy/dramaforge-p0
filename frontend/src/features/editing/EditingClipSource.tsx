import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Button, Checkbox, Dialog, Field, ExternalLink } from "../../components/ui";
import { artifactContentUrl, fetchOpenCutManifest, type OpenCutManifestRead } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import type { EditableClip } from "./useTimelineDraft";
import { timelineCopy as copy } from "./timelineCopy";
import "./editing-clip-source.css";

type SourceClip = OpenCutManifestRead["tracks"][number]["clips"][number];

function sourceFor(
  manifest: OpenCutManifestRead | undefined,
  clip: EditableClip,
  projectId: string,
) {
  if (manifest?.project_id !== projectId) return undefined;
  return (manifest.tracks ?? [])
    .flatMap((track) => track.clips)
    .find(
      (source) =>
        source.track_kind === "video" && source.shot_id === clip.shot_id && source.artifact_id,
    );
}

/** A new Formal source enters the local draft only after an explicit comparison. */
export function EditingClipSource({
  projectId,
  sessionId,
  clip,
  onReplace,
  onReplaced,
  onOpenShot,
}: {
  projectId: string;
  sessionId: string;
  clip: EditableClip;
  onReplace: (clip: EditableClip) => void;
  /** The comparison trigger disappears after a replacement; focus the next explicit action. */
  onReplaced?: () => void;
  onOpenShot?: (sceneId: string, shotId: string, clipId: string) => void;
}) {
  const manifest = useQuery({
    queryKey: queryKeys.production.opencutManifest(projectId),
    queryFn: () => fetchOpenCutManifest(projectId),
    staleTime: 30_000,
  });
  const source = sourceFor(manifest.data, clip, projectId);
  const [comparison, setComparison] = useState<{ source: SourceClip; clip: EditableClip } | null>(
    null,
  );
  const [resetCrop, setResetCrop] = useState(false);
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [mediaDuration, setMediaDuration] = useState<{
    artifactId: string;
    seconds: number;
  } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const intent = useRef(0);
  const replaced = useRef(false);
  const currentClip = useRef(clip);
  currentClip.current = clip;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const close = () => {
    intent.current++;
    setComparisonOpen(false);
    setError(null);
    setPending(false);
  };
  // OpenCut duration is the Shot's plan. Only decoded media describes its actual end.
  const duration =
    mediaDuration?.artifactId === comparison?.source.artifact_id
      ? (mediaDuration?.seconds ?? NaN)
      : NaN;
  const durationValid = Number.isFinite(duration) && duration > 0;
  const sourceIn = Number(clip.source_in_seconds ?? 0);
  const sourceOut = clip.source_out_seconds == null ? duration : Number(clip.source_out_seconds);
  const needsReset =
    !Number.isFinite(sourceIn) ||
    sourceIn < 0 ||
    sourceIn >= duration ||
    !Number.isFinite(sourceOut) ||
    sourceOut <= sourceIn ||
    sourceOut > duration;
  const changed = Boolean(source && source.artifact_id !== clip.artifact_id);
  async function apply() {
    if (!comparisonOpen || !comparison || !durationValid || (needsReset && !resetCrop) || pending)
      return;
    const captured = comparison;
    const token = intent.current;
    setPending(true);
    setError(null);
    try {
      const checked = await manifest.refetch();
      if (!mounted.current || intent.current !== token) return;
      if (checked.isError) {
        setError(copy.sourceError);
        return;
      }
      const latest = sourceFor(checked.data, captured.clip, projectId);
      if (
        latest?.artifact_id !== captured.source.artifact_id ||
        JSON.stringify(currentClip.current) !== JSON.stringify(captured.clip)
      ) {
        setError(copy.sourceChanged);
        return;
      }
      onReplace({
        ...captured.clip,
        artifact_id: captured.source.artifact_id,
        ...(resetCrop
          ? { source_in_seconds: 0, source_out_seconds: duration }
          : captured.clip.source_out_seconds == null
            ? { source_out_seconds: duration }
            : {}),
      });
      replaced.current = true;
      close();
    } catch {
      if (mounted.current && intent.current === token) setError(copy.sourceError);
    } finally {
      if (mounted.current && intent.current === token) setPending(false);
    }
  }
  return (
    <section className="editing-clip-source" aria-label={copy.sourceLink}>
      <div className="editing-source-actions">
        {typeof clip.scene_id === "string" && typeof clip.shot_id === "string" && (
          <ExternalLink
            type="link"
            href={`/projects/${encodeURIComponent(projectId)}/scenes/${encodeURIComponent(clip.scene_id)}?${new URLSearchParams({ shotId: clip.shot_id, editSessionId: sessionId, editClipId: String(clip.id) })}`}
            onClick={(event) => {
              if (
                onOpenShot &&
                !event.ctrlKey &&
                !event.metaKey &&
                !event.shiftKey &&
                !event.altKey &&
                event.button === 0
              ) {
                event.preventDefault();
                onOpenShot(String(clip.scene_id), String(clip.shot_id), String(clip.id));
              }
            }}
          >
            {copy.openShot}
          </ExternalLink>
        )}
        <Button
          tone="ghost"
          disabled={manifest.isFetching || pending}
          onClick={() => void manifest.refetch()}
        >
          {manifest.isFetching ? copy.checkingSource : copy.checkSource}
        </Button>
      </div>
      <p role={manifest.isError ? "alert" : "status"}>
        {manifest.isError
          ? copy.sourceError
          : manifest.isPending
            ? copy.checkingSource
            : changed
              ? copy.sourceUpdated
              : source
                ? copy.sourceCurrent
                : copy.sourceMissing}
      </p>
      {changed && (
        <Button
          onClick={() => {
            intent.current++;
            replaced.current = false;
            setComparison({ source: source!, clip: { ...clip } });
            setComparisonOpen(true);
            setResetCrop(false);
            setMediaDuration(null);
            setPending(false);
            setError(null);
          }}
        >
          {copy.compareSource}
        </Button>
      )}
      {comparison && (
        <Dialog
          open={comparisonOpen}
          afterClose={() => {
            setComparison(null);
            if (replaced.current) onReplaced?.();
          }}
          title={copy.replaceTitle}
          size="wide"
          onClose={close}
          actions={
            <>
              <Button onClick={close}>{copy.cancel}</Button>
              <Button
                tone="primary"
                disabled={pending || !durationValid || (needsReset && !resetCrop) || error !== null}
                onClick={() => void apply()}
              >
                {pending ? copy.checkingSource : copy.applySource}
              </Button>
            </>
          }
        >
          <p>{copy.replaceNotice}</p>
          <div className="editing-source-comparison">
            {[
              { label: copy.currentVideo, artifactId: comparison.clip.artifact_id },
              { label: copy.newVideo, artifactId: comparison.source.artifact_id },
            ].map(({ label, artifactId }) => (
              <figure key={label}>
                <figcaption>{label}</figcaption>
                {typeof artifactId === "string" && (
                  <video
                    key={artifactId}
                    controls
                    preload="metadata"
                    src={artifactContentUrl(projectId, artifactId)}
                    aria-label={label}
                    onLoadedMetadata={(event) => {
                      if (label !== copy.newVideo) return;
                      const seconds = Math.floor(event.currentTarget.duration * 1000) / 1000;
                      if (Number.isFinite(seconds) && seconds > 0)
                        setMediaDuration({ artifactId, seconds });
                      else setError(copy.invalidSource);
                    }}
                    onError={() => {
                      if (label === copy.newVideo) setError(copy.sourceMediaError);
                    }}
                  />
                )}
              </figure>
            ))}
          </div>
          {!durationValid && !error && <p role="status">{copy.readingSourceDuration}</p>}
          {durationValid && needsReset && <p role="alert">{copy.shortSource}</p>}
          <Field>
            <Checkbox
              checked={resetCrop}
              disabled={pending}
              onChange={(event) => setResetCrop(event.target.checked)}
            />
            {copy.resetCrop}
          </Field>
          {error && <p role="alert">{error}</p>}
        </Dialog>
      )}
    </section>
  );
}
