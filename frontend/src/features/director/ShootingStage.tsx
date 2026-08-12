import { useMutation } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import {
  approveDirectorStage,
  commandKey,
  generateShootingPackage,
} from "./api";
import type {
  CharacterBiblePayload,
  CostEstimatePayload,
  CostLine,
  DirectorWorkspaceSnapshot,
  RiskReportPayload,
  SelectionPlanPayload,
  StoryboardPlanPayload,
  TrialPlanPayload,
  VisualBiblePayload,
  VoiceBiblePayload,
} from "./types";
import { artifactPayload, shootingReadiness } from "./types";

type ShootingStageProps = {
  projectId: string;
  snapshot: DirectorWorkspaceSnapshot;
  refresh: () => Promise<unknown>;
  onMessage: (message: string) => void;
  onError: (message: string) => void;
};

const SHOT_TYPE_ZH: Record<string, string> = {
  wide: "全景",
  medium: "中景",
  medium_close: "中近景",
  close: "近景",
  over_shoulder: "过肩镜头",
  insert: "特写插入",
};

const CAMERA_MOVE_ZH: Record<string, string> = {
  static: "固定",
  push_in: "推进",
  pull_out: "拉远",
  pan: "摇摄",
  tracking: "跟拍",
};

const RISK_CATEGORY_ZH: Record<string, string> = {
  identity: "人物身份",
  multi_person: "多人同框",
  motion: "运动与肢体",
  lip_sync: "对白与口型",
  continuity: "镜头连续性",
  duration: "时长与节奏",
  model: "模型能力",
};

const PURPOSE_ZH: Record<string, string> = {
  character_reference: "虚构角色参考图",
  keyframe: "分镜关键帧",
  video: "图生视频",
  voice: "普通话配音",
};

const BLOCKER_ZH: Record<string, string> = {
  LOCAL_TTS_NOT_ENABLED: "本地普通话配音尚未启用",
  PROVIDER_CONNECTION_MISSING: "生成服务连接不存在",
  MODEL_BINDING_DISABLED: "模型绑定已停用",
  PROVIDER_CONNECTION_DISABLED: "生成服务连接已停用",
  MODEL_NOT_ACCOUNT_VERIFIED: "模型尚未完成账号实测",
  MODEL_QUALITY_GATE_MISSING: "模型尚未通过质量验证",
  MODEL_NOT_IN_CATALOG: "模型不在已知能力目录中",
  MODEL_NO_INVOKE_VALUE: "模型缺少真实调用标识",
};

