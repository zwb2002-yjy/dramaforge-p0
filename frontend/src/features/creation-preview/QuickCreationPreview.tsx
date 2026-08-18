import { useState } from "react";
import {
  Aperture,
  ChevronLeft,
  CircleHelp,
  Clapperboard,
  FolderKanban,
  Library,
  Menu,
  Settings,
} from "lucide-react";

import {
  ConstraintChip,
  DirectorPanel,
  MoodboardStrip,
  StageStepper,
  StoryDirectionCard,
} from "./components";
import { constraints, moodReferences, previewStages, storyDirections } from "./mockData";
import "./quick-creation-preview.css";

export function QuickCreationPreview() {
  const [selectedDirectionId, setSelectedDirectionId] = useState(storyDirections[0].id);
  const [selectedMoodIds, setSelectedMoodIds] = useState(["rain-city", "portrait", "window"]);
  const [directorCollapsed, setDirectorCollapsed] = useState(false);
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const selectedDirection =
    storyDirections.find((direction) => direction.id === selectedDirectionId) ?? storyDirections[0];

  const toggleMood = (id: string) => {
    setSelectedMoodIds((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  };

  return (
    <div
      className={`qc-preview-shell${sidebarExpanded ? " sidebar-expanded" : ""}${directorCollapsed ? " director-collapsed" : ""}`}
      data-testid="quick-creation-preview"
    >
      <aside className="qc-sidebar" aria-label="产品预览导航">
        <div className="qc-sidebar-head">
          <div className="qc-brand">
            <Aperture size={22} aria-hidden="true" />
            <span>DramaForge</span>
          </div>
          <button
            type="button"
            className="qc-icon-button qc-sidebar-toggle"
            onClick={() => setSidebarExpanded((value) => !value)}
            aria-label={sidebarExpanded ? "收起导航" : "展开导航"}
            aria-expanded={sidebarExpanded}
          >
            {sidebarExpanded ? (
              <ChevronLeft size={19} aria-hidden="true" />
            ) : (
              <Menu size={19} aria-hidden="true" />
            )}
          </button>
        </div>
        <nav>
          <a href="/" aria-label="返回项目大厅">
            <FolderKanban size={18} aria-hidden="true" />
            <span>项目大厅</span>
          </a>
          <a href="/design-preview/product?view=quick-creation" className="active">
            <Clapperboard size={18} aria-hidden="true" />
            <span>快速创作</span>
          </a>
          <a href="/design-preview">
            <Library size={18} aria-hidden="true" />
            <span>素材库</span>
          </a>
        </nav>
        <div className="qc-sidebar-bottom">
          <a href="/design-preview">
            <Settings size={18} aria-hidden="true" />
            <span>设置</span>
          </a>
          <a href="/design-preview">
            <CircleHelp size={18} aria-hidden="true" />
            <span>帮助</span>
          </a>
        </div>
      </aside>

      <div className="qc-workspace">
        <header className="qc-project-bar">
          <span className="qc-project-name">雨停之前</span>
          <span className="qc-project-save">已保存</span>
          <span className="qc-project-mode">快速模式</span>
          <button type="button" className="qc-avatar" aria-label="账户菜单">
            林
          </button>
        </header>

        <div className="qc-content-grid">
          <main className="qc-main-canvas">
            <StageStepper stages={previewStages} />

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
                <div>
                  <p>故事提案</p>
                  <h2 id="story-direction-title">三个可以继续发展的方向</h2>
                </div>
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
                  <div>
                    <p>视觉情绪</p>
                    <h2>这部片应该是什么感觉</h2>
                  </div>
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
          </main>

          <DirectorPanel
            collapsed={directorCollapsed}
            selectedDirection={selectedDirection}
            onToggle={() => setDirectorCollapsed((value) => !value)}
            onConfirm={() => setConfirmed(true)}
            confirmed={confirmed}
          />
        </div>
      </div>
    </div>
  );
}
