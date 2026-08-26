import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import {
  getEffectiveBindings,
  getProjectModelProfile,
  listModelSlots,
  listModels,
  putProjectModelProfile,
  type ModelProfileRead,
  type ProfileBindingInput,
  type ModelSlotRead,
} from "../../lib/api";
import { SIMPLE_MODE_SLOT_GROUPS, simpleModeToBindings } from "../../lib/modelProfile";

/**
 * Project "AI 制作模型方案" (model role configuration, spec §52/§127).
 *
 * Simple mode maps LLM / Image / Video onto slot groups (spec §78); advanced
 * mode edits each P0 slot individually. ``bindings`` stays the single source of
 * truth — simple mode only generates a bindings patch (spec §32/§77).
 */

type ModelProfileSettingsProps = {
  projectId: string;
  workspaceId: string | null;
};

export function ModelProfileSettings({ projectId, workspaceId }: ModelProfileSettingsProps) {
  const queryClient = useQueryClient();
  const [advanced, setAdvanced] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const slots = useQuery({
    queryKey: ["model-slots"],
    queryFn: listModelSlots,
    enabled: Boolean(workspaceId),
  });

  const models = useQuery({
    queryKey: ["models"],
    queryFn: () => listModels(),
    enabled: Boolean(workspaceId),
  });

  const effective = useQuery({
    queryKey: ["model-bindings-effective", projectId],
    queryFn: () => getEffectiveBindings(projectId),
    enabled: Boolean(workspaceId),
  });

  const projectProfile = useQuery({
    queryKey: ["project-model-profile", projectId],
    queryFn: () => getProjectModelProfile(projectId),
    enabled: Boolean(workspaceId),
    retry: false,
  });

  const slotById = useMemo(
    () => new Map((slots.data ?? []).map((s) => [s.id, s])),
    [slots.data],
  );

  const effectiveById = useMemo(
    () => new Map((effective.data ?? []).map((b) => [b.slot, b])),
    [effective.data],
  );

  const currentBindings = projectProfile.data?.bindings ?? {};

  const [simple, setSimple] = useState<Record<string, string>>({
    llm: "",
    image: "",
    video: "",
    voice: "",
  });

  // Per-slot model choices in advanced mode, seeded from the current profile.
  const [advancedChoices, setAdvancedChoices] = useState<Record<string, string>>({});

  const effectiveSlotModel = (slotId: string): string => {
    const current = currentBindings[slotId]?.model_id;
    if (current) return current;
    return effectiveById.get(slotId)?.model_id ?? "";
  };

  const save = useMutation({
    mutationFn: (bindings: Record<string, ProfileBindingInput>) =>
      putProjectModelProfile(projectId, { bindings }),
    onSuccess: (profile: ModelProfileRead) => {
      queryClient.setQueryData(["project-model-profile", projectId], profile);
      queryClient.invalidateQueries({ queryKey: ["model-bindings-effective", projectId] });
      setMessage(`已保存（版本 ${profile.version}）。修改只影响后续生成，运行中的镜头不会自动换模型。`);
      setError(null);
    },
    onError: (err: Error) => {
      setError(err.message);
      setMessage(null);
    },
  });

  const existingInputs = (): Record<string, ProfileBindingInput> => {
    const out: Record<string, ProfileBindingInput> = {};
    for (const [slotId, read] of Object.entries(projectProfile.data?.bindings ?? {})) {
      out[slotId] = {
        model_id: read.model_id,
        native_options: read.native_options,
        enabled: read.enabled,
      };
    }
    return out;
  };

  const saveSimple = () => {
    const patch = simpleModeToBindings({
      llm: simple.llm || undefined,
      image: simple.image || undefined,
      video: simple.video || undefined,
    });
    if (Object.keys(patch).length === 0) {
      setError("请至少选择一个模型。");
      return;
    }
    // Merge over the existing bindings so untouched slots are preserved
    // (the PUT replaces the whole map; the patch must carry the full set).
    save.mutate({ ...existingInputs(), ...patch });
  };

  const saveAdvanced = () => {
    const patch: Record<string, ProfileBindingInput> = {};
    for (const slot of slots.data ?? []) {
      const modelId = advancedChoices[slot.id] ?? effectiveSlotModel(slot.id);
      if (modelId) {
        patch[slot.id] = { model_id: modelId };
      }
    }
    if (Object.keys(patch).length === 0 && !projectProfile.data) {
      setError("没有可保存的模型选择。");
      return;
    }
    save.mutate({ ...existingInputs(), ...patch });
  };

  const modelsForCapability = (slot: ModelSlotRead) =>
    (models.data ?? []).filter((m) =>
      slot.capabilities.some((cap) => m.capabilities.includes(cap)),
    );

  const renderModelSelect = (
    slotId: string,
    value: string,
    onChange: (v: string) => void,
  ) => {
    const slot = slotById.get(slotId);
    if (!slot) return null;
    const candidates = modelsForCapability(slot);
    return (
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={`model-picker-${slotId}`}
      >
        <option value="">（使用工作区 / 系统默认）</option>
        {candidates.map((m) => (
          <option key={m.id} value={m.id}>
            {m.display_name}（{m.provider_id}）{m.configured ? "" : " · 未配置"}
          </option>
        ))}
      </select>
    );
  };

  const profileHasChanges = projectProfile.isError && !save.isPending;

  return (
    <section className="panel" data-testid="model-profile-settings">
      <div className="panel-header">
        <h3>AI 制作模型方案</h3>
        <div className="muted">同一项目可配置默认语言 / 图片 / 视频 / 声音模型。</div>
      </div>

      {!advanced ? (
        <>
          <div className="status-grid">
            {(["llm", "image", "video", "voice"] as const).map((group) => {
              const slotsInGroup = SIMPLE_MODE_SLOT_GROUPS[group];
              const current =
                slotsInGroup
                  .map((s) => effectiveSlotModel(s))
                  .find((m) => m) ?? "";
              return (
                <label key={group} className="status-card" style={{ display: "grid", gap: "0.4rem" }}>
                  <span className="status-label">
                    {group === "llm"
                      ? "默认语言模型"
                      : group === "image"
                        ? "默认图片模型"
                        : group === "video"
                          ? "默认视频模型"
                          : "默认声音模型"}
                  </span>
                  {renderModelSelect(slotsInGroup[0], simple[group] ?? current, (v) =>
                    setSimple((prev) => ({ ...prev, [group]: v })),
                  )}
                  <span className="muted" style={{ fontSize: "0.75rem" }}>
                    应用于 {slotsInGroup.join(" · ")}
                  </span>
                </label>
              );
            })}
          </div>
          <div className="toolbar">
            <button
              type="button"
              className="primary"
              onClick={saveSimple}
              disabled={save.isPending}
            >
              保存简单模式
            </button>
            <button type="button" className="ghost" onClick={() => setAdvanced(true)}>
              高级模型设置
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="status-grid">
            {(slots.data ?? []).map((slot) => {
              const value = advancedChoices[slot.id] ?? effectiveSlotModel(slot.id);
              return (
                <label key={slot.id} className="status-card" style={{ display: "grid", gap: "0.4rem" }}>
                  <span className="status-label">
                    {slot.display_name}
                    {slot.p0_scope ? "" : " · 扩展"}
                  </span>
                  {renderModelSelect(slot.id, value, (v) =>
                    setAdvancedChoices((prev) => ({ ...prev, [slot.id]: v })),
                  )}
                  <span className="muted" style={{ fontSize: "0.75rem" }}>
                    {slot.description}
                  </span>
                </label>
              );
            })}
          </div>
          <div className="toolbar">
            <button type="button" className="primary" onClick={saveAdvanced} disabled={save.isPending}>
              保存高级模式
            </button>
            <button type="button" className="ghost" onClick={() => setAdvanced(false)}>
              返回简单模式
            </button>
          </div>
        </>
      )}

      {message && <div className="status-ok">{message}</div>}
      {error && <div className="status-bad">{error}</div>}
      {profileHasChanges && (
        <div className="muted" style={{ marginTop: "0.6rem" }}>
          当前项目使用工作区默认方案；保存后将固化为本项目专属方案（版本 1）。
        </div>
      )}
    </section>
  );
}
