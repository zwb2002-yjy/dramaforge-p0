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
/** Canonical OpenCut hand-off over the existing production manifest endpoint. */
export function EditingWorkspace({ projectId }: EditingWorkspaceProps) {
  const manifest = useQuery({
    queryKey: ["opencut-manifest", projectId],
    queryFn: () => fetchOpenCutManifest(projectId),
    enabled: projectId !== "demo",
  });
  const clips = clipsByTrack(manifest.data);

  return (
    <div className="qc-project-page" data-testid="editing-workspace">
      <header className="qc-page-heading">
        <p>剪辑</p>
        <h1>OpenCut 剪辑交接</h1>
        <span>时间线来自正式镜头产物；剪辑层不会反向修改 Shot 或 Production Graph。</span>
      </header>
      {manifest.isError && <div className="flash err">无法读取剪辑时间线：{String(manifest.error)}</div>}
      {manifest.data && (
        <>
          <dl>
            <dt>时长</dt>
            <dd>{manifest.data.timeline.duration_seconds}s</dd>
            <dt>画幅</dt>
            <dd>{manifest.data.timeline.aspect_ratio}</dd>
            <dt>正式镜头</dt>
            <dd>{manifest.data.shots.length}</dd>
          </dl>
          <section aria-label="正式时间线">
            <h2>正式时间线</h2>
            {clips.length === 0 ? (
              <p className="muted">暂无正式视频产物可交接。</p>
            ) : (
              <ol>
                {clips.map(({ track, clip }) => (
                  <li key={clip.id}>
                    <strong>{track}</strong> · {clip.timeline_start_seconds}s–
                    {clip.timeline_end_seconds}s · shot {clip.shot_id}
                  </li>
                ))}
              </ol>
            )}
          </section>
          <p className="callout" data-testid="editing-api-blocker">
            当前后端已提供正式时间线 manifest；save/load/export 的 EditingAdapter HTTP 路由尚未暴露，
            因此本页暂不伪造可持久化编辑操作。
          </p>
        </>
      )}
    </div>
  );
}
