import { useState, type ReactNode } from "react";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  PageHeader,
  Select,
  Tabs,
  Textarea,
  ActionLink,
} from "../components/ui";

const PALETTE = [
  { name: "Obsidian", hex: "#071013", value: "var(--df-obsidian)" },
  { name: "Ink Blue", hex: "#142129", value: "var(--df-ink)" },
  { name: "Ink Light", hex: "#1c2c33", value: "var(--df-ink-light)" },
  { name: "Verdigris", hex: "#4f9f8c", value: "var(--df-verdigris)" },
  { name: "Brass", hex: "#c69a57", value: "var(--df-brass)" },
  { name: "Ivory", hex: "#eee7db", value: "var(--df-ivory)" },
];

function PreviewSection({ title, children }: { title: string; children: ReactNode }) {
  const id = `preview-${title.toLowerCase()}`;
  return (
    <section className="df-preview-section" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}

export function DesignPreviewPage() {
  const [activeTab, setActiveTab] = useState<"story" | "production">("story");

  return (
    <div className="df-design-preview" data-testid="design-preview">
      <PageHeader
        eyebrow="DramaForge"
        title="Visual System 2.0"
        actions={
          <ActionLink to="/" search={{ create: undefined }} tone="ghost">
            <span aria-hidden="true">←</span>
            返回我的项目
          </ActionLink>
        }
      />

      <PreviewSection title="Color">
        <div className="df-swatch-grid" data-testid="palette-grid">
          {PALETTE.map((color) => (
            <div className="df-swatch" key={color.name}>
              <span className="df-swatch-color" style={{ backgroundColor: color.value }} />
              <span>
                <strong>{color.name}</strong>
                <code>{color.hex}</code>
              </span>
            </div>
          ))}
        </div>
      </PreviewSection>

      <PreviewSection title="Typography">
        <div className="df-type-specimen">
          <p className="display-title">一部短剧，从一个决定开始</p>
          <h1>创作方案</h1>
          <h2>人物与故事</h2>
          <h3>核心冲突</h3>
          <p>让作品和创作决定成为页面的第一层信息。</p>
          <small className="df-muted">预计 4 个镜头 · 约 22 秒</small>
        </div>
      </PreviewSection>

      <PreviewSection title="Button">
        <div className="df-preview-row">
          <Button tone="primary">生成故事方向</Button>
          <Button tone="accent">开始试拍</Button>
          <Button>保存</Button>
          <Button tone="ghost">取消</Button>
          <Button tone="danger">删除</Button>
          <Button disabled>处理中</Button>
        </div>
      </PreviewSection>

      <PreviewSection title="Input">
        <div className="df-preview-form">
          <Field className="df-preview-field" htmlFor="preview-title">
            作品名
            <Input id="preview-title" defaultValue="雨停之前" />
          </Field>
          <Field className="df-preview-field" htmlFor="preview-idea">
            一句话创意
            <Textarea
              id="preview-idea"
              rows={3}
              defaultValue="一对多年未见的父女，在末班车上重新认识彼此。"
            />
          </Field>
          <Field className="df-preview-field" htmlFor="preview-ratio">
            画幅
            <Select id="preview-ratio" defaultValue="9:16">
              <option value="9:16">9:16 竖屏</option>
              <option value="16:9">16:9 横屏</option>
            </Select>
          </Field>
        </div>
      </PreviewSection>

      <PreviewSection title="Tabs">
        <Tabs
          label="工作模式"
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as "story" | "production")}
          items={[
            { key: "story", label: "创作", children: "故事工作区" },
            { key: "production", label: "制作", children: "制作工作区" },
          ]}
        />
      </PreviewSection>

      <PreviewSection title="Badge">
        <div className="df-preview-row">
          <Badge>待处理</Badge>
          <Badge tone="selected">已选择</Badge>
          <Badge tone="success">已完成</Badge>
          <Badge tone="warning">需复核</Badge>
          <Badge tone="danger">失败</Badge>
          <Badge tone="info">信息</Badge>
        </div>
      </PreviewSection>

      <PreviewSection title="Card">
        <div className="df-preview-card-grid">
          <Card>
            <div className="df-card-header">
              <h3>凌晨来信</h3>
              <Badge>草稿</Badge>
            </div>
            <p className="df-muted">母女关系 · 克制 · 开放式结局</p>
          </Card>
          <Card selected>
            <div className="df-card-header">
              <h3>雨停之前</h3>
              <Badge tone="selected">已选择</Badge>
            </div>
            <p className="df-muted">父女重逢 · 温暖 · 和解结局</p>
          </Card>
          <Card className="df-card-quality">
            <div className="df-card-header">
              <h3>代表镜头 03</h3>
              <Badge tone="success">通过</Badge>
            </div>
            <p className="df-muted">人物与构图稳定，动作需要人工确认。</p>
          </Card>
        </div>
      </PreviewSection>
    </div>
  );
}
