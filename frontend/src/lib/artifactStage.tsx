import { artifactContentUrl } from "./api";
import type { ProjectArtifact } from "./projectMedia";

type ArtifactPreviewProps = {
  projectId: string;
  /** 当前要展示的大图 artifact；null 时显示空状态 */
  stageArt: ProjectArtifact | null;
  /** 大图上方角标文字；默认 "最新分镜图" */
  stageLabel?: string;
  /** 缩略图列表 */
  previewArts: ProjectArtifact[];
  /** 缩略图最多显示数量；默认 8 */
  previewLimit?: number;
  /** 空状态提示；默认三段文字 */
  emptyLines?: [string, string, string];
  /** 测试 id 前缀 */
  testId?: string;
};

export function ArtifactStage({
  projectId,
  stageArt,
  stageLabel = "最新分镜图",
  previewArts,
  previewLimit = 8,
  emptyLines = ["分镜板产物预览", "导入剧本并生产后", "在此回看画面"],
  testId = "artifact-stage",
}: ArtifactPreviewProps) {
  const stageUrl =
    stageArt && projectId !== "demo" ? artifactContentUrl(projectId, stageArt.id) : null;
  return (
    <div className="panel" style={{ padding: "0.85rem" }}>
      <h3 style={{ marginBottom: "0.65rem" }}>预览 / 交付</h3>
      <div className="stage-phone" data-testid={`${testId}-phone`}>
        {stageUrl ? (
          <>
            <span className="stage-badge">{stageLabel}</span>
            <img src={stageUrl} alt="preview" data-testid={`${testId}-img`} />
          </>
        ) : (
          <div className="stage-empty">
            {emptyLines[0]}
            <br />
            {emptyLines[1]}
            <br />
            {emptyLines[2]}
          </div>
        )}
      </div>
      <div className="stage-meta" data-testid={`${testId}-meta`}>
        {stageArt ? (
          <>
            <div>
              <code>{stageArt.object_key.split("/").slice(-1)[0]}</code>
            </div>
            <div>
              {stageArt.byte_size}B ·{" "}
              <a href={stageUrl!} target="_blank" rel="noreferrer">
                打开原图
              </a>
            </div>
          </>
        ) : (
          <span>等待产物…</span>
        )}
      </div>
      <div className="ref-strip" style={{ marginTop: "0.65rem" }} data-testid={`${testId}-refs`}>
        {previewArts.slice(0, previewLimit).map((a) => (
          <a
            key={a.id}
            className="ref-chip"
            href={artifactContentUrl(projectId, a.id)}
            target="_blank"
            rel="noreferrer"
            title={a.object_key}
          >
            <img src={artifactContentUrl(projectId, a.id)} alt="" />
          </a>
        ))}
        {previewArts.length === 0 && <div className="ref-chip">空</div>}
      </div>
    </div>
  );
}
