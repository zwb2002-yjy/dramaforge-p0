import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Disclosure,
  Field,
  Fieldset,
  Input,
  Select,
  Card,
  Alert,
  Form,
  Row,
  Col,
  Flex,
  ActionLink,
} from "../../components/ui";
import { createProject } from "./api";
import { type WorkspaceRead } from "../access/api";
import { queryKeys } from "../../lib/queryKeys";
import "./create-project-form.css";
import { fetchProjectCreativeOptions } from "./creative-options";

const TEMPLATES = [
  { key: "dual_character_conflict_v1", name: "双人对白反转" },
  { key: "single_monologue_v1", name: "单人情绪独白" },
] as const;

type ProjectValues = {
  name: string;
  aspectRatio: "9:16" | "16:9";
  startType: "TEMPLATE" | "FREE";
  templateKey: string;
  autonomy: "AUTO" | "ASSIST" | "MANUAL";
  genre: string;
  style: string;
};
const INITIAL_VALUES: ProjectValues = {
  name: "新短剧",
  aspectRatio: "9:16",
  startType: "FREE",
  templateKey: TEMPLATES[0].key,
  autonomy: "ASSIST",
  genre: "",
  style: "",
};

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
  const [form] = Form.useForm<ProjectValues>();
  const name = Form.useWatch("name", form) ?? INITIAL_VALUES.name;
  const startType = Form.useWatch("startType", form) ?? INITIAL_VALUES.startType;
  const options = useQuery({
    queryKey: queryKeys.project.creativeOptions(workspaceId),
    queryFn: fetchProjectCreativeOptions,
    enabled: open && Boolean(workspaceId),
    staleTime: 60_000,
  });
  const create = useMutation({
    mutationFn: ({
      name,
      aspectRatio,
      startType,
      templateKey,
      autonomy,
      genre,
      style,
    }: ProjectValues) => {
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
        ...(genre ? { genre_key: genre } : {}),
        ...(style ? { style_key: style } : {}),
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
  return (
    <Card className="df-create-panel" aria-label="新建项目" hidden={!open}>
      <header className="panel-header">
        <h2>项目信息</h2>
      </header>
      <Form
        name="project-create"
        form={form}
        layout="vertical"
        initialValues={INITIAL_VALUES}
        className="df-project-create-form"
        onFinish={(values) => {
          if (!create.isPending) create.mutate(values);
        }}
      >
        <Fieldset disabled={create.isPending || !hasWorkspace}>
          <Row gutter={["var(--df-space-4)", "var(--df-space-4)"]}>
            <Col xs={24} sm={16}>
              <Form.Item
                label="项目名"
                name="name"
                rules={[{ required: true, whitespace: true, message: "请输入项目名称" }]}
              >
                <Input ref={nameInput} aria-label="项目名" required />
              </Form.Item>
            </Col>
            <Col xs={24} sm={8}>
              <Form.Item label="画幅" name="aspectRatio">
                <Select aria-label="画幅">
                  <option value="9:16">9:16 竖屏</option>
                  <option value="16:9">16:9 横屏</option>
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Field>
            保存到工作空间
            <Select
              aria-label="新项目工作空间"
              value={workspaceId ?? ""}
              onChange={(event) => onWorkspaceChange(event || null)}
            >
              {workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </Select>
          </Field>
          <section aria-label="创作选项">
            <Row gutter={["var(--df-space-4)", "var(--df-space-4)"]}>
              <Col xs={24} sm={12}>
                <Form.Item label="创作起点" name="startType">
                  <Select aria-label="创作起点">
                    <option value="FREE">自由创建</option>
                    <option value="TEMPLATE">从模板开始</option>
                  </Select>
                </Form.Item>
              </Col>
              {startType === "TEMPLATE" && (
                <Col xs={24} sm={12}>
                  <Form.Item label="创作模板" name="templateKey">
                    <Select aria-label="创作模板">
                      {TEMPLATES.map((template) => (
                        <option key={template.key} value={template.key}>
                          {template.name}
                        </option>
                      ))}
                    </Select>
                  </Form.Item>
                </Col>
              )}
              <Col xs={24} sm={12}>
                <Form.Item
                  label="导演参与度"
                  name="autonomy"
                  tooltip="正式应用、付费执行与导出仍需你的确认。"
                >
                  <Select aria-label="导演参与度">
                    <option value="AUTO">导演自动</option>
                    <option value="ASSIST">导演辅助</option>
                    <option value="MANUAL">手动控制</option>
                  </Select>
                </Form.Item>
              </Col>
            </Row>
          </section>
          <Disclosure title="风格与类型（可选）">
            <Row gutter={["var(--df-space-4)", "var(--df-space-4)"]}>
              <Col xs={24} sm={12}>
                <Form.Item label="创作类型" name="genre">
                  <Select aria-label="创作类型" disabled={options.isPending || options.isError}>
                    <option value="">
                      {startType === "TEMPLATE" ? "沿用模板建议" : "暂不指定"}
                    </option>
                    {(options.data?.genres ?? []).map((item) => (
                      <option key={item.key} value={item.key}>
                        {item.display_name}
                      </option>
                    ))}
                  </Select>
                </Form.Item>
              </Col>
              <Col xs={24} sm={12}>
                <Form.Item label="画面风格" name="style">
                  <Select aria-label="画面风格" disabled={options.isPending || options.isError}>
                    <option value="">
                      {startType === "TEMPLATE" ? "沿用模板建议" : "暂不指定"}
                    </option>
                    {(options.data?.styles ?? []).map((item) => (
                      <option key={item.key} value={item.key}>
                        {item.display_name}
                      </option>
                    ))}
                  </Select>
                </Form.Item>
              </Col>
            </Row>
            {options.isError && (
              <p role="alert">
                无法读取类型与风格。
                <Button type="button" onClick={() => void options.refetch()}>
                  重试
                </Button>
              </p>
            )}
          </Disclosure>
        </Fieldset>
        {!hasWorkspace && (
          <p role="status">
            请先
            <ActionLink to="/" search={{ panel: "workspace" }} tone="ghost">
              创建工作空间
            </ActionLink>
            ，再新建项目。
          </p>
        )}
        {create.isError && (
          <Alert role="alert" type="error" showIcon description={<>{create.error.message}</>} />
        )}
        <Flex component="footer" justify="flex-end" wrap gap="var(--df-space-3)">
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
        </Flex>
      </Form>
    </Card>
  );
}
