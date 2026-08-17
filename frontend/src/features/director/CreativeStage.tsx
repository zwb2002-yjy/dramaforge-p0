import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  approveDirectorStage,
  commandKey,
  generateConcepts,
  generateCreativePackage,
  interpretPreferences,
} from "./api";
import type {
  AdaptationMode,
  ConceptGenerateInput,
  ConceptSetPayload,
  CreationGoal,
  CreativeEntryMode,
  DirectorWorkspaceSnapshot,
  EpisodeScriptPayload,
  PreferenceUnderstandingPayload,
  StoryConcept,
  StoryCorePayload,
  StoryReviewPayload,
} from "./types";
import { artifactPayload } from "./types";

type CreativeStageProps = {
  projectId: string;
  snapshot: DirectorWorkspaceSnapshot;
  refresh: () => Promise<unknown>;
  onMessage: (message: string) => void;
  onError: (message: string) => void;
};

const ENTRY_MODES: Array<{ id: CreativeEntryMode; title: string; description: string }> = [
  { id: "no_idea", title: "我还没有想法", description: "AI 导演先帮你找到三个原创方向" },
  { id: "one_sentence", title: "我有一句话创意", description: "保留你的表达，再补足冲突与结局" },
  { id: "import_script", title: "我有自己的剧本", description: "导入你有权使用的文字并改编" },
];

const CREATION_GOALS: Array<{ id: CreationGoal; title: string; description: string }> = [
  { id: "self_expression", title: "表达我自己", description: "从情绪、经历或想表达的主题出发" },
  { id: "high_traffic", title: "平台热点和高流量题材", description: "只参考合规的抽象趋势，不复刻具体作品" },
  { id: "balanced", title: "两者平衡", description: "兼顾作品归属感与传播潜力" },
];

