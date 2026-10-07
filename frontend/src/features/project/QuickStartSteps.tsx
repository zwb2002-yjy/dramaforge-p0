import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Check } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "../../components/ui";
import { listModels, type ModelRead, type ProjectRead } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import "./quick-start.css";

const MODEL_KINDS: Array<{ label: string; matches: (capabilities: string[]) => boolean }> = [
  { label: "文本", matches: (caps) => caps.includes("text.generate") },
  { label: "图片", matches: (caps) => caps.includes("image.generate") },
  { label: "视频", matches: (caps) => caps.some((cap) => cap.startsWith("video.")) },
];

/** Which model kinds this workspace can already use, from its own connections. */
function missingModelKinds(models: ModelRead[]): string[] {
  const usable = models.filter((model) => model.source === "workspace" && model.available);
  return MODEL_KINDS.filter(
    (kind) => !usable.some((model) => kind.matches(model.capabilities)),
  ).map((kind) => kind.label);
}

type StepState = "done" | "current" | "pending";

function Step({
  index,
  state,
  title,
  status,
  children,
}: {
  index: number;
  state: StepState;
  title: string;
  status: string;
  children: ReactNode;
}) {
  return (
    <li className={`df-quick-step ${state}`} data-testid={`quick-start-step-${index}`}>
      <span className="df-quick-step-mark" aria-hidden="true">
        {state === "done" ? <Check size={14} /> : index}
      </span>
      <div className="df-quick-step-body">
        <strong>{title}</strong>
        <span className="df-quick-step-status">{status}</span>
      </div>
      <div className="df-quick-step-action">{children}</div>
    </li>
  );
}

/**
 * Three steps on the lobby: connect models, write the story, then make
 * frames and video. Each step reads existing facts only; nothing here starts
 * a generation.
 */
export function QuickStartSteps({
  recentProject,
  hasProjects,
  onCreateProject,
  onOpenProject,
}: {
  recentProject: ProjectRead | null;
  hasProjects: boolean;
  onCreateProject: () => void;
  onOpenProject: (projectId: string) => void;
}) {
  const models = useQuery({
    queryKey: queryKeys.model.catalog(),
    queryFn: () => listModels(),
    retry: false,
  });
  const missing = models.isSuccess ? missingModelKinds(models.data) : null;
  const modelsReady = missing !== null && missing.length === 0;
  const storyReady = hasProjects;

  const modelState: StepState = modelsReady ? "done" : "current";
  const storyState: StepState = storyReady ? "done" : modelsReady ? "current" : "pending";
  const makeState: StepState = storyReady && modelsReady ? "current" : "pending";

  return (
    <section className="df-quick-start" aria-label="开始制作" data-testid="quick-start">
      <ol>
        <Step
          index={1}
          state={modelState}
          title="连接模型"
          status={
            models.isPending
              ? "正在检查…"
              : models.isError
                ? "暂时无法确认"
                : modelsReady
                  ? "文本、图片、视频模型已就绪"
                  : missing && missing.length === MODEL_KINDS.length
                    ? "还没有可用的模型"
                    : `还缺${missing?.join("、")}模型`
          }
        >
          <Link
            to="/settings/models"
            className={modelsReady ? "df-btn" : "df-btn primary"}
            data-testid="quick-start-models"
          >
            {modelsReady ? "管理模型" : "去连接模型"}
            {!modelsReady && <ArrowRight size={14} aria-hidden="true" />}
          </Link>
        </Step>
        <Step
          index={2}
          state={storyState}
          title="写故事"
          status={recentProject ? `最近：${recentProject.name}` : "新建项目，粘贴剧本或写下想法"}
        >
          {recentProject ? (
            <Button
              tone={storyState === "current" ? "primary" : "default"}
              onClick={() => onOpenProject(recentProject.id)}
            >
              继续创作
            </Button>
          ) : (
            <Button
              tone={storyState === "current" ? "primary" : "default"}
              onClick={onCreateProject}
            >
              新建项目
            </Button>
          )}
        </Step>
        <Step
          index={3}
          state={makeState}
          title="生成画面与视频"
          status={recentProject ? "在分镜里逐镜生成，或一键补齐" : "先创建一个项目"}
        >
          {recentProject ? (
            <Link
              to="/projects/$projectId/scenes"
              params={{ projectId: recentProject.id }}
              className={makeState === "current" ? "df-btn primary" : "df-btn"}
              data-testid="quick-start-scenes"
            >
              进入分镜与生成
              <ArrowRight size={14} aria-hidden="true" />
            </Link>
          ) : (
            <Button disabled>进入分镜与生成</Button>
          )}
        </Step>
      </ol>
    </section>
  );
}
