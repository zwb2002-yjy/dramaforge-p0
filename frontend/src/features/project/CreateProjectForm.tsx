import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Disclosure, Input } from "../../components/ui";
import { createProject, type WorkspaceRead } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import "./create-project-form.css";

const TEMPLATES = [
  { key: "dual_character_conflict_v1", name: "双人对白反转" },
  { key: "single_monologue_v1", name: "单人情绪独白" },
] as const;
const AUTONOMY_LABELS = { AUTO: "导演自动", ASSIST: "导演辅助", MANUAL: "手动控制" };

type Props = {
  open: boolean;
  workspaceId: string | null;
  workspaces: WorkspaceRead[];
  onWorkspaceChange: (id: string | null) => void;
  onCancel: () => void;
  onCreated: (id: string) => void;
};

export function CreateProjectForm({
  open,
  workspaceId,
  workspaces,
  onWorkspaceChange,
  onCancel,
  onCreated,
}: Props) {
  const queryClient = useQueryClient();
  const nameInput = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("新短剧");
  const [aspectRatio, setAspectRatio] = useState<"9:16" | "16:9">("9:16");
  const [startType, setStartType] = useState<"TEMPLATE" | "FREE">("FREE");
  const [templateKey, setTemplateKey] = useState<string>(TEMPLATES[0].key);
  const [autonomy, setAutonomy] = useState<"AUTO" | "ASSIST" | "MANUAL">("ASSIST");
  const create = useMutation({
    mutationFn: () => {
      if (!workspaceId || !workspaces.some((workspace) => workspace.id === workspaceId))
        throw new Error("请先选择工作空间");
      if (!name.trim()) throw new Error("请输入项目名称");
      return createProject({
        workspace_id: workspaceId,
        name: name.trim(),
        aspect_ratio: aspectRatio,
        start_type: startType,
        template_key: startType === "TEMPLATE" ? templateKey : null,
        director_autonomy: autonomy,
      });
    },
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.workspace.projectsRoot() });
      onCreated(project.id);
    },
  });
  const hasWorkspace = workspaces.some((workspace) => workspace.id === workspaceId);
  useEffect(() => {
    if (open && hasWorkspace) nameInput.current?.focus();
  }, [open, hasWorkspace]);
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!create.isPending) create.mutate();
  }
  return (
    <section className="panel df-create-panel" aria-label="新建项目" hidden={!open}>
      <header className="panel-header">
        <h2>新建项目</h2>
      </header>
      <form className="df-project-create-form" onSubmit={submit}>
        <fieldset disabled={create.isPending || !hasWorkspace}>
          <div className="df-project-create-basics">
            <label>
              项目名
              <Input
                ref={nameInput}
                aria-label="项目名"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </label>
            <label>
              画幅
              <select
                aria-label="画幅"
                value={aspectRatio}
                onChange={(event) => setAspectRatio(event.target.value as "9:16" | "16:9")}
              >
                <option value="9:16">9:16 竖屏</option>
                <option value="16:9">16:9 横屏</option>
              </select>
            </label>
          </div>
          <label>
            保存到工作空间
            <select
              aria-label="新项目工作空间"
              value={workspaceId ?? ""}
              onChange={(event) => onWorkspaceChange(event.target.value || null)}
            >
              {workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </label>
          <Disclosure
            title="创作选项"
            description={`${startType === "TEMPLATE" ? "从模板开始" : "自由创建"} · ${AUTONOMY_LABELS[autonomy]}`}
          >
            <div className="df-project-create-options">
              <label>
                创作起点
                <select
                  aria-label="创作起点"
                  value={startType}
                  onChange={(event) => setStartType(event.target.value as "TEMPLATE" | "FREE")}
                >
                  <option value="FREE">自由创建</option>
                  <option value="TEMPLATE">从模板开始</option>
                </select>
              </label>
              {startType === "TEMPLATE" && (
                <label>
                  创作模板
                  <select
                    aria-label="创作模板"
                    value={templateKey}
                    onChange={(event) => setTemplateKey(event.target.value)}
                  >
                    {TEMPLATES.map((template) => (
                      <option key={template.key} value={template.key}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                导演参与度
                <select
                  aria-label="导演参与度"
                  value={autonomy}
                  onChange={(event) =>
                    setAutonomy(event.target.value as "AUTO" | "ASSIST" | "MANUAL")
                  }
                >
                  <option value="AUTO">导演自动</option>
                  <option value="ASSIST">导演辅助</option>
                  <option value="MANUAL">手动控制</option>
                </select>
              </label>
              <p className="muted">
                导演参与度不替代你的确认；正式应用、付费执行与导出仍需明确授权。
              </p>
            </div>
          </Disclosure>
        </fieldset>
        {!hasWorkspace && (
          <p role="status">
            请先<a href="/settings/workspaces">创建工作空间</a>，再新建项目。
          </p>
        )}
        {create.isError && (
          <p className="flash err" role="alert">
            {create.error.message}
          </p>
        )}
        <footer className="df-project-create-actions">
          <Button onClick={onCancel} disabled={create.isPending}>
            取消
          </Button>
          <Button
            tone="primary"
            type="submit"
            disabled={!hasWorkspace || !name.trim() || create.isPending}
          >
            {create.isPending ? "正在创建…" : "创建并进入剧本"}
          </Button>
        </footer>
      </form>
    </section>
  );
}
