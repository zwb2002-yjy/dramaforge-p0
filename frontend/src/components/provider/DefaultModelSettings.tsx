import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import {
  ApiError,
  applySimpleMode,
  createWorkspaceModelProfile,
  deleteWorkspaceModelProfile,
  getWorkspaceModelProfile,
  listModels,
  listWorkspaceModelProfiles,
  updateWorkspaceModelProfile,
  type ModelProfileRead,
  type ModelRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import { Button, Disclosure, Field, Input, Select } from "../ui";
import "./provider-settings.css";

type Group = "llm" | "image" | "video";

const GROUPS: Array<{
  id: Group;
  label: string;
  capability: string;
  slots: readonly string[];
}> = [
  {
    id: "llm",
    label: "文本模型",
    capability: "text.generate",
    slots: ["planning.brief", "planning.script", "planning.storyboard"],
  },
  {
    id: "image",
    label: "图片模型",
    capability: "image.generate",
    slots: ["visual.character", "visual.storyboard", "visual.keyframe"],
  },
  {
    id: "video",
    label: "视频模型",
    capability: "video.image_to_video",
    slots: ["video.shot"],
  },
];

const EMPTY_DRAFT: Record<Group, string | null> = { llm: null, image: null, video: null };

/** The saved model of a group, or "" when unset or when its slots differ. */
function savedModel(profile: ModelProfileRead | undefined, slots: readonly string[]): string {
  const values = new Set(slots.map((slot) => profile?.bindings?.[slot]?.model_id ?? ""));
  return values.size === 1 ? [...values][0] : "";
}

function mixed(profile: ModelProfileRead | undefined, slots: readonly string[]): boolean {
  return new Set(slots.map((slot) => profile?.bindings?.[slot]?.model_id ?? "")).size > 1;
}

/**
 * Workspace default models in three choices (文本 / 图片 / 视频). The first save
 * creates the "默认" profile; extra profiles stay under 「多套模型方案」.
 * Only models behind this workspace's own connections are offered.
 */
export function DefaultModelSettings({
  workspaceId,
  onAddProvider,
}: {
  workspaceId: string;
  onAddProvider?: () => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const profiles = useQuery({
    queryKey: queryKeys.model.workspaceProfiles(workspaceId),
    queryFn: () => listWorkspaceModelProfiles(workspaceId),
    retry: false,
  });
  const defaultSummary = profiles.data?.find((item) => item.is_default) ?? null;
  const profile = useQuery({
    queryKey: queryKeys.model.workspaceProfile(workspaceId, defaultSummary?.id ?? null),
    queryFn: () => getWorkspaceModelProfile(workspaceId, defaultSummary!.id),
    enabled: Boolean(defaultSummary),
    retry: false,
  });
  const models = useQuery({
    queryKey: queryKeys.model.catalog(),
    queryFn: () => listModels(),
    retry: false,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.model.workspaceProfiles(workspaceId),
    });
    await queryClient.invalidateQueries({ queryKey: ["workspace-model-profile", workspaceId] });
    // Project source summaries resolve through the workspace default.
    await queryClient.invalidateQueries({ queryKey: ["model-bindings-effective"] });
    await queryClient.invalidateQueries({ queryKey: ["execution-model-preflight"] });
  };
  const fail = (cause: unknown) => {
    setMessage(null);
    if (cause instanceof ApiError && cause.status === 409) {
      setError("模型设置已在别处修改，已重新读取，请再确认一次。");
      void refresh();
      return;
    }
    setError(cause instanceof Error ? cause.message : "保存失败");
  };

  const save = useMutation({
    retry: false,
    mutationFn: async () => {
      let target: ModelProfileRead | undefined = profile.data;
      if (!defaultSummary) {
        target = await createWorkspaceModelProfile(workspaceId, {
          name: "默认",
          bindings: {},
          is_default: true,
        });
      }
      if (!target) throw new Error("正在读取当前设置");
      return applySimpleMode(workspaceId, target.id, {
        llm_model_id: draft.llm || undefined,
        image_model_id: draft.image || undefined,
        video_model_id: draft.video || undefined,
        expected_version: target.version,
      });
    },
    onMutate: () => {
      setMessage(null);
      setError(null);
    },
    onSuccess: async (saved) => {
      queryClient.setQueryData(queryKeys.model.workspaceProfile(workspaceId, saved.id), saved);
      setDraft(EMPTY_DRAFT);
      setMessage("已保存。之后的生成使用这些模型，进行中的任务不受影响。");
      await refresh();
    },
    onError: fail,
  });

  const options = (capability: string): ModelRead[] =>
    (models.data ?? []).filter(
      (model) => model.source === "workspace" && model.capabilities.includes(capability),
    );
  const anyChoices = GROUPS.some((group) => options(group.capability).length > 0);
  const dirty = Object.values(draft).some((value) => value !== null && value !== "");
  const readsReady =
    profiles.isSuccess && models.isSuccess && (!defaultSummary || profile.isSuccess);
  const loadError = profiles.isError || models.isError || profile.isError;

  return (
    <section
      className="df-settings-block"
      aria-labelledby="default-models-title"
      data-testid="workspace-model-profile-settings"
    >
      <header className="df-settings-block-header">
        <div>
          <h2 id="default-models-title">默认模型</h2>
          <p className="muted">所有项目默认使用这里的模型，项目可单独覆盖。</p>
        </div>
      </header>
      {loadError ? (
        <p role="alert">
          无法读取模型设置。
          <Button
            tone="ghost"
            onClick={() => {
              void profiles.refetch();
              void models.refetch();
              void profile.refetch();
            }}
          >
            重试
          </Button>
        </p>
      ) : (
        <div className="df-default-models">
          {GROUPS.map((group) => {
            const choices = options(group.capability);
            const saved = savedModel(profile.data, group.slots);
            const value = draft[group.id] ?? saved;
            const savedMissing = saved && !choices.some((model) => model.id === saved);
            return (
              <div className="df-default-model-row" key={group.id}>
                <Field>
                  {group.label}
                  <Select
                    aria-label={group.label}
                    value={value}
                    disabled={!readsReady || save.isPending}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        [group.id]: event.target.value === saved ? null : event.target.value,
                      }))
                    }
                  >
                    <option value="">
                      {mixed(profile.data, group.slots) ? "各环节不同" : "未选择"}
                    </option>
                    {savedMissing && <option value={saved}>{saved}（当前）</option>}
                    {choices.map((model) => (
                      <option key={model.id} value={model.id} disabled={!model.available}>
                        {model.display_name}
                        {model.available ? "" : " · 待验证"}
                      </option>
                    ))}
                  </Select>
                </Field>
                {readsReady && anyChoices && !choices.length && (
                  <p className="df-default-model-empty">
                    <span className="df-status warn">还没有可用的{group.label}</span>
                  </p>
                )}
              </div>
            );
          })}
          {readsReady && !anyChoices && (
            <p className="df-default-model-empty">
              <span className="df-status warn">还没有可选的模型</span>
              {onAddProvider && (
                <Button tone="ghost" onClick={onAddProvider}>
                  <Plus size={14} aria-hidden="true" />
                  添加供应商
                </Button>
              )}
            </p>
          )}
          <div className="df-default-models-actions">
            {dirty && (
              <Button tone="ghost" disabled={save.isPending} onClick={() => setDraft(EMPTY_DRAFT)}>
                放弃修改
              </Button>
            )}
            <Button
              tone="primary"
              disabled={!readsReady || !dirty || save.isPending}
              onClick={() => save.mutate()}
              data-testid="save-default-models"
            >
              {save.isPending ? "正在保存…" : "保存"}
            </Button>
          </div>
        </div>
      )}
      {message && !error && (
        <p className="df-status ok" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="df-dialog-error" role="alert">
          {error}
        </p>
      )}
      {profiles.isSuccess && (
        <ProfileManager
          workspaceId={workspaceId}
          profiles={profiles.data}
          newName={newName}
          onNewNameChange={setNewName}
          onChanged={async (text) => {
            setDraft(EMPTY_DRAFT);
            setError(null);
            setMessage(text);
            await refresh();
          }}
          onError={fail}
        />
      )}
    </section>
  );
}

