import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Field, Input, Radio, Textarea } from "../../components/ui";
import { artifactContentUrl, artifactVideoFrameUrl, createReviewAnnotation } from "../../lib/api";
import { reviewTargetHref } from "../review/reviewTarget";
import type { ShotLite } from "./api";
import type { ShotCandidate } from "./shotCandidates";
import "./shot-continuity.css";

export type ShotContinuityBinding = {
  id?: string;
  purpose?: string;
  label?: string;
  asset_id?: string | null;
  asset_version_id?: string | null;
  artifact_id?: string | null;
  resolution_mode?: string;
  stage?: string;
};

export type ContinuityCheckItemKey =
  "styling" | "costume_prop" | "spatial_axis" | "action_match" | "dialogue_emotion";

export type ChecklistValue = "unchecked" | "consistent" | "issue_found";

export const CONTINUITY_CHECKLIST_ITEMS: readonly {
  key: ContinuityCheckItemKey;
  label: string;
  desc: string;
}[] = [
  { key: "styling", label: "角色造型", desc: "发型、容貌、体型特征是否跨镜头保持一致" },
  { key: "costume_prop", label: "服装道具", desc: "衣服配色、配饰、手持道具是否连贯" },
  { key: "spatial_axis", label: "空间视线与轴线", desc: "视线方向、主体位置与摄影机轴线是否越轴" },
  { key: "action_match", label: "动作衔接", desc: "前后镜头运动速度、姿态起点与终点是否匹配" },
  { key: "dialogue_emotion", label: "对白情绪", desc: "情绪强度、表演张力与台词语境是否连续" },
];

const INITIAL_CHECKLIST: Record<ContinuityCheckItemKey, ChecklistValue> = {
  styling: "unchecked",
  costume_prop: "unchecked",
  spatial_axis: "unchecked",
  action_match: "unchecked",
  dialogue_emotion: "unchecked",
};

