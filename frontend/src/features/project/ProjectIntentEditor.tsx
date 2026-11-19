import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Alert, Button, Descriptions, Dialog, Fieldset, Form, Input } from "../../components/ui";
import { queryKeys } from "../../lib/queryKeys";
import type { components } from "../../shared/api/generated";
import { fetchProject, previewProjectIntent, updateProject, type ProjectRead } from "./api";
import { ProjectIntentFields } from "./ProjectIntentFields";
import {
  INTENT_FIELDS,
  INTENT_LABELS,
  WORK_TYPE_LABELS,
  projectIntentInput,
  projectIntentPatch,
  projectIntentValues,
  rebaseProjectIntent,
  type ProjectIntentValues,
  type ProjectPatch,
  type ProjectWorkType,
} from "./projectIntent";

function displayValue(field: string, value: unknown): string {
  if (field === "work_type") {
    return value ? WORK_TYPE_LABELS[value as ProjectWorkType] : "待确认";
  }
  if (value == null || value === "") return "未设置";
  const text = String(value);
  return text.length > 140 ? `${text.slice(0, 140)}…` : text;
}

export function ProjectIntentEditor({
  projectId,
  projectName,
  onClose,
}: {
  projectId: string;
  projectName: string;
  onClose: () => void;
}) {
  const [form] = Form.useForm<ProjectIntentValues>();
  const queryClient = useQueryClient();
  const alive = useRef(true);
  const draftRevision = useRef(0);
  const [baseline, setBaseline] = useState<ProjectRead | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [preview, setPreview] = useState<{
    input: ProjectPatch;
    impact: components["schemas"]["ProjectUpdateImpact"];
  } | null>(null);
  const project = useQuery({
    queryKey: queryKeys.project.detail(projectId),
    queryFn: () => fetchProject(projectId),
    retry: false,
    refetchOnMount: "always",
  });
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!baseline && project.isSuccess && !project.isFetching && project.data) {
      setBaseline(project.data);
      form.setFieldsValue(projectIntentValues(project.data));
    }
  }, [baseline, project.data, project.isSuccess, project.isFetching, form]);

  const save = useMutation({
    retry: false,
    mutationFn: (request: { input: ProjectPatch; workspaceId: string }) =>
      updateProject(projectId, request.input, request.workspaceId),
    onError: () => {
      if (alive.current) setPreview(null);
    },
    onSuccess: async (updated) => {
      queryClient.setQueryData<ProjectRead>(queryKeys.project.detail(updated.id), (current) =>
        current && current.version > updated.version ? current : updated,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.workspace.projects(updated.workspace_id),
        }),
        queryClient.invalidateQueries({ queryKey: queryKeys.project.workspaceContext(updated.id) }),
      ]);
      if (alive.current) onClose();
    },
  });
  const busy = save.isPending || previewing || refreshing;

  async function showPreview() {
    if (!baseline || busy) return;
    const revision = draftRevision.current;
    setError(null);
    setMessage(null);
    setPreview(null);
    save.reset();
    try {
      const values = await form.validateFields();
      if (!alive.current || revision !== draftRevision.current) return;
      const input = projectIntentPatch(baseline, values);
      if (Object.keys(input).length === 1) {
        setMessage("当前设置已与输入一致，无需保存。");
        return;
      }
      setPreviewing(true);
      const impact = await previewProjectIntent(projectId, input, baseline.workspace_id);
      if (alive.current && revision === draftRevision.current) setPreview({ input, impact });
    } catch (caught) {
      if (alive.current && caught instanceof Error) setError(caught.message);
    } finally {
      if (alive.current) setPreviewing(false);
    }
  }

  async function compareLatest() {
    if (!baseline || busy) return;
    const revision = draftRevision.current;
    const draft = form.getFieldsValue(true);
    setRefreshing(true);
    setError(null);
    try {
      const latest = await fetchProject(projectId, baseline.workspace_id);
      if (!alive.current) return;
      if (revision !== draftRevision.current) {
        setMessage("输入有新修改，已保留；请重新对照最新设置。");
        return;
      }
      const merged = rebaseProjectIntent(baseline, latest, draft);
      queryClient.setQueryData<ProjectRead>(queryKeys.project.detail(projectId), (current) =>
        current && current.version > latest.version ? current : latest,
      );
      setBaseline(latest);
      form.setFieldsValue(merged);
      setPreview(null);
      save.reset();
      setMessage("已载入最新设置并保留你的修改，请重新预览后确认保存。");
    } catch (caught) {
      if (alive.current) setError(caught instanceof Error ? caught.message : "无法读取最新设置");
    } finally {
      if (alive.current) setRefreshing(false);
    }
  }

  const before = baseline ? projectIntentInput(projectIntentValues(baseline)) : null;
  return (
    <Dialog
      open
      title={`编辑项目「${baseline?.name ?? projectName}」`}
      testId="project-intent-dialog"
      onClose={() => {
        if (!busy) onClose();
      }}
      actions={
        <>
          <Button disabled={busy} onClick={onClose}>
            取消
          </Button>
          {preview ? (
            <Button
              tone="primary"
              disabled={busy || !preview.impact.can_apply}
              onClick={() => {
                if (baseline && preview.impact.can_apply && !busy) {
                  save.mutate({ input: preview.input, workspaceId: baseline.workspace_id });
                }
              }}
            >
              {save.isPending ? "正在保存…" : "确认保存"}
            </Button>
          ) : (
            <Button tone="primary" disabled={busy || !baseline} onClick={() => void showPreview()}>
              {previewing ? "正在预览…" : "预览修改"}
            </Button>
          )}
        </>
      }
    >
      {!baseline && !project.isError && <p role="status">正在读取项目…</p>}
      {!baseline && project.isError && (
        <Alert
          type="error"
          showIcon
          role="alert"
          description="无法读取项目，请重试。"
          action={<Button onClick={() => void project.refetch()}>重试</Button>}
        />
      )}
      <Form
        form={form}
        layout="vertical"
        hidden={!baseline}
        onValuesChange={() => {
          draftRevision.current += 1;
          setPreview(null);
          setMessage(null);
          setError(null);
          save.reset();
        }}
      >
        <Fieldset disabled={busy || !baseline}>
          <Form.Item
            label="项目名"
            name="name"
            rules={[
              { required: true, whitespace: true, message: "请输入项目名" },
              {
                validator: async (_, value: string | undefined) => {
                  if ([...(value?.trim() ?? "")].length > 160) throw new Error("项目名最多160字");
                },
              },
            ]}
          >
            <Input aria-label="项目名" maxLength={320} />
          </Form.Item>
          <ProjectIntentFields expanded allowUnconfirmed={baseline?.work_type == null} />
        </Fieldset>
      </Form>
      {baseline && project.data && project.data.version > baseline.version && (
        <p role="status">项目有新的修改；你的输入已保留，请对照最新设置。</p>
      )}
      {message && <p role="status">{message}</p>}
      {(error || save.isError) && (
        <Alert role="alert" type="error" showIcon description={error ?? save.error?.message} />
      )}
      {baseline && (
        <Button disabled={busy} onClick={() => void compareLatest()}>
          对照最新版本（保留修改）
        </Button>
      )}
      {preview && before && (
        <section aria-label="项目修改预览">
          <p>
            {baseline?.work_type === "animation_promo" &&
            (!preview.input.work_type || preview.input.work_type === "animation_promo")
              ? "本次不会删除已有内容或改写正式交付。"
              : `已有 ${preview.impact.episode_count} 集内容；本次不会删除已有内容或改写正式交付。`}
          </p>
          <Descriptions
            column={1}
            size="small"
            items={INTENT_FIELDS.filter((field) => field in preview.input).map((field) => ({
              key: field,
              label: INTENT_LABELS[field],
              children: `${displayValue(field, before[field])} → ${displayValue(field, preview.input[field])}`,
            }))}
          />
          {preview.impact.blockers.map((blocker) => (
            <Alert key={blocker} role="alert" type="error" showIcon description={blocker} />
          ))}
        </section>
      )}
    </Dialog>
  );
}
