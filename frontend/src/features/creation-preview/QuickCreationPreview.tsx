import { useState } from "react";

import {
  ConstraintChip,
  DirectorPanel,
  MoodboardStrip,
  StoryDirectionCard,
} from "./components";
import { QuickCreationShell } from "./QuickCreationShell";
import { constraints, moodReferences, previewStages, storyDirections } from "./mockData";

export function QuickCreationPreview() {
  const [selectedDirectionId, setSelectedDirectionId] = useState(storyDirections[0].id);
  const [selectedMoodIds, setSelectedMoodIds] = useState(["rain-city", "portrait", "window"]);
  const [confirmed, setConfirmed] = useState(false);
  const selectedDirection = storyDirections.find(
    (direction) => direction.id === selectedDirectionId,
  ) ?? storyDirections[0];

  const toggleMood = (id: string) => {
    setSelectedMoodIds((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  };

  return (
    <QuickCreationShell
      projectName="雨停之前"
      stages={previewStages}
      quickHref="/design-preview/product?view=quick-creation"
      renderDirector={({ collapsed, toggle }) => (
        <DirectorPanel
          collapsed={collapsed}
          selectedDirection={selectedDirection}
          onToggle={toggle}
          onConfirm={() => setConfirmed(true)}
          confirmed={confirmed}
        />
      )}
    >
      <header className="qc-page-heading">
        <p>阶段 01 · 创作方案</p>
        <h1>选择一个故事方向</h1>
        <span>从你想表达的关系和情绪出发，先决定这部短剧真正要讲什么。</span>
      </header>

      <section className="qc-idea-bar" aria-label="原始创意">
        <div>
          <small>你的一句话创意</small>
          <p>一对多年未见的父女，在末班车上重新认识彼此。</p>
        </div>
        <button type="button">修改</button>
      </section>

      <section
        className="qc-story-section"
        aria-labelledby="story-direction-title"
        data-testid="primary-media-area"
      >
        <div className="qc-section-heading">
          <div><p>故事提案</p><h2 id="story-direction-title">三个可以继续发展的方向</h2></div>
          <span>选择 1 个方向</span>
        </div>
        <div className="qc-story-grid" data-testid="story-direction-grid">
          {storyDirections.map((direction) => (
            <StoryDirectionCard
              key={direction.id}
              direction={direction}
              selected={direction.id === selectedDirectionId}
              onSelect={() => {
                setSelectedDirectionId(direction.id);
                setConfirmed(false);
              }}
            />
          ))}
        </div>
      </section>

      <section className="qc-visual-row">
        <div className="qc-mood-section">
          <div className="qc-section-heading compact">
            <div><p>视觉情绪</p><h2>这部片应该是什么感觉</h2></div>
            <span>{selectedMoodIds.length} 张已选</span>
          </div>
          <MoodboardStrip
            references={moodReferences}
            selectedIds={selectedMoodIds}
            onToggle={toggleMood}
          />
        </div>
        <div className="qc-constraints" aria-label="项目约束">
          <p>创作边界</p>
          <div>
            {constraints.map((constraint) => (
              <ConstraintChip key={constraint}>{constraint}</ConstraintChip>
            ))}
          </div>
        </div>
      </section>
    </QuickCreationShell>
  );
}
