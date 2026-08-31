import { useQuery } from "@tanstack/react-query";

import { fetchOpenCutManifest, type OpenCutManifestRead } from "../../lib/api";

type EditingWorkspaceProps = {
  projectId: string;
};

function clipsByTrack(manifest: OpenCutManifestRead | undefined) {
  return (manifest?.tracks ?? []).flatMap((track) =>
    track.clips.map((clip) => ({ track: track.name, clip })),
  );
}

function videoClips(manifest: OpenCutManifestRead | undefined) {
  return clipsByTrack(manifest).filter(({ clip }) => clip.track_kind === "video");
}

/** Canonical OpenCut hand-off over the existing production manifest endpoint. */
export function EditingWorkspace({ projectId }: EditingWorkspaceProps) {
  const manifest = useQuery({
    queryKey: ["opencut-manifest", projectId],
    queryFn: () => fetchOpenCutManifest(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
  });
  const clips = clipsByTrack(manifest.data);
  const formalVideoClips = videoClips(manifest.data);
  const formalShotIds = new Set(formalVideoClips.map(({ clip }) => clip.shot_id));
  const incompleteShotCount =
    manifest.data?.shots.filter((shot) => !formalShotIds.has(shot.shot_id)).length ?? 0;
  const isEmptyProject = manifest.data?.shots.length === 0 && clips.length === 0;

  return (
    <div className="qc-project-page" data-testid="editing-workspace">
      <header className="qc-page-heading">
        <p>剪辑</p>
        <h1>OpenCut 剪辑交接</h1>
        <span>时间线来自正式镜头产物；剪辑层不会反向修改 Shot 或 Production Graph。</span>
        <p className="callout" data-testid="editing-read-only">
          只读交接预览 · 仅展示已确认的正式视频，不会触发生成或写回生产事实。
        </p>
      </header>
      {manifest.isLoading && (
        <p className="muted" data-testid="editing-loading">
          正在读取正式剪辑时间线…
        </p>
      )}
      {manifest.isError && (
        <div className="flash err">无法读取剪辑时间线：{String(manifest.error)}</div>
      )}
      {!manifest.isLoading && !manifest.isError && !manifest.data && (
        <p className="muted" data-testid="editing-empty-project">
          {projectId === "demo"
            ? "演示项目没有真实 OpenCut manifest。"
            : "项目暂无可交接的正式视频。"}
        </p>
      )}
      {manifest.data && !manifest.isError && (
        <>
          <dl>
            <dt>时长</dt>
            <dd>{manifest.data.timeline.duration_seconds}s</dd>
            <dt>画幅</dt>
            <dd>{manifest.data.timeline.aspect_ratio}</dd>
            <dt>正式镜头</dt>
            <dd>
              {formalVideoClips.length} / {manifest.data.shots.length}
            </dd>
          </dl>
          {isEmptyProject && (
            <p className="muted" data-testid="editing-empty-project">
              项目暂无镜头或正式视频可交接。
            </p>
          )}
          {incompleteShotCount > 0 && (
            <p className="callout" data-testid="editing-partial-state">
              {`已交接 ${formalVideoClips.length} 个正式视频；另有 ${incompleteShotCount} 个镜头尚未确认正式视频，已跳过，不会进入时间线。`}
            </p>
          )}
          <section aria-label="正式时间线">
            <h2>正式时间线</h2>
            {clips.length === 0 ? (
              <p className="muted" data-testid="editing-no-clips">
                暂无正式视频产物可交接。
              </p>
            ) : (
              <ol>
                {clips.map(({ track, clip }) => (
                  <li key={clip.id} data-testid="editing-clip">
                    <strong>{track}</strong> · {clip.timeline_start_seconds}s–
                    {clip.timeline_end_seconds}s · 项目 {manifest.data.project_id} · 场景{" "}
                    {clip.scene_id} · 镜头 {clip.shot_id}
                    <br />
                    <small>
                      正式 Artifact {clip.artifact_id ?? "未知"}
                      {clip.source_url ? ` · 存储 ${clip.source_url}` : ""}
                    </small>
                  </li>
                ))}
              </ol>
            )}
          </section>
          <p className="callout" data-testid="editing-api-blocker">
            {
              "当前后端已提供正式时间线 manifest；save/load/export 的 EditingAdapter HTTP 路由尚未暴露，因此本页暂不伪造可持久化编辑操作。"
            }
          </p>
        </>
      )}
    </div>
  );
}
