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
  for (const slot of slots) {
    const model = profile?.bindings[slot]?.model_id;
    if (model) return model;
  }
  return "";
}

export function WorkspaceModelProfileSettings({ workspaceId }: WorkspaceModelProfileSettingsProps) {
  const queryClient = useQueryClient();
  const [selectedProfileId, setSelectedProfileId] = useState<string | null>(null);
  const [newProfileName, setNewProfileName] = useState("");
  const [newProfileDefault, setNewProfileDefault] = useState(false);
  const [profileName, setProfileName] = useState("");
  const [simple, setSimple] = useState({ llm: "", image: "", video: "" });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const profiles = useQuery({
    queryKey: queryKeys.model.workspaceProfiles(workspaceId),
    queryFn: () => listWorkspaceModelProfiles(workspaceId!),
    enabled: Boolean(workspaceId),
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
  });
  const modelsForGroup = (group: keyof typeof SIMPLE_CAPABILITIES) =>
    (models.data ?? []).filter((model) =>
      model.capabilities.includes(SIMPLE_CAPABILITIES[group]),
    );

  useEffect(() => {
    const first = profiles.data?.[0];
    if (!selectedProfileId && first) setSelectedProfileId(first.id);
    if (
      selectedProfileId &&
      profiles.data &&
      !profiles.data.some((candidate) => candidate.id === selectedProfileId)
    ) {
      setSelectedProfileId(first?.id ?? null);
    }
    if (profiles.data && profiles.data.length === 0) setNewProfileDefault(true);
  }, [profiles.data, selectedProfileId]);

  useEffect(() => {
    if (!profile.data) return;
    setProfileName(profile.data.name);
    setSimple({
      llm: modelForSlots(profile.data, SIMPLE_SLOTS.llm),
      image: modelForSlots(profile.data, SIMPLE_SLOTS.image),
      video: modelForSlots(profile.data, SIMPLE_SLOTS.video),
    });
  }, [profile.data]);

  const invalidateProfiles = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.model.workspaceProfiles(workspaceId),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.model.workspaceProfile(workspaceId, selectedProfileId),
    });
  };

  const createMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId || !newProfileName.trim()) throw new Error("请输入方案名称");
      return createWorkspaceModelProfile(workspaceId, {
        name: newProfileName.trim(),
        bindings: {},
        is_default: newProfileDefault,
      });
    },
    onSuccess: async (created) => {
      setNewProfileName("");
      setSelectedProfileId(created.id);
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
    mutationFn: () => {
      if (!workspaceId || !selectedProfileId || !profile.data || !profileName.trim()) {
        throw new Error("请输入方案名称");
      }
      return updateWorkspaceModelProfile(workspaceId, selectedProfileId, {
        name: profileName.trim(),
        expected_version: profile.data.version,
      });
    },
    onSuccess: async () => {
      setMessage("方案名称已保存。");
      setError(null);
      await invalidateProfiles();
    },
    onError: (cause: Error) => {
      setError(cause.message);
      setMessage(null);
    },
  });

  const simpleMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId || !selectedProfileId || !profile.data) throw new Error("请先选择方案");
      if (!simple.llm && !simple.image && !simple.video) throw new Error("请至少选择一个模型");
      return applySimpleMode(workspaceId, selectedProfileId, {
        llm_model_id: simple.llm || undefined,
        image_model_id: simple.image || undefined,
        video_model_id: simple.video || undefined,
        expected_version: profile.data.version,
      });
    },
    onSuccess: async () => {
      setMessage("默认模型方案已保存，后续新项目会读取它。");
      setError(null);
      await invalidateProfiles();
    },
    onError: (cause: Error) => {
      setError(cause.message);
      setMessage(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => {
      if (!workspaceId || !selectedProfileId || selectedSummary?.is_default) {
        throw new Error("默认方案不能删除");
      }
      return deleteWorkspaceModelProfile(workspaceId, selectedProfileId);
    },
    onSuccess: async () => {
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

  function submitNewProfile(event: FormEvent) {
    event.preventDefault();
    if (!createMutation.isPending) createMutation.mutate();
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
          <h2>工作区模型方案</h2>
          <p className="muted">配置项目未固化模型方案时使用的默认模型；项目方案仍可单独覆盖。</p>
        </div>
      </div>

      <form className="inline-form" onSubmit={submitNewProfile}>
        <input
          aria-label="新模型方案名称"
          value={newProfileName}
          onChange={(event) => setNewProfileName(event.target.value)}
          placeholder="新模型方案名称"
        />
        <label>
          <input
            type="checkbox"
            checked={newProfileDefault}
            onChange={(event) => setNewProfileDefault(event.target.checked)}
          />
          设为默认
        </label>
        <button type="submit" disabled={!newProfileName.trim() || createMutation.isPending}>
          创建方案
        </button>
      </form>

      {profiles.isLoading ? (
        <p className="muted" role="status">
          正在读取工作区方案…
        </p>
      ) : profiles.isError ? (
        <p className="flash err">工作区方案读取失败：{(profiles.error as Error).message}</p>
      ) : profiles.data?.length ? (
        <>
          <label>
            当前方案
            <select
              aria-label="工作区模型方案"
              value={selectedProfileId ?? ""}
              onChange={(event) => setSelectedProfileId(event.target.value || null)}
            >
              {profiles.data.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name}
                  {candidate.is_default ? " · 默认" : ""} · v{candidate.version}
                </option>
              ))}
            </select>
          </label>
          {profile.data && (
            <div className="status-grid" style={{ marginTop: "0.8rem" }}>
              <label className="status-card">
                <span className="status-label">方案名称</span>
                <input
                  aria-label="当前方案名称"
                  value={profileName}
                  onChange={(event) => setProfileName(event.target.value)}
                />
                <button
                  type="button"
                  className="ghost"
                  onClick={() => renameMutation.mutate()}
                  disabled={renameMutation.isPending || !profileName.trim()}
                >
                  保存名称
                </button>
              </label>
              {(["llm", "image", "video"] as const).map((group) => (
                <label className="status-card" key={group}>
                  <span className="status-label">
                    {group === "llm" ? "语言模型" : group === "image" ? "图片模型" : "视频模型"}
                  </span>
                  <select
                    aria-label={`工作区${group === "llm" ? "语言" : group === "image" ? "图片" : "视频"}模型`}
                    value={simple[group]}
                    onChange={(event) =>
                      setSimple((current) => ({ ...current, [group]: event.target.value }))
                    }
                  >
                    <option value="">保持当前值</option>
                    {modelsForGroup(group).map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.display_name} · {model.provider_id}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          )}
          <div className="toolbar">
            <button
              type="button"
              className="primary"
              onClick={() => simpleMutation.mutate()}
              disabled={simpleMutation.isPending || !profile.data}
            >
              保存默认模型
            </button>
            <button
              type="button"
              className="ghost danger"
              onClick={() => {
                if (window.confirm(`删除方案「${selectedSummary?.name ?? ""}」？`)) {
                  deleteMutation.mutate();
                }
              }}
              disabled={Boolean(selectedSummary?.is_default) || deleteMutation.isPending}
              title={selectedSummary?.is_default ? "默认方案不能删除" : undefined}
            >
              删除方案
            </button>
          </div>
        </>
      ) : (
        <p className="muted">尚无工作区方案，请先创建一个。</p>
      )}

      {message && <div className="status-ok">{message}</div>}
      {error && <div className="status-bad">{error}</div>}
    </section>
  );
}