/** Evidence comparison & continuity problem closed-loop over adjacent shots, bindings, and narrative. */
export function ShotContinuityCompare({
  projectId,
  shots,
  shotId,
  candidate,
  bindings = [],
}: {
  projectId: string;
  shots: ShotLite[];
  shotId: string | null;
  candidate?: ShotCandidate | null;
  bindings?: ShotContinuityBinding[];
}) {
  const [open, setOpen] = useState(false);
  const [checklist, setChecklist] =
    useState<Record<ContinuityCheckItemKey, ChecklistValue>>(INITIAL_CHECKLIST);
  const [showIssueForm, setShowIssueForm] = useState(false);
  const [severity, setSeverity] = useState<"blocker" | "warning" | "note">("blocker");
  const [videoTimecode, setVideoTimecode] = useState("0.0");
  const [issueNote, setIssueNote] = useState("");
  const [submittingAnnotation, setSubmittingAnnotation] = useState(false);
  const [annotationError, setAnnotationError] = useState<string | null>(null);
  const [annotationSuccess, setAnnotationSuccess] = useState(false);

  const ordered = useMemo(
    () => [...shots].sort((a, b) => a.sort_order - b.sort_order || a.shot_number - b.shot_number),
    [shots],
  );

  const index = ordered.findIndex((shot) => shot.id === shotId);
  const currentShot = index >= 0 ? ordered[index] : null;
  const prevShot = index > 0 ? ordered[index - 1] : null;
  const nextShot = index >= 0 && index < ordered.length - 1 ? ordered[index + 1] : null;

  // Determine current active media artifact & lineage
  const currentVideoId =
    candidate?.stage === "video"
      ? candidate.artifactId
      : candidate
        ? null
        : currentShot?.formal_video_artifact_id;
  const currentImageId =
    candidate?.stage === "image_keyframe"
      ? candidate.artifactId
      : candidate
        ? null
        : currentShot?.formal_keyframe_artifact_id;
  const activeArtifactId = candidate?.artifactId ?? (currentVideoId || currentImageId || null);
  const activeIsVideo = Boolean(
    candidate?.stage === "video" || (!candidate && currentShot?.formal_video_artifact_id),
  );

  // Reset checklist when candidate, shot, or binding identities change
  const evidenceIdentityKey = `${shotId}:${candidate?.artifactId ?? "formal"}:${candidate?.nodeRunId ?? ""}:${bindings.map((b) => `${b.asset_version_id}:${b.artifact_id}`).join(",")}`;
  useEffect(() => {
    setChecklist({ ...INITIAL_CHECKLIST });
    setShowIssueForm(false);
    setAnnotationSuccess(false);
    setAnnotationError(null);
    setIssueNote("");
  }, [evidenceIdentityKey]);

  if (index < 0 || !currentShot) return null;

  const hasIssueFound = Object.values(checklist).some((val) => val === "issue_found");
  const issuesFoundList = CONTINUITY_CHECKLIST_ITEMS.filter(
    (item) => checklist[item.key] === "issue_found",
  );

  const handleChecklistChange = (key: ContinuityCheckItemKey, val: ChecklistValue) => {
    setChecklist((prev) => ({ ...prev, [key]: val }));
  };

  const handleRecordAnnotation = async () => {
    if (!activeArtifactId || !shotId) return;
    setSubmittingAnnotation(true);
    setAnnotationError(null);

    const issuesSummary = issuesFoundList.map((i) => i.label).join("、");
    const fullNote = issueNote.trim()
      ? `[连续性问题: ${issuesSummary}] ${issueNote.trim()}`
      : `[连续性问题: ${issuesSummary}]`;

    if (activeIsVideo) {
      const tc = parseFloat(videoTimecode);
      if (isNaN(tc) || tc < 0) {
        setAnnotationError("请输入有效的时间码（大于或等于 0 的数字秒数）");
        setSubmittingAnnotation(false);
        return;
      }
    }

    try {
      await createReviewAnnotation(projectId, shotId, {
        artifact_id: activeArtifactId,
        target_kind: activeIsVideo ? "video_time" : "shot",
        time_start: activeIsVideo ? videoTimecode : undefined,
        note: fullNote,
        severity,
      });
      setAnnotationSuccess(true);
    } catch (err: unknown) {
      setAnnotationError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmittingAnnotation(false);
    }
  };

  const reviewBoardHref =
    activeArtifactId && shotId
      ? reviewTargetHref(projectId, {
          shotId,
          artifactId: activeArtifactId,
          stage: activeIsVideo ? "formal_video" : "formal_keyframe",
          reviewKind: activeIsVideo ? "video_drift" : "identity",
        })
      : null;

  return (
    <section className="shot-continuity" aria-label="相邻镜头连续性对照">
      <Button tone="ghost" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        相邻镜头对照
      </Button>

      {open && (
        <div className="shot-continuity-container" data-testid="shot-continuity-container">
          {/* 1. Four-Zone Media Comparison Grid */}
          <div className="shot-continuity-grid" data-testid="shot-continuity-grid">
            {/* Zone 1: Previous shot end frame */}
            <ComparisonMedia
              key={`prev:${prevShot?.id ?? "none"}`}
              projectId={projectId}
              title="前镜末帧"
              shot={prevShot ?? undefined}
              videoId={prevShot?.formal_video_artifact_id}
              imageId={prevShot?.formal_keyframe_artifact_id}
              end={true}
              source="正式素材"
            />

            {/* Zone 2: Current shot bound reference assets */}
            <figure
              className="shot-continuity-item shot-continuity-references"
              aria-label="当前镜头绑定参考"
            >
              <figcaption>当前镜头绑定参考</figcaption>
              {bindings.length > 0 ? (
                <div className="shot-continuity-ref-list" data-testid="continuity-bindings-list">
                  {bindings.map((b, idx) => (
                    <div
                      key={b.id || idx}
                      className="shot-continuity-ref-item"
                      data-testid="continuity-binding-item"
                    >
                      {b.artifact_id ? (
                        <img
                          src={artifactContentUrl(projectId, b.artifact_id)}
                          alt={b.label || b.purpose || "参考视觉"}
                          className="shot-continuity-ref-thumb"
                        />
                      ) : (
                        <div className="shot-continuity-ref-placeholder">尚无画面</div>
                      )}
                      <div className="shot-continuity-ref-info">
                        <strong>{b.label || b.purpose || "未命名参考"}</strong>
                        <small>版本: {b.asset_version_id || "默认"}</small>
                        <small>
                          产物: {b.artifact_id ? `${b.artifact_id.slice(0, 8)}...` : "未绑定"}
                        </small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p role="status">当前镜头未绑定角色或场景参考</p>
              )}
            </figure>

            {/* Zone 3: Current shot candidate / formal start frame */}
            <ComparisonMedia
              key={`current:${currentShot.id}:${activeArtifactId}:${candidate ? "candidate" : "formal"}`}
              projectId={projectId}
              title="当前镜头首帧"
              shot={currentShot}
              videoId={currentVideoId}
              imageId={currentImageId}
              end={false}
              source={candidate ? "所选候选（非正式）" : "正式素材"}
              extraMeta={
                candidate
                  ? `Artifact: ${candidate.artifactId.slice(0, 8)}...${candidate.nodeRunId ? ` · NodeRun: ${candidate.nodeRunId.slice(0, 8)}...` : ""}`
                  : undefined
              }
            />

            {/* Zone 4: Next shot start frame */}
            <ComparisonMedia
              key={`next:${nextShot?.id ?? "none"}`}
              projectId={projectId}
              title="后镜首帧"
              shot={nextShot ?? undefined}
              videoId={nextShot?.formal_video_artifact_id}
              imageId={nextShot?.formal_keyframe_artifact_id}
              end={false}
              source="正式素材"
            />
          </div>

          <p className="shot-continuity-note">
            只对照已有证据，不自动判断连续性或生成缺失画面。视频读取首/末帧采样；静帧不代表视频首/末帧证据。
          </p>

          {/* 2. Three-Shot Narrative Comparison */}
          <div className="shot-continuity-narrative" data-testid="shot-continuity-narrative">
            <h4>三镜头叙事与机位对照</h4>
            <div className="shot-continuity-narrative-grid">
              <NarrativeColumn title="前一镜头" shot={prevShot} />
              <NarrativeColumn title="当前镜头" shot={currentShot} isCurrent={true} />
              <NarrativeColumn title="后一镜头" shot={nextShot} />
            </div>
          </div>

          {/* 3. Five-Item 3-State Checklist */}
          <div className="shot-continuity-checklist" data-testid="shot-continuity-checklist">
            <div className="shot-continuity-checklist-header">
              <h4>连续性人工检查清单</h4>
              <p className="shot-continuity-checklist-desc">
                无可信自动评价器，必须由人工目视核对；切换候选或证据变化后自动重置为未检查；本检查不构成自动批准或正式采纳。
              </p>
            </div>

            <div
              className="shot-continuity-checklist-table"
              role="table"
              aria-label="连续性核对清单"
            >
              {CONTINUITY_CHECKLIST_ITEMS.map((item) => (
                <div
                  key={item.key}
                  className="shot-continuity-check-row"
                  role="row"
                  data-testid={`checklist-row-${item.key}`}
                >
                  <div className="shot-continuity-check-label" role="cell">
                    <strong>{item.label}</strong>
                    <small>{item.desc}</small>
                  </div>
                  <div className="shot-continuity-check-actions" role="cell">
                    {(
                      [
                        { val: "unchecked", label: "未检查" },
                        { val: "consistent", label: "一致" },
                        { val: "issue_found", label: "发现问题" },
                      ] as const
                    ).map(({ val, label }) => (
                      <Radio
                        key={val}
                        name={`checklist-${item.key}`}
                        value={val}
                        checked={checklist[item.key] === val}
                        onChange={() => handleChecklistChange(item.key, val)}
                        className={`shot-continuity-radio-item ${checklist[item.key] === val ? "selected" : ""}`}
                      >
                        {label}
                      </Radio>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="shot-continuity-checklist-footer">
              <Button
                tone={hasIssueFound ? "primary" : "ghost"}
                disabled={!hasIssueFound}
                onClick={() => setShowIssueForm((prev) => !prev)}
                data-testid="open-record-issue-button"
              >
                {showIssueForm ? "收起问题规划" : "记录连续性问题并规划修复"}
              </Button>
              {!hasIssueFound && (
                <span className="muted">至少标记一项“发现问题”后可记录并规划修复</span>
              )}
            </div>
          </div>

          {/* 4. Issue Recording & Repair Scope Planning */}
          {showIssueForm && (
            <div className="shot-continuity-issue-form" data-testid="continuity-issue-form">
              <h4>记录连续性问题与修复规划</h4>

              {!activeArtifactId ? (
                <Alert
                  type="warning"
                  showIcon
                  message="缺少可定位产物"
                  description="当前镜头或候选缺少可定位产物，仅能编辑镜头设计意图，不能生成伪证据批注。"
                  data-testid="no-target-artifact-warning"
                />
              ) : (
                <>
                  <div className="shot-continuity-evidence-binding">
                    <small>
                      关联产物：<code>{activeArtifactId}</code>
                      {candidate?.nodeRunId ? ` · NodeRun: ${candidate.nodeRunId}` : ""}
                    </small>
                  </div>

                  <Field>
                    <span>严重级别</span>
                    <div className="shot-continuity-severity-radios">
                      {(
                        [
                          { val: "blocker", label: "阻断 (Blocker)" },
                          { val: "warning", label: "警告 (Warning)" },
                          { val: "note", label: "提示 (Note)" },
                        ] as const
                      ).map(({ val, label }) => (
                        <Radio
                          key={val}
                          name="issue-severity"
                          value={val}
                          checked={severity === val}
                          onChange={() => setSeverity(val)}
                        >
                          {label}
                        </Radio>
                      ))}
                    </div>
                  </Field>

                  <Field>
                    <span>时间点与帧定位</span>
                    {activeIsVideo ? (
                      <Input
                        type="number"
                        min="0"
                        step="0.1"
                        className="shot-continuity-timecode-input"
                        value={videoTimecode}
                        onChange={(e) => setVideoTimecode(e.target.value)}
                        placeholder="输入秒数，例如 1.5"
                        data-testid="continuity-timecode-input"
                      />
                    ) : (
                      <span className="shot-continuity-static-frame">
                        首帧 / 静帧（不编造视频时间码）
                      </span>
                    )}
                  </Field>

                  <Field>
                    <span>涉及问题项</span>
                    <span className="shot-continuity-involved-items">
                      {issuesFoundList.map((i) => i.label).join("、")}
                    </span>
                  </Field>

                  <Field>
                    <span>问题描述与修改建议</span>
                    <Textarea
                      rows={3}
                      value={issueNote}
                      onChange={(e) => setIssueNote(e.target.value)}
                      placeholder="例如：第二镜角色服装由蓝色变成了红色，与参考资产及前镜末帧不符..."
                      data-testid="continuity-issue-note-input"
                    />
                  </Field>

                  <div className="shot-continuity-form-actions">
                    <Button
                      tone="primary"
                      onClick={handleRecordAnnotation}
                      disabled={submittingAnnotation}
                      data-testid="submit-continuity-annotation"
                    >
                      {submittingAnnotation ? "正在保存批注..." : "保存批注"}
                    </Button>
                  </div>

                  {annotationError && (
                    <Alert
                      type="error"
                      showIcon
                      title="批注保存失败"
                      description={annotationError}
                      data-testid="continuity-annotation-error"
                    />
                  )}

                  {annotationSuccess && (
                    <div
                      className="shot-continuity-annotation-success"
                      data-testid="continuity-annotation-success"
                    >
                      <Alert
                        type="success"
                        showIcon
                        title="批注保存成功"
                        description="连续性问题已关联到当前产物，未自动触发付费生成或修改正式素材。"
                      />

                      {reviewBoardHref && (
                        <div className="shot-continuity-review-link">
                          <a
                            href={reviewBoardHref}
                            className="button-like"
                            data-testid="goto-review-board-link"
                          >
                            进入审核与修复看板
                          </a>
                        </div>
                      )}

                      <div className="shot-continuity-repair-scope-card">
                        <h5>修复规划与范围说明</h5>
                        <ul>
                          <li>
                            <strong>修复范围由模型能力决定：</strong>
                            若目标模型不支持局部重绘或区域编辑，系统将以整镜头重新生成方式替代，不会隐式修改相邻镜头。
                          </li>
                          <li>
                            <strong>显式确认原则：</strong>
                            修复生成必须在审核与修复看板中由用户显式确认提交，不自动产生扣费操作。
                          </li>
                          <li>
                            <strong>候选审阅：</strong>
                            新修复生成的结果将作为新候选产物呈现，需再次经过人工审阅后方可设为正式素材。
                          </li>
                        </ul>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function NarrativeColumn({
  title,
  shot,
  isCurrent = false,
}: {
  title: string;
  shot: ShotLite | null;
  isCurrent?: boolean;
}) {
  return (
    <div
      className={`shot-continuity-narrative-col ${isCurrent ? "current" : ""}`}
      data-testid={`narrative-col-${shot ? shot.id : "empty"}`}
    >
      <h5>
        {title} {shot ? `(镜头 ${shot.shot_number})` : ""}
      </h5>
      {shot ? (
        <dl>
          <div>
            <dt>景别</dt>
            <dd>{shot.shot_type || "未填写"}</dd>
          </div>
          <div>
            <dt>机位/运镜</dt>
            <dd>{shot.camera_move || "未填写"}</dd>
          </div>
          <div>
            <dt>计划时长</dt>
            <dd>{shot.duration_seconds ? `${shot.duration_seconds}s` : "未填写"}</dd>
          </div>
          <div>
            <dt>动作描述</dt>
            <dd>{shot.visual_description || "未填写"}</dd>
          </div>
          <div>
            <dt>台词</dt>
            <dd>{shot.dialogue || "未填写"}</dd>
          </div>
        </dl>
      ) : (
        <p className="muted">没有相邻镜头</p>
      )}
    </div>
  );
}

function ComparisonMedia({
  projectId,
  title,
  shot,
  videoId,
  imageId,
  end,
  source,
  extraMeta,
}: {
  projectId: string;
  title: string;
  shot?: ShotLite;
  videoId?: string | null;
  imageId?: string | null;
  end: boolean;
  source: string;
  extraMeta?: string;
}) {
  const [error, setError] = useState(false);
  return (
    <figure className="shot-continuity-item" aria-label={title}>
      <figcaption>
        {title}
        {shot ? ` · 镜头 ${shot.shot_number}` : ""} · {source}
        {extraMeta ? <small className="shot-continuity-extra-meta">{extraMeta}</small> : null}
      </figcaption>
      {videoId ? (
        <>
          <img
            src={artifactVideoFrameUrl(projectId, videoId, end ? "end" : "start")}
            alt={`${title}视频采样帧`}
            onError={() => setError(true)}
          />
          <small>来自此视频的{end ? "末帧" : "首帧"}采样</small>
        </>
      ) : imageId ? (
        <>
          <img
            src={artifactContentUrl(projectId, imageId)}
            alt={`${title} · ${source === "正式素材" ? "正式静帧" : "所选候选静帧"}`}
            onError={() => setError(true)}
          />
          <small>仅有静帧，尚无视频首/末帧证据</small>
        </>
      ) : (
        <p role="status">{shot ? "此镜头缺少可对照素材" : "没有相邻镜头"}</p>
      )}
      {error && <p role="alert">已有素材读取失败，请检查该镜头；不会当作缺失素材自动补生成。</p>}
    </figure>
  );
}
