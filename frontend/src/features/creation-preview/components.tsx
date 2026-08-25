import type { ReactNode } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  MessageCircleMore,
  Sparkles,
} from "lucide-react";

import type { MoodReference, PreviewStage, StoryDirection } from "./types";

export function StageStepper({
  stages,
  testId = "stage-stepper",
}: {
  stages: PreviewStage[];
  testId?: string;
}) {
  return (
    <ol className="qc-stage-stepper" aria-label="创作进度" data-testid={testId}>
      {stages.map((stage, index) => (
        <li
          className={stage.state}
          key={stage.id}
          aria-current={stage.state === "active" ? "step" : undefined}
        >
          <span className="qc-stage-number">{index + 1}</span>
          <span className="qc-stage-copy">
            <strong>{stage.label}</strong>
            <small>{stage.caption}</small>
          </span>
          {index < stages.length - 1 && <span className="qc-stage-line" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

export function ConstraintChip({ children }: { children: ReactNode }) {
  return <span className="qc-constraint-chip">{children}</span>;
}

type StoryDirectionCardProps = {
  direction: StoryDirection;
  selected: boolean;
  onSelect: () => void;
};

export function StoryDirectionCard({ direction, selected, onSelect }: StoryDirectionCardProps) {
  return (
    <button
      type="button"
      className={`qc-story-card${selected ? " selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
      data-testid={`story-direction-${direction.id}`}
    >
      <span className="qc-story-media">
        <img src={direction.image} alt="" />
        <span className="qc-story-index">方向 {direction.number}</span>
        {selected && (
          <span className="qc-story-selected">
            <Check size={14} strokeWidth={2.2} aria-hidden="true" /> 已选择
          </span>
        )}
      </span>
      <span className="qc-story-body">
        <strong>{direction.title}</strong>
        <span className="qc-story-premise">{direction.premise}</span>
        <span className="qc-story-meta">
          <span>{direction.tone}</span>
          <span>{direction.ending}结局</span>
        </span>
      </span>
    </button>
  );
}

type MoodboardStripProps = {
  references: MoodReference[];
  selectedIds: string[];
  onToggle: (id: string) => void;
};

export function MoodboardStrip({ references, selectedIds, onToggle }: MoodboardStripProps) {
  return (
    <div className="qc-moodboard" data-testid="moodboard-strip">
      {references.map((reference) => {
        const selected = selectedIds.includes(reference.id);
        return (
          <button
            type="button"
            key={reference.id}
            className={selected ? "selected" : ""}
            aria-pressed={selected}
            aria-label={`${selected ? "移除" : "选择"}${reference.alt}`}
            onClick={() => onToggle(reference.id)}
          >
            <img src={reference.image} alt={reference.alt} />
            {selected && <Check size={15} strokeWidth={2.4} aria-hidden="true" />}
          </button>
        );
      })}
    </div>
  );
}

type DirectorPanelProps = {
  collapsed: boolean;
  selectedDirection: StoryDirection;
  onToggle: () => void;
  onConfirm: () => void;
  confirmed: boolean;
};

export function DirectorPanel({
  collapsed,
  selectedDirection,
  onToggle,
  onConfirm,
  confirmed,
}: DirectorPanelProps) {
  if (collapsed) {
    return (
      <aside className="qc-director-panel collapsed" data-testid="director-panel">
        <button
          type="button"
          className="qc-icon-button"
          onClick={onToggle}
          aria-label="展开 AI 导演"
        >
          <ChevronLeft size={19} aria-hidden="true" />
        </button>
        <Sparkles size={19} aria-hidden="true" />
        <span>AI 导演</span>
      </aside>
    );
  }

  return (
    <aside className="qc-director-panel" data-testid="director-panel">
      <header className="qc-director-header">
        <span className="qc-director-mark">
          <Sparkles size={17} aria-hidden="true" />
        </span>
        <span>
          <strong>AI 导演</strong>
          <small>创作方案</small>
        </span>
        <button
          type="button"
          className="qc-icon-button"
          onClick={onToggle}
          aria-label="收起 AI 导演"
        >
          <ChevronRight size={19} aria-hidden="true" />
        </button>
      </header>

      <section className="qc-director-section">
        <p className="qc-director-kicker">当前建议</p>
        <h2>先锁定你真正想讲的故事</h2>
        <p>
          三个方向都围绕关系修复展开。{selectedDirection.title}
          最适合在短时长内完成情绪转折。
        </p>
      </section>

      <section className="qc-director-section qc-decision-list" aria-label="已确定的创作边界">
        <div>
          <Check size={15} aria-hidden="true" />
          <span>
            <strong>表达核心</strong>
            <small>亲密关系中的迟到理解</small>
          </span>
        </div>
        <div>
          <Check size={15} aria-hidden="true" />
          <span>
            <strong>情绪走向</strong>
            <small>{selectedDirection.tone}</small>
          </span>
        </div>
        <div>
          <CircleDollarSign size={15} aria-hidden="true" />
          <span>
            <strong>当前阶段</strong>
            <small>不生成媒体，仅更新文本事实</small>
          </span>
        </div>
      </section>

      <section className="qc-director-section qc-risk-note">
        <strong>导演提醒</strong>
        <p>双人近景对白需要留出清晰的肩线，下一阶段会优先验证人物关系与构图。</p>
      </section>

      <div className="qc-director-actions">
        <button
          type="button"
          className="qc-director-cta"
          onClick={onConfirm}
          data-testid="primary-cta"
        >
          {confirmed ? "方案已确认" : "确认这个故事方向"}
          <ChevronRight size={17} aria-hidden="true" />
        </button>
        <button type="button" className="qc-director-message">
          <MessageCircleMore size={16} aria-hidden="true" />
          和导演说说想改哪里
        </button>
      </div>
    </aside>
  );
}