function displayBlocker(value: string): string {
  if (value.startsWith("MODEL_BINDING_MISSING:")) {
    return `缺少${value.endsWith("video") ? "视频" : "图片"}模型绑定`;
  }
  if (value.startsWith("MODEL_BINDING_NOT_FOUND:")) return "已选择的模型绑定不存在";
  return BLOCKER_ZH[value] ?? value;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function CharacterAndVisual({
  characterBible,
  visualBible,
}: {
  characterBible: CharacterBiblePayload;
  visualBible: VisualBiblePayload;
}) {
  return (
    <section className="panel" data-testid="shooting-character-visual">
      <div className="panel-header"><div><h3>虚构人物与视觉锚点</h3><p className="muted">这里只确认设计文字；还没有生成或上传真人照片。</p></div><span>{visualBible.aspect_ratio}</span></div>
      <div className="director-character-list">
        {characterBible.characters.map((character) => (
          <article key={character.character_id}>
            <strong>{character.name} · {character.age_range}</strong>
            <span>五官：{character.facial_features}</span>
            <span>发型：{character.hair}</span>
            <span>体型：{character.body_shape}</span>
            <span>服装：{character.wardrobe}</span>
            {character.distinguishing_features.length > 0 && <span>识别锚点：{character.distinguishing_features.join(" · ")}</span>}
          </article>
        ))}
      </div>
      <dl className="creative-summary">
        <dt>时代与场景</dt><dd>{visualBible.era_and_setting}</dd>
        <dt>色彩</dt><dd>{visualBible.color_palette}</dd>
        <dt>光线</dt><dd>{visualBible.lighting}</dd>
        <dt>镜头语言</dt><dd>{visualBible.lens_language}</dd>
        <dt>连续性规则</dt><dd>{visualBible.continuity_rules.join("；")}</dd>
      </dl>
    </section>
  );
}

function Voices({ voiceBible }: { voiceBible: VoiceBiblePayload }) {
  return (
    <section className="panel" data-testid="shooting-voices">
      <div className="panel-header"><div><h3>声音方案</h3><p className="muted">普通话 · 内置或自配授权声线 · 不克隆真人声音</p></div><span className="status-ok">声纹克隆已禁用</span></div>
      <div className="director-character-list">
        {voiceBible.voices.map((voice) => (
          <article key={voice.character_id}>
            <strong>{voice.character_name}</strong>
            <span>{voice.voice_description}</span>
            <span>语速：{voice.pace === "slow" ? "慢" : voice.pace === "fast" ? "快" : "中等"}</span>
            <span>情绪范围：{voice.emotional_range.join(" · ")}</span>
          </article>
        ))}
      </div>
    </section>
  );
}

function Storyboard({ storyboard }: { storyboard: StoryboardPlanPayload }) {
  return (
    <section className="panel" data-testid="shooting-storyboard">
      <div className="panel-header"><div><h3>动态分镜方案</h3><p className="muted">{storyboard.shots.length} 个镜头 · 合计约 {storyboard.target_duration_seconds} 秒 · 对白严格来自已锁定剧本</p></div><span>{storyboard.aspect_ratio}</span></div>
      <div className="director-shot-list">
        {storyboard.shots.map((shot) => (
          <article key={shot.shot_id}>
            <header><strong>镜头 {shot.shot_number}</strong><span>{SHOT_TYPE_ZH[shot.shot_type] ?? shot.shot_type} · {CAMERA_MOVE_ZH[shot.camera_move] ?? shot.camera_move} · {shot.duration_seconds} 秒</span></header>
            <p>{shot.location} · {shot.time_of_day} · {shot.characters.join("、")}</p>
            <p>{shot.action}</p>
            {shot.dialogue.map((line, index) => <p className="director-shot-dialogue" key={`${line.speaker}-${index}`}>{line.speaker}：「{line.text}」 <small>{line.emotion}</small></p>)}
            <p className="muted">转场：{shot.transition}</p>
            <details><summary>查看供模型无关的生成意图</summary><dl><dt>画面</dt><dd>{shot.image_prompt}</dd><dt>视频</dt><dd>{shot.video_prompt}</dd></dl></details>
          </article>
        ))}
      </div>
    </section>
  );
}

function Risks({ risk, trial }: { risk: RiskReportPayload; trial: TrialPlanPayload }) {
  return (
    <section className="panel" data-testid="shooting-risks">
      <div className="panel-header"><div><h3>风险预审与代表镜头</h3><p className="muted">生成前只能识别已知风险，真实质量仍由试拍验证。</p></div><strong className={risk.status === "ready" ? "status-ok" : "status-bad"}>{risk.status === "ready" ? "可进入试拍准备" : risk.status === "blocked" ? "存在阻断" : "需要修改"}</strong></div>
      <div className="callout"><strong>建议试拍：{trial.representative_shot_id}</strong><br />{trial.selection_reason}</div>
      <div className="director-risk-list">
        {risk.risks.map((item) => (
          <article key={item.risk_id} className={item.severity}>
            <header><strong>{RISK_CATEGORY_ZH[item.category] ?? item.category}</strong><span>{item.shot_id ?? "全局"} · {item.severity === "blocking" ? "阻断" : item.severity === "warning" ? "警告" : "提示"}</span></header>
            <p>{item.evidence}</p><p className="muted">处理建议：{item.mitigation}</p>
          </article>
        ))}
        {risk.risks.length === 0 && <p className="status-ok">没有发现模板规则能够提前识别的高风险项。</p>}
      </div>
    </section>
  );
}

function ModelSelection({ selection, projectId }: { selection: SelectionPlanPayload; projectId: string }) {
  return (
    <section className="panel" data-testid="shooting-selection">
      <div className="panel-header"><div><h3>推荐模型与能力核对</h3><p className="muted">快速模式不暴露供应商原始 JSON；但不会隐藏能力缺口。</p></div><strong className={selection.status === "ready" ? "status-ok" : "status-bad"}>{selection.status === "ready" ? "全部能力已验证" : selection.status === "unsupported" ? "当前组合不支持" : "需要完成配置"}</strong></div>
      <div className="director-model-plan-list">
        {selection.plans.map((plan) => (
          <article key={plan.purpose}>
            <div><strong>{PURPOSE_ZH[plan.purpose] ?? plan.purpose}</strong><span>{plan.model_id ?? "尚未选定模型"}</span></div>
            <span className={plan.status === "ready" ? "status-ok" : "status-bad"}>{plan.status === "ready" ? "可用" : plan.status === "unsupported" ? "不支持" : "待配置"}</span>
            {plan.blockers.length > 0 && <ul>{plan.blockers.map((blocker) => <li key={blocker}>{displayBlocker(blocker)}</li>)}</ul>}
          </article>
        ))}
      </div>
      {selection.status !== "ready" && (
        <div className="callout warn">先到项目设置完成 Provider、模型绑定与质量验证，再重新生成拍摄方案。 <Link to="/projects/$projectId" params={{ projectId }}>打开项目设置</Link></div>
      )}
    </section>
  );
}

function formatCost(value: string | null, currency: string): string {
  return value === null ? "供应商未提供可验证价格" : `${value} ${currency}`;
}

function CostTable({ title, lines }: { title: string; lines: CostLine[] }) {
  return <div><h4>{title}</h4><ul className="dense">{lines.map((line) => <li key={`${title}-${line.purpose}`}><span>{PURPOSE_ZH[line.purpose] ?? line.purpose} × {line.quantity}</span><strong>{formatCost(line.estimated_amount, line.currency)}</strong></li>)}</ul></div>;
}

function Costs({ cost }: { cost: CostEstimatePayload }) {
  return (
    <section className="panel" data-testid="shooting-costs">
      <div className="panel-header"><div><h3>成本预期</h3><p className="muted">价格快照 {cost.pricing_snapshot_id}</p></div></div>
      <div className="director-cost-grid"><CostTable title="代表镜头试拍" lines={cost.trial} /><CostTable title="正式生产" lines={cost.production} /><CostTable title="单镜修复参考" lines={cost.repair} /></div>
      <div className="status-grid">
        <div className="status-card"><span className="status-label">试拍估算</span><strong>{formatCost(cost.trial_total, cost.currency)}</strong></div>
        <div className="status-card"><span className="status-label">正式生产估算</span><strong>{formatCost(cost.production_total, cost.currency)}</strong></div>
      </div>
      <p className="muted">{cost.disclaimer}</p>
      <p>这里仍是零媒体成本预演；真正试拍前必须由你另行设置硬预算上限。</p>
    </section>
  );
}

export function ShootingStage({ projectId, snapshot, refresh, onMessage, onError }: ShootingStageProps) {
  const characterBible = artifactPayload<CharacterBiblePayload>(snapshot, "character_bible");
  const visualBible = artifactPayload<VisualBiblePayload>(snapshot, "visual_bible");
  const voiceBible = artifactPayload<VoiceBiblePayload>(snapshot, "voice_bible");
  const storyboard = artifactPayload<StoryboardPlanPayload>(snapshot, "storyboard_plan");
  const risk = artifactPayload<RiskReportPayload>(snapshot, "risk_report");
  const selection = artifactPayload<SelectionPlanPayload>(snapshot, "selection_plan");
  const cost = artifactPayload<CostEstimatePayload>(snapshot, "cost_estimate");
  const trial = artifactPayload<TrialPlanPayload>(snapshot, "trial_plan");
  const readiness = shootingReadiness(snapshot);

  const generate = useMutation({
    mutationFn: () => generateShootingPackage(projectId, {
      authorize_text_calls: true,
      idempotency_key: commandKey("shooting-package"),
    }),
    onSuccess: async () => { onMessage("拍摄方案已生成。请检查人物、声音、分镜、风险、能力和成本。"); await refresh(); },
    onError: (error) => onError(errorText(error)),
  });
  const approve = useMutation({
    mutationFn: () => approveDirectorStage(projectId, "shooting_plan", commandKey("approve-shooting")),
    onSuccess: async () => { onMessage("拍摄方案已锁定。下一步只会在你授权预算后试拍一个代表镜头。"); await refresh(); },
    onError: (error) => onError(errorText(error)),
  });
  const busy = generate.isPending || approve.isPending;
  const hasPackage = Boolean(characterBible && visualBible && voiceBible && storyboard && risk && selection && cost && trial);

  return (
    <section data-testid="shooting-stage">
      <section className="panel director-stage-intro">
        <div><span className="director-stage-kicker">阶段 2</span><h2>拍摄方案</h2></div>
        <p>AI 把已锁定剧本翻译成人物、声音和 3–6 个镜头，并提前列出已知风险、能力缺口和成本。生成这一方案只调用文字模型。</p>
      </section>
      {!hasPackage && (
        <section className="panel" data-testid="shooting-generate">
          <h3>准备零媒体成本预演</h3>
          <p>本次会调用文字模型设计人物、声音与分镜，并用确定性规则做风险、模型能力和成本核对；不会生成图片、视频或声音。</p>
          <button type="button" className="primary" disabled={busy} onClick={() => generate.mutate()}>{generate.isPending ? "AI 导演正在拆解拍摄方案…" : "授权本次文字生成并准备拍摄方案"}</button>
        </section>
      )}
      {characterBible && visualBible && <CharacterAndVisual characterBible={characterBible} visualBible={visualBible} />}
      {voiceBible && <Voices voiceBible={voiceBible} />}
      {storyboard && <Storyboard storyboard={storyboard} />}
      {risk && trial && <Risks risk={risk} trial={trial} />}
      {selection && <ModelSelection selection={selection} projectId={projectId} />}
      {cost && <Costs cost={cost} />}
      {hasPackage && snapshot.workflow.status === "awaiting_shooting_confirmation" && snapshot.allowed_actions.includes("confirm_shooting_plan") && (
        <section className="panel director-hard-confirm" data-testid="shooting-hard-confirmation">
          <div><span>硬确认 2 / 4</span><h3>这套人物、声音、分镜和风险方案可以开始试拍</h3><p>确认只锁定拍摄方案，不会生成媒体。下一阶段仍要先查看价格快照并单独授权试拍预算。</p></div>
          <div className="director-confirm-actions">
            <button type="button" className="accent" disabled={busy || !readiness.ready} onClick={() => approve.mutate()}>{approve.isPending ? "正在锁定…" : "确认拍摄方案"}</button>
            <button type="button" disabled={busy} onClick={() => generate.mutate()}>{generate.isPending ? "正在生成修订版…" : "重新生成拍摄方案"}</button>
          </div>
          {!readiness.ready && <div className="callout warn" data-testid="shooting-not-ready"><strong>还不能确认：</strong><ul>{readiness.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul><Link to="/projects/$projectId" params={{ projectId }}>打开项目设置</Link></div>}
        </section>
      )}
    </section>
  );
}
