import { Download, RefreshCw } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Disclosure,
  MetadataList,
  RecordItem,
  RecordList,
  SectionHeader,
  Alert,
  ExternalLink,
} from "../../components/ui";
import { RunStatusBadge } from "../../components/shared/RunStatusBadge";
import { artifactContentUrl } from "../../lib/api";
import { formatFileSize, formatMediaDuration } from "../../lib/formatMedia";
import type { FinalFilmJobRead, FinalFilmRead } from "./api";
import { FinalFilmPlayback } from "./FinalFilmPlayback";
import { deliveryCopy as copy } from "./deliveryCopy";
import "./editing-deliverables.css";

/** Read-only presentation; selection, refresh and export facts stay with the owner. */
export function EditingDeliverables({
  projectId,
  history,
  loading,
  failed,
  refreshing,
  onRefresh,
  onSelect,
  film,
  currentVersion,
}: {
  projectId: string;
  history: FinalFilmJobRead[];
  loading: boolean;
  failed: boolean;
  refreshing: boolean;
  onRefresh: () => void;
  onSelect: (runId: string) => void;
  film: FinalFilmRead | null;
  currentVersion?: number;
}) {
  return (
    <section className="editing-deliverables" aria-label={copy.region} data-has-film={!!film}>
      <Card className="editing-film-history">
        <SectionHeader
          title={copy.history}
          actions={
            <Button
              tone="ghost"
              aria-label={copy.refresh}
              onClick={onRefresh}
              disabled={refreshing}
            >
              <RefreshCw size={16} aria-hidden="true" />
            </Button>
          }
        >
          <Badge>{history.length}</Badge>
        </SectionHeader>
        {loading && (
          <p className="muted" role="status">
            {copy.loading}
          </p>
        )}
        {failed && <Alert role="alert" type="error" showIcon description={<>{copy.loadError}</>} />}
        {!loading && !failed && history.length === 0 && <p className="muted">{copy.empty}</p>}
        <RecordList aria-label={copy.historyList}>
          {history.map((job, index) => (
            <RecordItem
              key={job.node_run_id}
              selected={film?.node_run_id === job.node_run_id}
              title={copy.version(job.timeline_version)}
              status={<RunStatusBadge status={job.status} />}
              meta={[
                copy.record(index),
                ...(job.result
                  ? [
                      formatMediaDuration(job.result.duration_seconds),
                      formatFileSize(job.result.byte_size),
                    ]
                  : []),
              ].join(" · ")}
              actions={
                job.result && (
                  <Button
                    tone="ghost"
                    aria-label={copy.viewRecord(job.timeline_version, index)}
                    aria-pressed={film?.node_run_id === job.node_run_id}
                    onClick={() => onSelect(job.node_run_id)}
                  >
                    {copy.view}
                  </Button>
                )
              }
            >
              {job.error_summary && <p role="status">{job.error_summary}</p>}
            </RecordItem>
          ))}
        </RecordList>
      </Card>
      {film && (
        <Card className="final-film-result" data-testid="final-film-result">
          <SectionHeader title={`${copy.film} · v${film.timeline_version}`}>
            <Badge tone={film.timeline_version === currentVersion ? "success" : "default"}>
              {film.timeline_version === currentVersion ? copy.current : copy.historical}
            </Badge>
            {film.timeline_version !== currentVersion && (
              <small className="muted">{copy.currentVersion(currentVersion)}</small>
            )}
          </SectionHeader>
          <div className="editing-film-summary" aria-label={copy.summary}>
            <span>{formatMediaDuration(film.duration_seconds)}</span>
            <span>{film.mime_type === "video/mp4" ? "MP4" : film.mime_type}</span>
            <span>{formatFileSize(film.byte_size)}</span>
            {film.storage_state !== "available" && (
              <Badge tone="warning">
                {copy.storageLabels[film.storage_state] ?? film.storage_state}
              </Badge>
            )}
          </div>
          <FinalFilmPlayback
            key={`${projectId}:${film.artifact_id}`}
            projectId={projectId}
            artifactId={film.artifact_id}
          />
          <div className="editing-film-downloads">
            <ExternalLink
              data-testid="final-film-download"
              href={artifactContentUrl(projectId, film.artifact_id)}
              download={`dramaforge-final-film-${film.content_hash.slice(0, 12)}.mp4`}
            >
              <Download size={16} aria-hidden="true" />
              {copy.download}
            </ExternalLink>
            {film.subtitle_artifact_id ? (
              <ExternalLink
                type="text"
                data-testid="final-film-subtitle-download"
                href={artifactContentUrl(projectId, film.subtitle_artifact_id)}
                download={`dramaforge-final-film-${film.content_hash.slice(0, 12)}.srt`}
              >
                {copy.subtitles(film.subtitle_cue_count ?? 0)}
              </ExternalLink>
            ) : (
              <span className="muted" data-testid="final-film-no-subtitles">
                {copy.noSubtitles}
              </span>
            )}
          </div>
          <Disclosure title={copy.fileInfo} testId="final-film-diagnostics">
            <MetadataList
              items={[
                {
                  label: copy.session,
                  value: film.edit_session_id,
                  testId: "final-film-session-reference",
                },
                { label: copy.artifact, value: film.artifact_id },
                { label: copy.hash, value: film.content_hash },
                { label: copy.duration, value: film.duration_seconds },
                { label: copy.mimeType, value: film.mime_type },
                { label: copy.bytes, value: film.byte_size },
                {
                  label: copy.storage,
                  value: copy.storageLabels[film.storage_state] ?? film.storage_state,
                },
                ...(film.subtitle_artifact_id
                  ? [
                      { label: copy.subtitleArtifact, value: film.subtitle_artifact_id },
                      {
                        label: copy.subtitleHash,
                        value: film.subtitle_content_hash ?? copy.unavailable,
                      },
                    ]
                  : []),
                {
                  label: copy.assertions,
                  value:
                    film.ffprobe?.assertions &&
                    typeof film.ffprobe.assertions === "object" &&
                    !Array.isArray(film.ffprobe.assertions)
                      ? Object.entries(film.ffprobe.assertions)
                          .map(([key, value]) => `${key}=${String(value)}`)
                          .join(" · ")
                      : copy.unavailable,
                },
              ]}
            />
          </Disclosure>
        </Card>
      )}
    </section>
  );
}
