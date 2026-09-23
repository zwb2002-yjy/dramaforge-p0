import { Button, Field, Select } from "../ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { queryKeys } from "../../lib/queryKeys";

import {
  ApiError,
  getEffectiveBindings,
  getProjectModelProfile,
  listModelSlots,
  listModels,
  putProjectModelProfile,
  type ModelProfileRead,
  type ProfileBindingInput,
  type ModelSlotRead,
} from "../../lib/api";
import { SIMPLE_MODE_SLOT_GROUPS, simpleModeToBindings, slotLabel } from "../../lib/modelProfile";

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
    queryKey: queryKeys.model.slots(),
    queryFn: listModelSlots,
    enabled: Boolean(workspaceId),
  });

  const models = useQuery({
    queryKey: queryKeys.model.catalog(),
    queryFn: () => listModels(),
    enabled: Boolean(workspaceId),
  });

  const effective = useQuery({
    queryKey: queryKeys.model.effectiveBindings(projectId),
    queryFn: () => getEffectiveBindings(projectId),
    enabled: Boolean(workspaceId),
  });

  const projectProfile = useQuery({
    queryKey: queryKeys.model.projectProfile(projectId),
    queryFn: () => getProjectModelProfile(projectId),
    enabled: Boolean(workspaceId),
    retry: false,
  });

  const slotById = useMemo(() => new Map((slots.data ?? []).map((s) => [s.id, s])), [slots.data]);

  const currentBindings = projectProfile.data?.bindings ?? {};

  const [simple, setSimple] = useState<Record<string, string>>({});

  // Per-slot model choices in advanced mode, seeded from the current profile.
  const [advancedChoices, setAdvancedChoices] = useState<Record<string, string>>({});

  const save = useMutation({
    mutationFn: (bindings: Record<string, ProfileBindingInput>) =>
      putProjectModelProfile(projectId, { bindings }),
    onSuccess: (profile: ModelProfileRead) => {
      queryClient.setQueryData(["project-model-profile", projectId], profile);
      queryClient.invalidateQueries({ queryKey: queryKeys.model.effectiveBindings(projectId) });
      setMessage(
        `模型方案已保存（版本 ${profile.version}）。修改只影响后续生成，运行中的镜头不会自动换模型。`,
      );
      setError(null);
      setSimple({});
      setAdvancedChoices({});
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

  const inheritsProfile =
    projectProfile.error instanceof ApiError && projectProfile.error.status === 404;
  const readFailed =
    slots.isError ||
    models.isError ||
    effective.isError ||
    (projectProfile.isError && !inheritsProfile);
  const readsPending =
    slots.isPending || models.isPending || effective.isPending || projectProfile.isPending;
  const canSave = Boolean(workspaceId) && !readFailed && !readsPending && !save.isPending;

  const saveSimple = () => {
    if (!canSave) return;
    if (!Object.keys(simple).length) {
      setError("请先修改模型选择。");
      return;
    }
    const bindings = existingInputs();
    for (const [group, modelId] of Object.entries(simple)) {
      if (!modelId) for (const slot of SIMPLE_MODE_SLOT_GROUPS[group] ?? []) delete bindings[slot];
    }
    save.mutate({ ...bindings, ...simpleModeToBindings(simple) });
  };

  const saveAdvanced = () => {
    if (!canSave) return;
    if (!Object.keys(advancedChoices).length) {
      setError("请先修改模型选择。");
      return;
    }
    const bindings = existingInputs();
    for (const [slot, modelId] of Object.entries(advancedChoices)) {
      if (modelId) bindings[slot] = { model_id: modelId, enabled: true };
      else delete bindings[slot];
    }
    save.mutate(bindings);
  };

  const modelsForCapability = (slot: ModelSlotRead) =>
    (models.data ?? []).filter((m) =>
      slot.capabilities.some((cap) => m.capabilities.includes(cap)),
    );

  const renderModelSelect = (slotId: string, value: string, onChange: (v: string) => void) => {
    const slot = slotById.get(slotId);
    if (!slot) return null;
    const candidates = modelsForCapability(slot);
    return (
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={`model-picker-${slotId}`}
      >
        <option value="">使用默认方案</option>
        {candidates.map((m) => (
          <option key={m.id} value={m.id}>
            {m.display_name}（{m.provider_id}）{m.configured ? "" : " · 未配置"}
          </option>
        ))}
      </Select>
    );
  };

  const profileHasChanges = inheritsProfile && !save.isPending;

  return (
    <section className="panel" data-testid="model-profile-settings">
      <div className="panel-header">
        <h3>模型选择</h3>
      </div>

      {readFailed && (
        <p className="flash err" role="alert">
          模型配置读取失败，请重新读取后再保存。
          <Button
            type="button"
            onClick={() => {
              void slots.refetch();
              void models.refetch();
              void effective.refetch();
              void projectProfile.refetch();
            }}
          >
            重新读取
          </Button>
        </p>
      )}
      {readsPending && <p role="status">正在读取模型配置…</p>}
      {!advanced ? (
        <>
          <div className="status-grid">
            {(["llm", "image", "video"] as const).map((group) => {
              const slotsInGroup = SIMPLE_MODE_SLOT_GROUPS[group];
              const current =
                slotsInGroup.map((s) => currentBindings[s]?.model_id).find((m) => m) ?? "";
              return (
                <Field key={group} className="status-card">
                  <span className="status-label" title={slotsInGroup.map(slotLabel).join(" · ")}>
                    {group === "llm"
                      ? "默认语言模型"
                      : group === "image"
                        ? "默认图片模型"
                        : "默认视频模型"}
                  </span>
                  {renderModelSelect(slotsInGroup[0], simple[group] ?? current, (v) =>
                    setSimple((prev) => ({ ...prev, [group]: v })),
                  )}
                </Field>
              );
            })}
          </div>
          <div className="toolbar">
            <Button type="button" className="primary" onClick={saveSimple} disabled={!canSave}>
              保存模型选择
            </Button>
            <Button type="button" className="ghost" onClick={() => setAdvanced(true)}>
              按环节配置
            </Button>
          </div>
        </>
      ) : (
        <>
          <div className="status-grid">
            {(slots.data ?? [])
              .filter((slot) => slot.id !== "audio.tts")
              .map((slot) => {
                const value = advancedChoices[slot.id] ?? currentBindings[slot.id]?.model_id ?? "";
                return (
                  <Field key={slot.id} className="status-card">
                    <span className="status-label">
                      {slot.display_name}
                      {slot.p0_scope ? "" : " · 扩展"}
                    </span>
                    {renderModelSelect(slot.id, value, (v) =>
                      setAdvancedChoices((prev) => ({ ...prev, [slot.id]: v })),
                    )}
                    <span className="muted">{slot.description}</span>
                  </Field>
                );
              })}
          </div>
          <div className="toolbar">
            <Button type="button" className="primary" onClick={saveAdvanced} disabled={!canSave}>
              保存高级模式
            </Button>
            <Button type="button" className="ghost" onClick={() => setAdvanced(false)}>
              返回常用模型
            </Button>
          </div>
        </>
      )}

      {message && <div className="status-ok">{message}</div>}
      {error && (
        <div className="status-bad" role="alert">
          {error}
        </div>
      )}
      {profileHasChanges && <p className="muted">当前跟随默认方案；保存后仅覆盖此项目。</p>}
    </section>
  );
}
