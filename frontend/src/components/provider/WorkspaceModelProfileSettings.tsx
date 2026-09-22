import { Button, Checkbox, Disclosure, Field, Input, Select } from "../ui";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  applySimpleMode,
  createWorkspaceModelProfile,
  deleteWorkspaceModelProfile,
  getWorkspaceModelProfile,
  listModels,
  listWorkspaceModelProfiles,
  updateWorkspaceModelProfile,
  type ModelProfileRead,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";

type WorkspaceModelProfileSettingsProps = {
  workspaceId: string | null;
};

const SIMPLE_SLOTS = {
  llm: ["planning.brief", "planning.script", "planning.storyboard"],
  image: ["visual.character", "visual.storyboard", "visual.keyframe"],
  video: ["video.shot"],
} as const;

const SIMPLE_CAPABILITIES = {
  llm: "text.generate",
  image: "image.generate",
  video: "video.image_to_video",
} as const;

function modelForSlots(profile: ModelProfileRead | undefined, slots: readonly string[]): string {
  const values = slots.map((slot) => profile?.bindings?.[slot]?.model_id ?? "未绑定");
  return new Set(values).size === 1 ? values[0] : "各环节不同（保存选择将统一此组）";
}

export function WorkspaceModelProfileSettings({ workspaceId }: WorkspaceModelProfileSettingsProps) {
  const queryClient = useQueryClient();
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);
  const [newProfileName, setNewProfileName] = useState("");
  const [newProfileDefault, setNewProfileDefault] = useState(false);
  const [profileNameDraft, setProfileName] = useState<string | null>(null);
  const [draftVersion, setDraftVersion] = useState<number | null>(null);
  const [simple, setSimple] = useState({ llm: "", image: "", video: "" });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const profiles = useQuery({
    queryKey: queryKeys.model.workspaceProfiles(workspaceId),
    queryFn: () => listWorkspaceModelProfiles(workspaceId!),
    enabled: Boolean(workspaceId),
    retry: false,
  });
  const selectedSummary = useMemo(
    () => profiles.data?.find((candidate) => candidate.id === selectedProfileId) ?? null,
    [profiles.data, selectedProfileId],
  );
  const profile = useQuery({
    queryKey: queryKeys.model.workspaceProfile(workspaceId, selectedProfileId),
    queryFn: () => getWorkspaceModelProfile(workspaceId!, selectedProfileId!),
    enabled: Boolean(workspaceId && selectedProfileId),
    retry: false,
  });
  const models = useQuery({
    queryKey: queryKeys.model.catalog(),
    queryFn: () => listModels(),
    enabled: Boolean(workspaceId),
    retry: false,
  });
  const modelsForGroup = (group: keyof typeof SIMPLE_CAPABILITIES) =>
    (models.data ?? []).filter((model) => model.capabilities.includes(SIMPLE_CAPABILITIES[group]));

  useEffect(() => {
    const first = profiles.data?.[0];
    if (!selectedProfileId && first) setSelectedProfileId(first.id);
    if (profiles.data && profiles.data.length === 0) setNewProfileDefault(true);
  }, [profiles.data, selectedProfileId]);

  const profileName = profileNameDraft ?? profile.data?.name ?? "";
  const hasDraft = profileNameDraft !== null || Object.values(simple).some(Boolean);
  const staleDraft = hasDraft && draftVersion !== null && profile.data?.version !== draftVersion;
  const beginEdit = () => {
    if (!hasDraft && profile.data) setDraftVersion(profile.data.version);
    setMessage(null);
    setError(null);
  };
  const discardDraft = () => {
    setProfileName(null);
    setSimple({ llm: "", image: "", video: "" });
    setDraftVersion(null);
    setMessage(null);
    setError(null);
  };
  const readsReady =
    profiles.isSuccess && Boolean(selectedSummary) && profile.isSuccess && models.isSuccess;

  const invalidateProfiles = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.model.workspaceProfiles(workspaceId),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.model.workspaceProfile(workspaceId, selectedProfileId),
    });
  };

  const createMutation = useMutation({
    retry: false,
    mutationFn: () => {
      if (!workspaceId || !profiles.isSuccess || !newProfileName.trim())
        throw new Error("请输入方案名称");
      return createWorkspaceModelProfile(workspaceId, {
        name: newProfileName.trim(),
        bindings: {},
        is_default: newProfileDefault,
      });
    },
    onSuccess: async (created) => {
      discardDraft();
      setNewProfileName("");
      setSelectedProfileId(created.id);
      queryClient.setQueryData(queryKeys.model.workspaceProfile(workspaceId, created.id), created);
      setMessage("工作区模型方案已创建。项目未固化方案时会使用当前默认方案。");
      setError(null);
      await invalidateProfiles();
    },
    onError: (cause: Error) => {
      setError(cause.message);
      setMessage(null);
    },
  });

  const renameMutation = useMutation({
    retry: false,
    mutationFn: () => {
      if (
        !workspaceId ||
        !selectedProfileId ||
        !profile.data ||
        !profileName.trim() ||
        !readsReady ||
        staleDraft
      ) {
        throw new Error("请输入方案名称");
      }
      return updateWorkspaceModelProfile(workspaceId, selectedProfileId, {
        name: profileName.trim(),
        expected_version: draftVersion ?? profile.data.version,
      });
    },
    onSuccess: async (saved) => {
      setProfileName(null);
      setDraftVersion(Object.values(simple).some(Boolean) ? saved.version : null);
      queryClient.setQueryData(queryKeys.model.workspaceProfile(workspaceId, saved.id), saved);
      setMessage("方案名称已保存；模型草稿需单独保存。");
      setError(null);
      await invalidateProfiles();
    },
    onError: (cause: Error) => {
      setError(cause.message);
      setMessage(null);
    },
  });

  const simpleMutation = useMutation({
    retry: false,
    mutationFn: () => {
      if (!workspaceId || !selectedProfileId || !profile.data || !readsReady || staleDraft)
        throw new Error("请先重新读取并核对方案");
      if (!simple.llm && !simple.image && !simple.video) throw new Error("请至少选择一个模型");
      return applySimpleMode(workspaceId, selectedProfileId, {
        llm_model_id: simple.llm || undefined,
        image_model_id: simple.image || undefined,
        video_model_id: simple.video || undefined,
        expected_version: draftVersion ?? profile.data.version,
      });
    },
    onSuccess: async (saved) => {
      setSimple({ llm: "", image: "", video: "" });
      setDraftVersion(profileNameDraft !== null ? saved.version : null);
      queryClient.setQueryData(queryKeys.model.workspaceProfile(workspaceId, saved.id), saved);
      setMessage(
        saved.is_default
          ? "默认模型方案已保存。未被项目或请求单独覆盖的后续生成会读取它；运行中的任务不会换模型。"
          : "所选方案已保存，但它不是默认方案，不会自动影响作品。",
      );
      setError(null);
      await invalidateProfiles();
    },
    onError: (cause: Error) => {
      setError(cause.message);
      setMessage(null);
    },
  });

  const deleteMutation = useMutation({
    retry: false,
    mutationFn: () => {
      if (!workspaceId || !selectedProfileId || selectedSummary?.is_default) {
        throw new Error("默认方案不能删除");
      }
      return deleteWorkspaceModelProfile(workspaceId, selectedProfileId);
    },
    onSuccess: async () => {
      discardDraft();
      setSelectedProfileId(null);
      setMessage("方案已删除。");
      setError(null);
      await invalidateProfiles();
    },
    onError: (cause: Error) => {
      setError(cause.message);
      setMessage(null);
    },
  });

  const busy =
    createMutation.isPending ||
    renameMutation.isPending ||
    simpleMutation.isPending ||
    deleteMutation.isPending;

  function submitNewProfile(event: FormEvent) {
    event.preventDefault();
    if (!busy && profiles.isSuccess && !hasDraft) createMutation.mutate();
  }

  if (!workspaceId) {
    return (
      <section className="df-settings-card" data-testid="workspace-model-profile-settings">
        <h2>工作区模型方案</h2>
        <p className="muted">请先选择工作空间。</p>
      </section>
    );
  }

  return (
    <section className="df-settings-card" data-testid="workspace-model-profile-settings">
      <div className="panel-header">
        <div>
          <h2>工作空间默认模型</h2>
          <p className="muted">
            默认方案影响没有单独覆盖的后续生成。选择下拉框仅查看方案，不会自动将它设为默认。
          </p>
        </div>
      </div>

      {profiles.isLoading ? (
        <p className="muted" role="status">
          正在读取工作区方案…
        </p>
      ) : profiles.isError ? (
        <p className="flash err" role="alert">
          工作区方案读取失败。
          <Button onClick={() => void profiles.refetch()}>重新读取方案列表</Button>
        </p>
      ) : profiles.data?.length ? (
        <>
          <Field>
            当前方案
            <Select
              aria-label="工作区模型方案"
              value={selectedProfileId ?? ""}
              disabled={busy}
              onChange={(event) => {
                if (hasDraft && !window.confirm("切换方案会放弃未保存修改，是否继续？")) return;
                discardDraft();
                setSelectedProfileId(event.target.value || null);
              }}
            >
              {profiles.data.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name}
                  {candidate.is_default ? " · 默认" : ""} · v{candidate.version}
                </option>
              ))}
            </Select>
          </Field>
          {!selectedSummary && (
            <p role="alert">所选方案已不在列表中，请显式选择其他方案；不会自动迁移草稿。</p>
          )}
          {profile.isPending && <p role="status">正在读取方案详情…</p>}
          {(profile.isError || models.isError) && (
            <p role="alert">
              方案详情或模型目录读取失败；不能保存或把缓存当作当前事实。
              <Button
                onClick={() => {
                  void profile.refetch();
                  void models.refetch();
                }}
              >
                重新读取方案详情
              </Button>
            </p>
          )}
          {staleDraft && (
            <p role="alert">
              方案已在其他位置更新。本地草稿仍保留；请核对并放弃草稿后重新选择，不能覆盖新版本。
            </p>
          )}
          {hasDraft && (
            <p role="status">
              有未保存的方案修改。
              <Button disabled={busy} onClick={discardDraft}>
                放弃方案草稿
              </Button>
            </p>
          )}
          {profile.data && (
            <div className="status-grid" style={{ marginTop: "0.8rem" }}>
              <Field className="status-card">
                <span className="status-label">方案名称</span>
                <Input
                  aria-label="当前方案名称"
                  value={profileName}
                  disabled={busy || !readsReady}
                  onChange={(event) => {
                    beginEdit();
                    setProfileName(event.target.value);
                  }}
                />
                <Button
                  type="button"
                  className="ghost"
                  onClick={() => renameMutation.mutate()}
                  disabled={
                    busy ||
                    !readsReady ||
                    staleDraft ||
                    profileNameDraft === null ||
                    !profileName.trim()
                  }
                >
                  保存名称
                </Button>
              </Field>
              {(["llm", "image", "video"] as const).map((group) => (
                <Field className="status-card" key={group}>
                  <span className="status-label">
                    {group === "llm" ? "语言模型" : group === "image" ? "图片模型" : "视频模型"}
                  </span>
                  <Select
                    aria-label={`工作区${group === "llm" ? "语言" : group === "image" ? "图片" : "视频"}模型`}
                    value={simple[group]}
                    disabled={busy || !readsReady}
                    onChange={(event) => {
                      beginEdit();
                      setSimple((current) => ({ ...current, [group]: event.target.value }));
                    }}
                  >
                    <option value="">保持各环节当前值</option>
                    {modelsForGroup(group).map((model) => (
                      <option
                        key={model.id}
                        value={model.id}
                        disabled={!model.enabled || !model.available}
                      >
                        {model.display_name} · {model.id}
                        {!model.enabled
                          ? " · 已停用"
                          : !model.available
                            ? " · 不可用"
                            : !model.configured
                              ? " · 未配置"
                              : ""}
                      </option>
                    ))}
                  </Select>
                  <span className="muted">
                    已保存：{modelForSlots(profile.data, SIMPLE_SLOTS[group]) || "尚未绑定"}
                    ；本选择会统一该组环节，留空不删除已有配置。
                  </span>
                </Field>
              ))}
            </div>
          )}
          <div className="toolbar">
            <Button
              type="button"
              disabled={busy}
              onClick={() => {
                void profiles.refetch();
                void profile.refetch();
                void models.refetch();
              }}
            >
              重新读取当前方案
            </Button>
            <Button
              type="button"
              className="primary"
              onClick={() => simpleMutation.mutate()}
              disabled={busy || !readsReady || staleDraft || !Object.values(simple).some(Boolean)}
            >
              保存默认模型
            </Button>
            <Button
              type="button"
              className="ghost danger"
              onClick={() => {
                if (window.confirm(`删除方案「${selectedSummary?.name ?? ""}」？`)) {
                  deleteMutation.mutate();
                }
              }}
              disabled={busy || !readsReady || Boolean(selectedSummary?.is_default)}
              title={selectedSummary?.is_default ? "默认方案不能删除" : undefined}
            >
              删除方案
            </Button>
          </div>
        </>
      ) : (
        <p className="muted">尚无工作区方案，请先创建一个。</p>
      )}

      {message && <div className="status-ok">{message}</div>}
      {error && (
        <div className="status-bad" role="alert">
          {error}
        </div>
      )}
      <Disclosure title="新建模型方案">
        {hasDraft && <p className="muted">先保存或放弃当前草稿，再新建方案。</p>}
        <form className="inline-form" onSubmit={submitNewProfile}>
          <Input
            aria-label="新模型方案名称"
            value={newProfileName}
            disabled={busy}
            onChange={(event) => setNewProfileName(event.target.value)}
            placeholder="新模型方案名称"
          />
          <Field>
            <Checkbox
              type="checkbox"
              checked={newProfileDefault}
              disabled={busy}
              onChange={(event) => setNewProfileDefault(event.target.checked)}
            />
            设为默认
          </Field>
          <Button
            type="submit"
            disabled={busy || hasDraft || !profiles.isSuccess || !newProfileName.trim()}
          >
            创建方案
          </Button>
        </form>
      </Disclosure>
    </section>
  );
}