function textFrom(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function shouldInitializeConceptChoices(
  selectedConceptId: string | null,
  lockedConceptId: string | null,
): boolean {
  return Boolean(selectedConceptId && selectedConceptId !== lockedConceptId);
}

function conceptInputReady(input: {
  entryMode: CreativeEntryMode;
  creationGoal: CreationGoal;
  idea: string;
  scriptText: string;
  sourceRightsConfirmed: boolean;
}): boolean {
  if (input.entryMode === "no_idea") return Boolean(input.creationGoal);
  if (input.entryMode === "one_sentence") return Boolean(input.idea.trim());
  return Boolean(input.scriptText.trim() && input.sourceRightsConfirmed);
}

function ConceptCard({
  concept,
  selected,
  onSelect,
}: {
  concept: StoryConcept;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`director-concept-card ${selected ? "selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
      data-testid={`concept-${concept.concept_id}`}
    >
      <span className="director-concept-title">{concept.title}</span>
      <span>{concept.logline}</span>
      <dl>
        <dt>主题</dt><dd>{concept.theme}</dd>
        <dt>人物关系</dt><dd>{concept.character_relationship}</dd>
        <dt>核心冲突</dt><dd>{concept.core_conflict}</dd>
        <dt>结局方向</dt><dd>{concept.ending_direction}</dd>
      </dl>
      <small>{concept.why_it_fits}</small>
    </button>
  );
}

function PreferenceCard({
  preference,
  busy,
  onConfirm,
}: {
  preference: PreferenceUnderstandingPayload;
  busy: boolean;
  onConfirm: () => void;
}) {
  return (
    <section className="director-preference-card" data-testid="preference-understanding-card">
      <h4>AI 导演对你的理解</h4>
      <p>{preference.interpretation_summary}</p>
      <div className="split-2">
        <div><strong>想保留</strong><ul>{preference.liked.map((item) => <li key={item}>{item}</li>)}</ul></div>
        <div><strong>想避开</strong><ul>{preference.disliked.concat(preference.avoid).map((item) => <li key={item}>{item}</li>)}</ul></div>
      </div>
      {preference.inferred_preferences.length > 0 && (
        <p className="muted">推断偏好：{preference.inferred_preferences.join(" · ")}</p>
      )}
      <button type="button" className="primary" disabled={busy} onClick={onConfirm}>
        {busy ? "正在生成下一版…" : "理解正确，按这张卡生成下一版"}
      </button>
      <p className="muted">点击前不会修改概念；若理解不对，请修改反馈后重新生成理解卡。</p>
    </section>
  );
}

function CreativePackageReview({
  storyCore,
  script,
  review,
}: {
  storyCore: StoryCorePayload;
  script: EpisodeScriptPayload;
  review: StoryReviewPayload;
}) {
  const issueCount = review.logic_issues.length + review.pacing_issues.length
    + review.duration_risks.length + review.closure_issues.length;
  return (
    <section className="director-package" data-testid="creative-package-review">
      <div className="panel-header">
        <div><h3>{script.title}</h3><p className="muted">预计 {script.target_duration_seconds} 秒</p></div>
        <strong className={review.status === "passed" ? "status-ok" : "status-bad"}>
          {review.status === "passed" ? "剧本预审通过" : `发现 ${issueCount} 个问题`}
        </strong>
      </div>
      <dl className="creative-summary">
        <dt>主题</dt><dd>{storyCore.theme}</dd>
        <dt>核心冲突</dt><dd>{storyCore.core_conflict}</dd>
        <dt>情绪走向</dt><dd>{storyCore.emotional_direction}</dd>
        <dt>结局</dt><dd>{storyCore.ending}</dd>
        <dt>起</dt><dd>{script.setup}</dd>
        <dt>转</dt><dd>{script.turn}</dd>
        <dt>落点</dt><dd>{script.ending}</dd>
      </dl>
      <h4>角色动机</h4>
      <div className="director-character-list">
        {storyCore.characters.map((character) => (
          <article key={character.name}>
            <strong>{character.name} · {character.identity}</strong>
            <span>想要：{character.desire}</span>
            <span>害怕或代价：{character.fear_or_cost}</span>
          </article>
        ))}
      </div>
      <h4>完整对白</h4>
      <ol className="director-dialogue-list">
        {script.dialogue.map((line, index) => (
          <li key={`${line.speaker}-${index}`}><strong>{line.speaker}</strong><span>「{line.text}」</span><small>{line.emotion}</small></li>
        ))}
      </ol>
      {review.status === "needs_revision" && (
        <div className="callout warn">
          {review.logic_issues.concat(review.pacing_issues, review.duration_risks, review.closure_issues).map((item) => <p key={item}>{item}</p>)}
          {review.revision_suggestions.map((item) => <p key={item}>建议：{item}</p>)}
        </div>
      )}
    </section>
  );
}

export function CreativeStage({
  projectId,
  snapshot,
  refresh,
  onMessage,
  onError,
}: CreativeStageProps) {
  const [entryMode, setEntryMode] = useState<CreativeEntryMode>("no_idea");
  const [creationGoal, setCreationGoal] = useState<CreationGoal>("self_expression");
  const [idea, setIdea] = useState("");
  const [scriptText, setScriptText] = useState("");
  const [adaptationMode, setAdaptationMode] = useState<AdaptationMode>("balanced");
  const [sourceRightsConfirmed, setSourceRightsConfirmed] = useState(false);
  const [selectedConceptId, setSelectedConceptId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [theme, setTheme] = useState("");
  const [coreConflict, setCoreConflict] = useState("");
  const [emotionalDirection, setEmotionalDirection] = useState("");
  const [ending, setEnding] = useState("");
  const [reconsiderConcept, setReconsiderConcept] = useState(false);

  const conceptArtifact = snapshot.current_artifacts.concept_set;
  const preferenceArtifact = snapshot.current_artifacts.preference_understanding;
  const concepts = artifactPayload<ConceptSetPayload>(snapshot, "concept_set");
  const preference = artifactPayload<PreferenceUnderstandingPayload>(snapshot, "preference_understanding");
  const storyCore = artifactPayload<StoryCorePayload>(snapshot, "story_core");
  const episodeScript = artifactPayload<EpisodeScriptPayload>(snapshot, "episode_script");
  const storyReview = artifactPayload<StoryReviewPayload>(snapshot, "story_review");
  const selectedConcept = useMemo(
    () => concepts?.concepts.find((candidate) => candidate.concept_id === selectedConceptId) ?? null,
    [concepts, selectedConceptId],
  );
  const preferenceIsForCurrentConcept = Boolean(
    conceptArtifact && preferenceArtifact && snapshot.step_runs.some(
      (run) => run.input_version_refs.includes(conceptArtifact.id)
        && run.output_version_refs.includes(preferenceArtifact.id),
    ),
  );

  useEffect(() => {
    if (!concepts) return;
    setEntryMode(concepts.entry_mode);
    if (concepts.creation_goal) setCreationGoal(concepts.creation_goal);
    if (concepts.adaptation_mode) setAdaptationMode(concepts.adaptation_mode);
    setSourceRightsConfirmed(concepts.source_rights_confirmed);
  }, [concepts]);

  useEffect(() => {
    if (!selectedConcept || !shouldInitializeConceptChoices(
      selectedConcept.concept_id,
      storyCore?.selected_concept_id ?? null,
    )) return;
    setTheme(selectedConcept.theme);
    setCoreConflict(selectedConcept.core_conflict);
    setEnding(selectedConcept.ending_direction);
  }, [selectedConcept, storyCore?.selected_concept_id]);

  useEffect(() => {
    if (!storyCore) return;
    setSelectedConceptId(storyCore.selected_concept_id);
    setTheme(storyCore.theme);
    setCoreConflict(storyCore.core_conflict);
    setEmotionalDirection(storyCore.emotional_direction);
    setEnding(storyCore.ending);
  }, [storyCore]);

  const conceptMutation = useMutation({
    mutationFn: (input: ConceptGenerateInput) => generateConcepts(projectId, input),
    onSuccess: async () => {
      setSelectedConceptId(null);
      setReconsiderConcept(false);
      setFeedback("");
      onMessage("已生成三个原创概念。先选择方向，或告诉 AI 导演喜欢和不喜欢什么。");
      await refresh();
    },
    onError: (error) => onError(textFrom(error)),
  });
  const preferenceMutation = useMutation({
    mutationFn: () => {
      if (!conceptArtifact) throw new Error("请先生成概念");
      return interpretPreferences(projectId, {
        source_concept_version_id: conceptArtifact.id,
        feedback: feedback.trim(),
        authorize_text_call: true,
        idempotency_key: commandKey("creative-preference"),
      });
    },
    onSuccess: async () => {
      onMessage("偏好理解卡已生成。确认它理解正确后，才会生成下一版概念。");
      await refresh();
    },
    onError: (error) => onError(textFrom(error)),
  });
  const packageMutation = useMutation({
    mutationFn: () => {
      if (!conceptArtifact || !selectedConceptId) throw new Error("请先选择一个概念");
      return generateCreativePackage(projectId, {
        concept_version_id: conceptArtifact.id,
        selected_concept_id: selectedConceptId,
        theme: theme.trim(),
        core_conflict: coreConflict.trim(),
        emotional_direction: emotionalDirection.trim(),
        ending: ending.trim(),
        authorize_text_call: true,
        idempotency_key: commandKey("creative-package"),
      });
    },
    onSuccess: async () => {
      onMessage("完整短剧方案与预审已生成。请阅读后再确认创作方案。");
      await refresh();
    },
    onError: (error) => onError(textFrom(error)),
  });
  const approvalMutation = useMutation({
    mutationFn: () => approveDirectorStage(
      projectId,
      "creative_plan",
      commandKey("approve-creative"),
    ),
    onSuccess: async () => {
      onMessage("创作方案已锁定。AI 导演将基于这份事实准备拍摄方案。");
      await refresh();
    },
    onError: (error) => onError(textFrom(error)),
  });

  const busy = conceptMutation.isPending || preferenceMutation.isPending
    || packageMutation.isPending || approvalMutation.isPending;
  const ready = conceptInputReady({
    entryMode,
    creationGoal,
    idea,
    scriptText,
    sourceRightsConfirmed,
  });

  function currentConceptInput(preferenceVersionId: string | null = null): ConceptGenerateInput {
    const fallbackIdea = concepts?.concepts.map((concept) => concept.logline).join("；") ?? "";
    return {
      entry_mode: entryMode,
      creation_goal: entryMode === "no_idea" ? creationGoal : null,
      idea: entryMode === "one_sentence" ? idea.trim() || fallbackIdea : "",
      script_text: entryMode === "import_script" ? scriptText.trim() || fallbackIdea : "",
      adaptation_mode: entryMode === "import_script" ? adaptationMode : null,
      source_rights_confirmed: entryMode === "import_script" && sourceRightsConfirmed,
      confirmed_preference_version_id: preferenceVersionId,
      authorize_text_call: true,
      idempotency_key: commandKey(preferenceVersionId ? "concepts-revision" : "concepts"),
    };
  }

  const editable = ["drafting_creative", "awaiting_creative_confirmation"].includes(
    snapshot.workflow.status,
  );
  const canConfirmCreative = snapshot.allowed_actions.includes("confirm_creative_plan");

  return (
    <section data-testid="creative-stage">
      <div className="panel director-stage-intro">
        <div><span className="director-stage-kicker">阶段 1</span><h2>创作方案</h2></div>
        <p>故事为什么发生、角色为什么这样选择、最后落在哪里，由你决定。AI 负责把它整理成能拍的 15–30 秒短剧。</p>
      </div>

      {!storyCore && editable && (
        <section className="panel" data-testid="creative-entry">
          <h3>你想从哪里开始？</h3>
          <div className="director-choice-grid" role="radiogroup" aria-label="创作入口">
            {ENTRY_MODES.map((mode) => (
              <button
                key={mode.id}
                type="button"
                role="radio"
                aria-checked={entryMode === mode.id}
                className={entryMode === mode.id ? "selected" : ""}
                onClick={() => setEntryMode(mode.id)}
              >
                <strong>{mode.title}</strong><span>{mode.description}</span>
              </button>
            ))}
          </div>

          {entryMode === "no_idea" && (
            <div className="director-goal-list" role="radiogroup" aria-label="创作目标">
              {CREATION_GOALS.map((goal) => (
                <label key={goal.id} className={creationGoal === goal.id ? "selected" : ""}>
                  <input type="radio" name="creation-goal" checked={creationGoal === goal.id} onChange={() => setCreationGoal(goal.id)} />
                  <span><strong>{goal.title}</strong><small>{goal.description}</small></span>
                </label>
              ))}
            </div>
          )}
          {entryMode === "one_sentence" && (
            <label>用一句话说出你最想看到的故事<textarea value={idea} onChange={(event) => setIdea(event.target.value)} rows={3} placeholder="例如：搬家前夜，她发现一直讨厌的邻居替她保守了十年的秘密。" /></label>
          )}
          {entryMode === "import_script" && (
            <div className="form-grid">
              <label>粘贴剧本文字<textarea value={scriptText} onChange={(event) => setScriptText(event.target.value)} rows={9} placeholder="只导入你原创或已获得明确授权的内容" /></label>
              <label>改编方式<select value={adaptationMode} onChange={(event) => setAdaptationMode(event.target.value as AdaptationMode)}><option value="faithful">忠实原作</option><option value="balanced">保留内核，适配短剧</option><option value="free">自由改编</option></select></label>
              <label className="director-rights-confirm"><input type="checkbox" checked={sourceRightsConfirmed} onChange={(event) => setSourceRightsConfirmed(event.target.checked)} /><span>我确认自己拥有这段文字的使用和改编权</span></label>
            </div>
          )}
          <div className="toolbar">
            <button type="button" className="primary" data-testid="generate-concepts" disabled={!ready || busy} onClick={() => conceptMutation.mutate(currentConceptInput())}>
              {conceptMutation.isPending ? "AI 导演构思中…" : "授权本次文字生成并给我三个方向"}
            </button>
          </div>
          <p className="muted">这一步只调用文字模型，不会产生图片或视频费用。</p>
        </section>
      )}

      {concepts && !storyCore && (
        <section className="panel" data-testid="concept-set">
          <div className="panel-header"><div><h3>三个原创概念</h3><p className="muted">第 {conceptArtifact?.revision_no ?? 1} 版 · 选择不等于锁定，生成完整方案后仍需你确认</p></div></div>
          <div className="director-concept-grid">
            {concepts.concepts.map((concept) => <ConceptCard key={concept.concept_id} concept={concept} selected={selectedConceptId === concept.concept_id} onSelect={() => setSelectedConceptId(concept.concept_id)} />)}
          </div>
          <div className="director-feedback">
            <label>还没选中？直接说喜欢和不喜欢的部分<textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} rows={3} placeholder="例如：喜欢第二个的关系，但不想要悲剧；希望冲突更日常、更克制。" /></label>
            <button type="button" disabled={!feedback.trim() || busy} onClick={() => preferenceMutation.mutate()}>{preferenceMutation.isPending ? "正在理解…" : "生成偏好理解卡"}</button>
          </div>
        </section>
      )}

      {preference && preferenceArtifact && preferenceIsForCurrentConcept && !storyCore && (
        <PreferenceCard preference={preference} busy={conceptMutation.isPending} onConfirm={() => conceptMutation.mutate(currentConceptInput(preferenceArtifact.id))} />
      )}

      {storyCore && reconsiderConcept && concepts && (
        <section className="panel" data-testid="reconsider-concept-set">
          <h3>重新选择故事方向</h3>
          <p className="muted">这里只创建新的未锁定版本；当前方案仍保留，直到你确认新版本。</p>
          <div className="director-concept-grid">
            {concepts.concepts.map((concept) => <ConceptCard key={concept.concept_id} concept={concept} selected={selectedConceptId === concept.concept_id} onSelect={() => setSelectedConceptId(concept.concept_id)} />)}
          </div>
        </section>
      )}

      {selectedConcept && (!storyCore || reconsiderConcept) && (
        <section className="panel" data-testid="locked-story-choices">
          <h3>把这个方向变成你的故事</h3>
          <p className="muted">以下四项是作品归属感的核心。AI 可以建议，但不会在你确认后暗改。</p>
          <div className="form-grid">
            <label>主题<input value={theme} onChange={(event) => setTheme(event.target.value)} /></label>
            <label>核心冲突<textarea value={coreConflict} onChange={(event) => setCoreConflict(event.target.value)} rows={2} /></label>
            <label>情绪走向<input value={emotionalDirection} onChange={(event) => setEmotionalDirection(event.target.value)} placeholder="例如：戒备 → 动摇 → 坦诚" /></label>
            <label>结局落点<textarea value={ending} onChange={(event) => setEnding(event.target.value)} rows={2} /></label>
          </div>
          <button type="button" className="primary" data-testid="generate-creative-package" disabled={busy || !theme.trim() || !coreConflict.trim() || !emotionalDirection.trim() || !ending.trim()} onClick={() => packageMutation.mutate()}>
            {packageMutation.isPending ? "正在编写和预审…" : "授权本次文字生成并形成完整短剧方案"}
          </button>
        </section>
      )}

      {storyCore && episodeScript && storyReview && (
        <>
          <CreativePackageReview storyCore={storyCore} script={episodeScript} review={storyReview} />
          {editable && snapshot.workflow.status === "awaiting_creative_confirmation" && (
            <section className="panel" data-testid="creative-revision-controls">
              <h3>{storyReview.status === "needs_revision" ? "按预审建议定向修改" : "还不是你想要的？"}</h3>
              <p className="muted">当前方案尚未锁定。调整作品内核后，AI 会生成新版本并重新预审；旧版本仍保留，不会被覆盖。</p>
              <div className="form-grid">
                <label>主题<input value={theme} onChange={(event) => setTheme(event.target.value)} /></label>
                <label>核心冲突<textarea value={coreConflict} onChange={(event) => setCoreConflict(event.target.value)} rows={2} /></label>
                <label>情绪走向<input value={emotionalDirection} onChange={(event) => setEmotionalDirection(event.target.value)} /></label>
                <label>结局落点<textarea value={ending} onChange={(event) => setEnding(event.target.value)} rows={2} /></label>
              </div>
              <button type="button" className="primary" disabled={busy || !selectedConceptId || !theme.trim() || !coreConflict.trim() || !emotionalDirection.trim() || !ending.trim()} onClick={() => packageMutation.mutate()}>
                {packageMutation.isPending ? "正在生成并重新预审…" : "按这些修改生成新版本"}
              </button>
              <button type="button" className="ghost" disabled={busy} onClick={() => setReconsiderConcept((value) => !value)}>
                {reconsiderConcept ? "收起概念选择" : "返回三个概念重新选择"}
              </button>
            </section>
          )}
          {snapshot.workflow.status === "awaiting_creative_confirmation" && canConfirmCreative && (
            <section className="panel director-hard-confirm" data-testid="creative-hard-confirmation">
              <div><span>硬确认 1 / 4</span><h3>这是我想表达的故事</h3><p>确认后将锁定故事内核、角色动机和完整对白。之后任何自然语言修改都会先展示影响范围，再由你确认。</p></div>
              <button type="button" className="accent" disabled={busy || storyReview.status !== "passed"} onClick={() => approvalMutation.mutate()}>{approvalMutation.isPending ? "正在锁定…" : "确认创作方案，进入拍摄方案"}</button>
              {storyReview.status !== "passed" && <p className="status-bad">预审尚未通过，请先按建议修改，不能直接进入付费媒体流程。</p>}
            </section>
          )}
        </>
      )}
    </section>
  );
}
