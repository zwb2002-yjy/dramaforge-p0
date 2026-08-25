import { useEffect, useMemo, useState } from "react";

import type { AssetRead, CanvasRevisionRead, DirectorBoardRead, ExperimentRead, ModelRead, OpenCutManifestRead, ProjectSnapshot, ReviewAnnotationRead, ShotCanvasUpdateResponse, ShotChangeProposalResult, ShotRead } from "../../lib/api";

type Suggestion = {
  id: string;
  title: string;
  body: string;
  change: string;
  impact: string;
};

type CanvasSaveResult = ShotRead | ShotCanvasUpdateResponse | void;

type ProfessionalWorkbenchProps = {
  projectId: string;
  shots: ShotRead[];
  snapshot?: ProjectSnapshot;
  selectedShotId: string | null;
  onSelectShot: (shotId: string) => void;
  onRerun?: (shotId: string) => void;
  onStart?: (shotId: string) => void;
  onSave?: (shot: ShotRead, input: { visual_description: string; shot_type: string; camera_move?: string; dialogue: string }) => Promise<CanvasSaveResult>;
  onPropose?: (shot: ShotRead, input: { summary: string; replacement_payload: Record<string, unknown>; affected_node_keys: string[]; reusable_artifact_ids: string[] }) => Promise<ShotChangeProposalResult>;
  onConfirmProposal?: (shotId: string, proposalId: string, revisionId: string) => Promise<void>;
  revisions?: CanvasRevisionRead[];
  assets?: AssetRead[];
  onCreateAsset?: (input: { kind: string; name: string; description: string; tags: string[] }) => Promise<void>;
  onUpdateAsset?: (asset: AssetRead, input: { status: "active" | "archived" }) => Promise<void>;
  experiments?: ExperimentRead[];
  annotations?: ReviewAnnotationRead[];
  openCutManifest?: OpenCutManifestRead;
  onCreateExperiment?: (input: { name: string; selected_model: string }) => Promise<void>;
  onStartExperiment?: (experimentId: string, targetNodeKey: "keyframe" | "video") => Promise<void>;
  onDecideExperiment?: (experimentId: string, input: { decision: "accepted" | "rejected" | "kept"; adoption_scope?: "current_node" | "keyframe_keep_video" | "keyframe_rerun_downstream"; candidate_artifact_id?: string | null }) => Promise<void>;
  models?: ModelRead[];
  onCreateAnnotation?: (input: { artifact_id?: string | null; target_kind: "shot" | "video_time" | "image_point" | "image_region"; time_start: string | null; time_end: string | null; x?: string | null; y?: string | null; width?: string | null; height?: string | null; note: string }) => Promise<void>;
  directorBoard?: DirectorBoardRead | null;
  onSaveDirectorBoard?: (input: { mode: "2d" | "rough_3d"; camera: Record<string, unknown>; characters: Array<Record<string, unknown>>; scene: Record<string, unknown> }) => Promise<void>;
};

const PIPELINE = [
  ["keyframe", "关键帧"],
  ["video", "视频"],
  ["review", "审片"],
  ["edit", "剪辑"],
] as const;

function statusLabel(status: string): string {
  if (["completed", "cached", "completed_after_cancel", "approved"].includes(status)) return "已完成";
  if (["queued", "running", "leased"].includes(status)) return "运行中";
  if (["failed", "blocked_budget"].includes(status)) return "需处理";
  return "未开始";
}

function statusTone(status: string): string {
  if (["completed", "cached", "completed_after_cancel", "approved"].includes(status)) return "done";
  if (["queued", "running", "leased"].includes(status)) return "running";
  if (["failed", "blocked_budget"].includes(status)) return "attention";
  return "idle";
}

function shotRunStatus(shot: ShotRead, snapshot?: ProjectSnapshot): string {
  const runs = snapshot?.node_runs.filter((run) => String(run.input_snapshot?.shot_id ?? "") === shot.id) ?? [];
  if (runs.some((run) => run.status === "failed")) return "failed";
  if (runs.some((run) => ["queued", "running", "leased"].includes(run.status))) return "running";
  if (runs.some((run) => ["completed", "cached", "completed_after_cancel"].includes(run.status))) return "completed";
  return shot.status;
}