function ProfileManager({
  workspaceId,
  profiles,
  newName,
  onNewNameChange,
  onChanged,
  onError,
}: {
  workspaceId: string;
  profiles: Awaited<ReturnType<typeof listWorkspaceModelProfiles>>;
  newName: string;
  onNewNameChange: (value: string) => void;
  onChanged: (message: string) => Promise<void>;
  onError: (cause: unknown) => void;
}) {
  const current = profiles.find((item) => item.is_default);
  const create = useMutation({
    retry: false,
    mutationFn: () =>
      createWorkspaceModelProfile(workspaceId, {
        name: newName.trim(),
        bindings: {},
        is_default: false,
        ...(current ? { copy_from: current.id } : {}),
      }),
    onSuccess: async () => {
      onNewNameChange("");
      await onChanged("方案已创建。设为默认后才会生效。");
    },
    onError,
  });
  const makeDefault = useMutation({
    retry: false,
    mutationFn: (id: string) => {
      const target = profiles.find((item) => item.id === id)!;
      return updateWorkspaceModelProfile(workspaceId, id, {
        is_default: true,
        expected_version: target.version,
      });
    },
    onSuccess: () => onChanged("默认方案已切换。"),
    onError,
  });
  const remove = useMutation({
    retry: false,
    mutationFn: (id: string) => deleteWorkspaceModelProfile(workspaceId, id),
    onSuccess: () => onChanged("方案已删除。"),
    onError,
  });
  const busy = create.isPending || makeDefault.isPending || remove.isPending;

  return (
    <Disclosure title="多套模型方案" testId="model-profile-manager">
      <ul className="df-profile-list">
        {profiles.map((item) => (
          <li key={item.id}>
            <span>
              <strong>{item.name}</strong>
              {item.is_default && <span className="df-status active">默认</span>}
            </span>
            {!item.is_default && (
              <span className="df-profile-actions">
                <Button tone="ghost" disabled={busy} onClick={() => makeDefault.mutate(item.id)}>
                  设为默认
                </Button>
                <Button
                  tone="ghost"
                  className="danger"
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm(`删除方案「${item.name}」？`)) remove.mutate(item.id);
                  }}
                >
                  删除
                </Button>
              </span>
            )}
          </li>
        ))}
        {!profiles.length && <li className="muted">保存默认模型后会自动创建「默认」方案。</li>}
      </ul>
      <div className="df-profile-create">
        <Input
          aria-label="新方案名称"
          placeholder="新方案名称，例如「高质量」"
          value={newName}
          disabled={busy}
          onChange={(event) => onNewNameChange(event.target.value)}
        />
        <Button disabled={busy || !newName.trim()} onClick={() => create.mutate()}>
          新建方案
        </Button>
      </div>
    </Disclosure>
  );
}