function sceneName(sceneId: string, index: number): string {
  return sceneId ? `场景 ${index + 1}` : "未命名场景";
}

export function ProfessionalWorkbench({
  projectId,
  shots,
  snapshot,
  selectedShotId,
  onSelectShot,
  onRerun,
  onStart,
  onSave,
  revisions = [],
  onPropose,
  onConfirmProposal,
  assets = [],
  onCreateAsset,
  onUpdateAsset,
  experiments = [],
  annotations = [],
  openCutManifest,
  onCreateExperiment,
  onStartExperiment,
  onDecideExperiment,
  models = [],
  onCreateAnnotation,
  directorBoard,
  onSaveDirectorBoard,
}: ProfessionalWorkbenchProps) {
  const [assistantMode, setAssistantMode] = useState<"auto" | "manual">("manual");
  const [activeTab, setActiveTab] = useState<"canvas" | "assets" | "director" | "review">("canvas");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savedDrafts, setSavedDrafts] = useState<Record<string, string>>({});
  const [rejected, setRejected] = useState<Record<string, boolean>>({});
  const [accepted, setAccepted] = useState<Record<string, boolean>>({});
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [assetKind, setAssetKind] = useState("character");
  const [assetName, setAssetName] = useState("");
  const [assetDescription, setAssetDescription] = useState("");
  const [assetTags, setAssetTags] = useState("");
  const [boardMode, setBoardMode] = useState<"2d" | "rough_3d">("2d");
  const [boardCamera, setBoardCamera] = useState("中景 · 50mm · 平视");
  const [boardBlocking, setBoardBlocking] = useState("主角 x=0.35 y=0.55 · 面向镜头");
  const [boardPose, setBoardPose] = useState("自然站立");
  const [boardExpression, setBoardExpression] = useState("克制");
  const [boardGaze, setBoardGaze] = useState("看向对手");
  const [boardScene, setBoardScene] = useState("基础场景与空间关系");
  const [experimentName, setExperimentName] = useState("");
  const [experimentModel, setExperimentModel] = useState("");
  const [annotationStart, setAnnotationStart] = useState("");
  const [annotationEnd, setAnnotationEnd] = useState("");
  const [annotationKind, setAnnotationKind] = useState<"shot" | "video_time" | "image_point" | "image_region">("video_time");
  const [annotationArtifactId, setAnnotationArtifactId] = useState("");
  const [annotationX, setAnnotationX] = useState("");
  const [annotationY, setAnnotationY] = useState("");
  const [annotationWidth, setAnnotationWidth] = useState("");
  const [annotationHeight, setAnnotationHeight] = useState("");
  const [annotationNote, setAnnotationNote] = useState("");
  const [proposalIds, setProposalIds] = useState<Record<string, string>>({});
  const [proposalImpacts, setProposalImpacts] = useState<Record<string, ShotChangeProposalResult["impact"]>>({});

  useEffect(() => {
    if (!shots.length) return;
    setDrafts((current) => {
      const next = { ...current };
      for (const shot of shots) next[shot.id] ??= shot.visual_description;
      return next;
    });
    setSavedDrafts((current) => {
      const next = { ...current };
      for (const shot of shots) next[shot.id] ??= shot.visual_description;
      return next;
    });
  }, [shots]);
  useEffect(() => {
    if (!directorBoard) return;
    setBoardMode(directorBoard.mode);
    setBoardCamera(String(directorBoard.camera.summary ?? "中景 · 50mm · 平视"));
    const character = directorBoard.characters[0] ?? {};
    setBoardBlocking(String(character.blocking ?? "主角 x=0.35 y=0.55 · 面向镜头"));
    setBoardPose(String(character.pose ?? "自然站立"));
    setBoardExpression(String(character.expression ?? "克制"));
    setBoardGaze(String(character.gaze ?? "看向对手"));
    setBoardScene(String(directorBoard.scene.description ?? "基础场景与空间关系"));
  }, [directorBoard]);

  const selectedShot = shots.find((shot) => shot.id === selectedShotId) ?? shots[0] ?? null;
  const selectedId = selectedShot?.id ?? null;
  const selectedText = selectedId ? drafts[selectedId] ?? selectedShot?.visual_description ?? "" : "";
  const isDirty = selectedId ? selectedText !== (savedDrafts[selectedId] ?? selectedShot?.visual_description ?? "") : false;
  const selectedStatus = selectedShot ? shotRunStatus(selectedShot, snapshot) : "";
  const experimentModelRecord = models.find((model) => model.id === experimentModel);
  const imageArtifacts = (snapshot?.artifacts ?? []).filter((artifact) => artifact.mime_type.startsWith("image/"));
  const candidateArtifactIds = (item: ExperimentRead): string[] => item.candidate_artifact_ids ?? [];

  const scenes = useMemo(() => {
    const groups = new Map<string, ShotRead[]>();
    for (const shot of shots) groups.set(shot.scene_id, [...(groups.get(shot.scene_id) ?? []), shot]);
    return [...groups.entries()];
  }, [shots]);

  const suggestions = useMemo<Suggestion[]>(() => {
    if (!selectedShot) return [];
    return [
      {
        id: `${selectedShot.id}:blocking`,
        title: "补齐动作因果",
        body: "当前镜头只有结果描述，建议补充动作起点、终点与角色反应，方便视频模型保持连续性。",
        change: "增加动作起点 / 终点 / 反应",
        impact: "只影响当前镜头的视频节点；关键帧可复用。",
      },
      {
        id: `${selectedShot.id}:camera`,
        title: "明确机位与景别",
        body: "建议把景别和镜头运动写入导演语义，不替你选择风格，只让模型执行更可追溯。",
        change: "补充中近景、缓慢推进",
        impact: "会让当前镜头提示词版本产生新快照。",
      },
      {
        id: `${selectedShot.id}:identity`,
        title: "锁定身份锚点",
        body: "检测到该镜头包含主角。建议显式引用角色身份资产，避免关键帧通过后视频阶段漂移。",
        change: "引用角色 Canonical 身份锚点",
        impact: "不会重跑历史结果；下次视频执行使用该引用。",
      },
    ];
  }, [selectedShot]);

  async function applySuggestion(suggestion: Suggestion) {
    if (!selectedId || !selectedShot) return;
    const suffix = `

[导演助手建议 · ${suggestion.title}] ${suggestion.change}。`;
    const nextText = `${drafts[selectedId] ?? ""}${suffix}`.trim();
    setDrafts((current) => ({ ...current, [selectedId]: nextText }));
    setRejected((current) => ({ ...current, [suggestion.id]: false }));
    try {
      const proposal = await onPropose?.(selectedShot, {
        summary: suggestion.title,
        replacement_payload: { visual_description: nextText, suggestion_id: suggestion.id },
        affected_node_keys: [suggestion.id.endsWith(":camera") ? "prompt" : "video"],
        reusable_artifact_ids: ["keyframe"],
      });
      if (proposal) {
        setProposalIds((current) => ({ ...current, [suggestion.id]: proposal.proposal.id }));
        setProposalImpacts((current) => ({ ...current, [suggestion.id]: proposal.impact }));
      }
      setAccepted((current) => ({ ...current, [suggestion.id]: true }));
      setSaveMessage(proposal ? "结构化变更提案已创建；保存画布后才会确认并写入正式事实。" : "建议已写入变更预览，保存画布后才会成为正式事实。");
    } catch (error) {
      setSaveMessage(error instanceof Error ? `提案创建失败：${error.message}` : "提案创建失败，请重试。");
    }
  }
  function referenceAsset(asset: AssetRead) {
    if (!selectedId) return;
    const usage = asset.kind === "character" ? "身份" : asset.kind === "action" ? "动作" : "视觉";
    setDrafts((current) => ({
      ...current,
      [selectedId]: `${current[selectedId] ?? ""}
@${asset.name}[用途:${usage};版本:v${asset.version}]`.trim(),
    }));
    setSaveMessage(`已引用 @${asset.name}；保存画布后成为正式输入。`);
  }
  function rejectSuggestion(suggestion: Suggestion) {
    setRejected((current) => ({ ...current, [suggestion.id]: true }));
    setAccepted((current) => ({ ...current, [suggestion.id]: false }));
  }

  async function saveCanvas() {
    if (!selectedId || !selectedShot) return;
    try {
      const saved = await onSave?.(selectedShot, {
        visual_description: selectedText,
        shot_type: selectedShot.shot_type,
        camera_move: selectedShot.camera_move ?? "static",
        dialogue: selectedShot.dialogue,
      });
      const savedShot = saved && "shot" in saved ? saved.shot : saved;
      const revisionId = saved && "revision_id" in saved ? saved.revision_id : null;
      const pendingProposalIds = Object.entries(proposalIds)
        .filter(([key]) => key.startsWith(`${selectedId}:`))
        .map(([, proposalId]) => proposalId)
        .filter(Boolean);
      if (revisionId && onConfirmProposal) {
        await Promise.all(pendingProposalIds.map((proposalId) => onConfirmProposal(selectedId, proposalId, revisionId)));
        setProposalIds((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(`${selectedId}:`))));
        setProposalImpacts((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !key.startsWith(`${selectedId}:`))));
      }
      setSavedDrafts((current) => ({ ...current, [selectedId]: selectedText }));
      setSaveMessage(savedShot ? `画布版本已保存（v${savedShot.version}）。后续执行将以这份正式镜头语义为事实源。` : "画布版本已保存。后续执行将以这份正式镜头语义为事实源。");
    } catch (error) {
      setSaveMessage(error instanceof Error ? `保存失败：${error.message}` : "保存失败，请重试。");
    }
  }
  return (
    <section className="professional-workbench" data-testid="professional-workbench" data-project-id={projectId}>
      <header className="professional-workbench-header">
        <div>
          <span className="director-stage-kicker">专业工作台 · Canvas is source of truth</span>
          <h2>场景与镜头</h2>
          <p className="muted">正式画布决定执行；导演助手只能提出可审阅的变更。</p>
        </div>
        <div className="professional-toolbar">
          <div className="workbench-tabs" role="tablist" aria-label="工作台视图">
            <button type="button" className={activeTab === "canvas" ? "active" : ""} onClick={() => setActiveTab("canvas")}>画布</button>
            <button type="button" className={activeTab === "assets" ? "active" : ""} onClick={() => setActiveTab("assets")}>资产</button>
            <button type="button" className={activeTab === "director" ? "active" : ""} onClick={() => setActiveTab("director")}>导演台</button>
            <button type="button" className={activeTab === "review" ? "active" : ""} onClick={() => setActiveTab("review")}>审片</button>
          </div>
          <span className="fact-source-badge">正式事实源</span>
        </div>      </header>

      <div className="professional-workbench-grid">
        <aside className="scene-rail" aria-label="场景列表">
          <div className="scene-rail-header"><span>场景</span><strong>{scenes.length}</strong></div>
          {scenes.length === 0 && <p className="muted">还没有镜头。可从快速模式导入剧本，或在后续版本手动创建场景。</p>}
          {scenes.map(([sceneId, sceneShots], index) => (
            <section key={sceneId || index} className="scene-group">
              <div className="scene-group-title"><span>{sceneName(sceneId, index)}</span><small>{sceneShots.length} 镜头</small></div>
              {sceneShots.map((shot) => {
                const status = shotRunStatus(shot, snapshot);
                return (
                  <button key={shot.id} type="button" className={`shot-list-item ${selectedId === shot.id ? "selected" : ""}`} onClick={() => onSelectShot(shot.id)}>
                    <span className="shot-index">{String(shot.shot_number).padStart(2, "0")}</span>
                    <span className="shot-list-copy"><strong>{shot.shot_type || "镜头"}</strong><small>{shot.dialogue || "无对白"}</small></span>
                    <span className={`status-dot ${statusTone(status)}`} aria-label={statusLabel(status)} />
                  </button>
                );
              })}
            </section>
          ))}
        </aside>

        <main className="director-canvas" aria-label="导演画布">
          {!selectedShot ? (
            <div className="canvas-empty"><strong>选择一个镜头开始</strong><span>场景和镜头是专业工作台的第一等对象。</span></div>
          ) : (
            <>
              <div className="canvas-stage">
                <div className="canvas-stage-topline"><span>SCENE / {selectedShot.scene_id || "—"}</span><span className={`status-chip ${statusTone(selectedStatus)}`}>{statusLabel(selectedStatus)}</span></div>
                {activeTab === "assets" ? (
                  <div className="asset-card-workspace" data-testid="asset-card-workspace">
                    <div className="asset-card-list">
                      {assets.map((asset) => <article key={asset.id} className={asset.status === "archived" ? "archived" : ""}><span>{asset.kind}</span><strong>{asset.name}</strong><small>v{asset.version} · {asset.status}</small><p>{asset.description || "暂无描述"}</p><small>{Array.isArray(asset.metadata.tags) ? asset.metadata.tags.join(" · ") : "未分类"}</small><div className="suggestion-actions"><button type="button" className="df-btn ghost" onClick={() => referenceAsset(asset)}>@引用</button><button type="button" className="df-btn ghost" disabled={!onUpdateAsset} onClick={() => void onUpdateAsset?.(asset, { status: asset.status === "archived" ? "active" : "archived" })}>{asset.status === "archived" ? "恢复" : "回收站"}</button></div></article>)}
                      {assets.length === 0 && <p className="muted">暂无项目资产。创建角色、场景、道具或服装资产卡。</p>}
                    </div>
                    <div className="asset-create-form">
                      <select aria-label="资产类型" value={assetKind} onChange={(event) => setAssetKind(event.target.value)}><option value="character">角色</option><option value="scene">场景</option><option value="prop">道具</option><option value="costume">服装</option><option value="action">动作</option><option value="expression">表情</option><option value="voice">声音</option><option value="audio">音频</option><option value="text">文本</option><option value="prompt">提示词</option></select>
                      <input aria-label="资产名称" value={assetName} onChange={(event) => setAssetName(event.target.value)} placeholder="资产名称" />
                      <input aria-label="资产标签" value={assetTags} onChange={(event) => setAssetTags(event.target.value)} placeholder="标签，以逗号分隔" /><textarea aria-label="资产描述" value={assetDescription} onChange={(event) => setAssetDescription(event.target.value)} placeholder="稳定特征、用途与限制" rows={3} />
                      <button type="button" className="df-btn primary" disabled={!assetName.trim() || !onCreateAsset} onClick={() => void onCreateAsset?.({ kind: assetKind, name: assetName.trim(), description: assetDescription.trim(), tags: assetTags.split(",").map((item) => item.trim()).filter(Boolean) }).then(() => { setAssetName(""); setAssetDescription(""); setAssetTags(""); })}>创建资产卡</button>
                    </div>
                  </div>
                ) : <div className="canvas-preview-placeholder"><div className="preview-grid-mark">{activeTab === "canvas" ? "镜头大幕布" : "审片批注预览"}</div><span>{selectedShot.shot_type || "镜头"} · {selectedShot.shot_number}</span></div>}
                                {activeTab === "director" && <div className="director-board-workspace" data-testid="director-board-workspace">
                  <div className="assistant-mode-switch"><button type="button" className={boardMode === "2d" ? "active" : ""} onClick={() => setBoardMode("2d")}>2D</button><button type="button" className={boardMode === "rough_3d" ? "active" : ""} onClick={() => setBoardMode("rough_3d")}>粗 3D</button></div>
                  <div className="director-board-stage"><span>CAMERA</span><div className="director-board-character">人物 Blocking / 骨架</div><small>{boardMode === "2d" ? "俯视舞台" : "透视预演"}</small></div>
                  <div className="form-grid"><label>摄影机<input value={boardCamera} onChange={(event) => setBoardCamera(event.target.value)} /></label><label>人物位置<input value={boardBlocking} onChange={(event) => setBoardBlocking(event.target.value)} /></label><label>动作 / 骨架<input value={boardPose} onChange={(event) => setBoardPose(event.target.value)} /></label><label>表情<input value={boardExpression} onChange={(event) => setBoardExpression(event.target.value)} /></label><label>视线<input value={boardGaze} onChange={(event) => setBoardGaze(event.target.value)} /></label><label>基础场景<input value={boardScene} onChange={(event) => setBoardScene(event.target.value)} /></label></div>
                  <button type="button" className="df-btn primary" disabled={!onSaveDirectorBoard} onClick={() => void onSaveDirectorBoard?.({ mode: boardMode, camera: { summary: boardCamera }, characters: [{ blocking: boardBlocking, pose: boardPose, expression: boardExpression, gaze: boardGaze }], scene: { description: boardScene } })}>保存导演台版本</button>
                </div>}{activeTab === "review" && <div className="review-annotation-workspace" data-testid="review-annotation-workspace">
                  <div className="asset-card-list">{annotations.map((item) => <article key={item.id}><span>{item.severity} · {item.target_kind}</span><strong>{item.target_kind === "image_point" || item.target_kind === "image_region" ? `(${item.x ?? "—"}, ${item.y ?? "—"})` : item.time_start ?? "全镜头"}{item.time_end ? `–${item.time_end}s` : ""}</strong><p>{item.note}</p><small>{item.status}{item.width ? ` · 区域 ${item.width}×${item.height}` : ""}</small></article>)}{annotations.length === 0 && <p className="muted">暂无审片批注。</p>}</div>
                  <div className="asset-create-form">
                    <label>批注类型<select aria-label="批注类型" value={annotationKind} onChange={(event) => setAnnotationKind(event.target.value as typeof annotationKind)}><option value="video_time">视频时间点 / 时间段</option><option value="image_point">图片点</option><option value="image_region">图片区域</option><option value="shot">整镜头</option></select></label>
                    {(annotationKind === "image_point" || annotationKind === "image_region") && <label>图片候选<select aria-label="批注图片 Artifact" value={annotationArtifactId} onChange={(event) => setAnnotationArtifactId(event.target.value)}><option value="">选择图片 Artifact</option>{imageArtifacts.map((artifact) => <option key={artifact.id} value={artifact.id}>{artifact.id.slice(0, 8)} · {artifact.mime_type}</option>)}</select></label>}
                    {annotationKind === "video_time" && <div className="form-grid"><input aria-label="批注开始秒" value={annotationStart} onChange={(event) => setAnnotationStart(event.target.value)} placeholder="开始秒" /><input aria-label="批注结束秒" value={annotationEnd} onChange={(event) => setAnnotationEnd(event.target.value)} placeholder="结束秒（可空）" /></div>}
                    {(annotationKind === "image_point" || annotationKind === "image_region") && <div className="form-grid"><input aria-label="图片归一化 X" value={annotationX} onChange={(event) => setAnnotationX(event.target.value)} placeholder="X 0–1" /><input aria-label="图片归一化 Y" value={annotationY} onChange={(event) => setAnnotationY(event.target.value)} placeholder="Y 0–1" />{annotationKind === "image_region" && <><input aria-label="图片区域宽度" value={annotationWidth} onChange={(event) => setAnnotationWidth(event.target.value)} placeholder="宽度 0–1" /><input aria-label="图片区域高度" value={annotationHeight} onChange={(event) => setAnnotationHeight(event.target.value)} placeholder="高度 0–1" /></>}</div>}
                    <textarea aria-label="审片批注" rows={3} value={annotationNote} onChange={(event) => setAnnotationNote(event.target.value)} placeholder="指出问题和修复意图" /><button type="button" className="df-btn primary" disabled={!annotationNote.trim() || !onCreateAnnotation} onClick={() => void onCreateAnnotation?.({ artifact_id: annotationArtifactId || null, target_kind: annotationKind, time_start: annotationKind === "video_time" ? annotationStart || null : null, time_end: annotationKind === "video_time" ? annotationEnd || null : null, x: annotationKind === "image_point" || annotationKind === "image_region" ? annotationX || null : null, y: annotationKind === "image_point" || annotationKind === "image_region" ? annotationY || null : null, width: annotationKind === "image_region" ? annotationWidth || null : null, height: annotationKind === "image_region" ? annotationHeight || null : null, note: annotationNote.trim() }).then(() => { setAnnotationNote(""); setAnnotationStart(""); setAnnotationEnd(""); setAnnotationX(""); setAnnotationY(""); setAnnotationWidth(""); setAnnotationHeight(""); })}>添加批注</button>
                  </div>
                </div>}                <div className="canvas-stage-meta"><div><small>对白</small><strong>{selectedShot.dialogue || "无对白"}</strong></div><div><small>版本</small><strong>v{selectedShot.version}</strong></div><div><small>事实源</small><strong>Canvas Revision · {revisions.length}</strong></div></div>
              </div>
              <div className="canvas-editor panel">
                <div className="panel-header"><div><span className="director-stage-kicker">导演语义</span><h3>正式画布内容</h3></div><span className={isDirty ? "canvas-dirty" : "canvas-saved"}>{isDirty ? "有未保存变更" : "已保存"}</span></div>
                <textarea aria-label="镜头导演语义" value={selectedText} onChange={(event) => { setDrafts((current) => ({ ...current, [selectedId]: event.target.value })); setSaveMessage(null); }} rows={5} />
                <div className="canvas-editor-footer"><span className="muted">手动修改不会被助手覆盖，也不会自动重跑旧结果。</span><div><button type="button" className="df-btn ghost" onClick={() => onStart?.(selectedId)} disabled={!onStart}>启动镜头</button><button type="button" className="df-btn ghost" onClick={() => onRerun?.(selectedId)} disabled={!onRerun}>局部重跑视频</button><button type="button" className="df-btn primary" onClick={() => void saveCanvas()} disabled={!isDirty || !onSave}>保存画布版本</button></div></div>
                {saveMessage && <div className="canvas-save-message" role="status">{saveMessage}</div>}
              </div>
            </>
          )}
        </main>

        <aside className="director-assistant" aria-label="导演助手">
          <div className="assistant-header"><div><span className="director-stage-kicker">Director Assistant</span><h3>导演助手</h3></div><div className="assistant-mode-switch"><button type="button" className={assistantMode === "auto" ? "active" : ""} onClick={() => setAssistantMode("auto")}>自动</button><button type="button" className={assistantMode === "manual" ? "active" : ""} onClick={() => setAssistantMode("manual")}>手动</button></div></div>
          <div className="assistant-rule">{assistantMode === "manual" ? "手动模式：只在你点击后提出下一项建议。" : "自动模式：建议仍需逐项确认，不能直接改正式画布。"}</div>
          <div className="assistant-fact-card"><strong>当前镜头</strong><span>{selectedShot ? `S${selectedShot.shot_number} · ${selectedShot.shot_type || "镜头"}` : "未选择"}</span><small>已锁定版本不会被助手暗改 · 历史修订 {revisions.length} 条</small></div>
          <div className="assistant-suggestions"><div className="assistant-section-title"><span>建议与变更预览</span><small>{suggestions.filter((item) => !rejected[item.id]).length} 项</small></div>
            {!selectedShot && <p className="muted">选择镜头后，助手会根据当前画布提出建议。</p>}
            {suggestions.map((suggestion) => rejected[suggestion.id] ? null : (
              <article key={suggestion.id} className={`suggestion-card ${accepted[suggestion.id] ? "accepted" : ""}`}>
                <div className="suggestion-card-title"><strong>{suggestion.title}</strong>{accepted[suggestion.id] && <span>{proposalIds[suggestion.id] ? "提案已创建" : "已采纳"}</span>}</div>
                <p>{suggestion.body}</p><small>变更：{suggestion.change}</small><small>影响：{suggestion.impact}</small>{proposalImpacts[suggestion.id] && <small>失效节点：{proposalImpacts[suggestion.id].invalidated_node_keys.join("、") || "—"} · 可复用：{proposalImpacts[suggestion.id].reusable_artifact_ids.length}</small>}
                {!accepted[suggestion.id] && <div className="suggestion-actions"><button type="button" className="df-btn primary" onClick={() => applySuggestion(suggestion)}>采纳</button><button type="button" className="df-btn ghost" onClick={() => rejectSuggestion(suggestion)}>拒绝</button></div>}
              </article>
            ))}
          </div>
          <div className="assistant-footer"><span className="status-dot done" />助手不能直接写入正式画布</div>
        </aside>
      </div>

      <section className="panel experiment-branch-panel" data-testid="experiment-branches"><div className="panel-header"><div><span className="director-stage-kicker">Formal / Experiment</span><h3>正式线与实验线</h3></div><strong>{experiments.length} 个实验</strong></div><div className="director-professional-columns"><section><h4>实验分支</h4><ul className="dense">{experiments.map((item) => { const candidates = candidateArtifactIds(item); const targetNodeKey = String(item.parameters.target_node_key ?? "video") as "keyframe" | "video"; const firstCandidate = candidates[0] ?? null; const runStates = Array.isArray(item.comparison?.run_states) ? item.comparison.run_states : []; return <li key={item.id} className="experiment-row"><div><strong>{item.name}</strong><small>{item.selected_model ?? "未选模型"} · {item.status} · 候选 {candidates.length}</small>{runStates.length > 0 && <small>执行证据：{runStates.length} 个 Run</small>}</div><div className="suggestion-actions"><button type="button" className="df-btn ghost" disabled={!onStartExperiment || item.status === "accepted" || item.status === "rejected"} onClick={() => void onStartExperiment?.(item.id, targetNodeKey)}>运行实验</button><button type="button" className="df-btn primary" disabled={!onDecideExperiment || !firstCandidate || item.status === "accepted" || item.status === "rejected"} onClick={() => void onDecideExperiment?.(item.id, { decision: "accepted", adoption_scope: targetNodeKey === "keyframe" ? "keyframe_rerun_downstream" : "current_node", candidate_artifact_id: firstCandidate })}>采纳候选</button><button type="button" className="df-btn ghost" disabled={!onDecideExperiment || item.status === "accepted" || item.status === "rejected"} onClick={() => void onDecideExperiment?.(item.id, { decision: "kept" })}>保留实验</button><button type="button" className="df-btn ghost" disabled={!onDecideExperiment || item.status === "accepted" || item.status === "rejected"} onClick={() => void onDecideExperiment?.(item.id, { decision: "rejected" })}>拒绝</button></div></li> })}{experiments.length === 0 && <li className="muted">正式结果不会被实验覆盖</li>}</ul></section><section><h4>创建模型实验</h4><div className="asset-create-form"><input aria-label="实验名称" value={experimentName} onChange={(event) => setExperimentName(event.target.value)} placeholder="例如：换模型验证转头稳定性" /><select aria-label="实验模型" value={experimentModel} onChange={(event) => setExperimentModel(event.target.value)}><option value="">选择模型</option>{models.map((model) => <option key={model.id} value={model.id}>{model.display_name}</option>)}</select>{experimentModelRecord && <small>动态能力：{experimentModelRecord.capabilities.join(" · ")}</small>}<button type="button" className="df-btn primary" disabled={!experimentName.trim() || !experimentModel.trim() || !onCreateExperiment} onClick={() => void onCreateExperiment?.({ name: experimentName.trim(), selected_model: experimentModel.trim() }).then(() => { setExperimentName(""); setExperimentModel(""); })}>创建实验分支</button></div></section><section><h4>OpenCut</h4><p className="muted">正式线镜头 {openCutManifest?.shots?.length ?? 0} 个 · {openCutManifest?.tracks?.length ?? 0} 条轨道 · {openCutManifest?.schema_version ?? "等待清单"}</p><small className="muted">视频、音频、字幕轨道均携带 Artifact 与 Provider 血缘，可由剪辑适配层导入。</small></section></div></section>
      <div className="workbench-timeline" aria-label="镜头生产链"><div className="timeline-title"><span>当前镜头生产链</span><small>每一步保留请求与 Artifact 血缘</small></div><div className="timeline-steps">{PIPELINE.map(([id, label], index) => <div key={id} className={`timeline-step ${index === 0 ? "current" : ""}`}><span className="timeline-step-index">{index + 1}</span><strong>{label}</strong><small>{index === 0 ? "可复用" : "按需执行"}</small></div>)}</div></div>
    </section>
  );
}





















