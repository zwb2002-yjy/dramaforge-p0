import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { fetchProjectAssets } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import {
  createShotReference,
  deleteShotReference,
  fetchAssetCard,
  fetchShotReferences,
  resolveShotReferences,
  roleLabel,
  updateShotReference,
  type ShotBindingRead,
  type ResolvedReferenceRead,
  type ShotExecutionReference,
} from "../../features/assets/api";

export type AssetReferencePickerProps = {
  projectId: string;
  shotId: string;
  purpose?: string;
  /** Concrete, backend-recognised references for the selected Shot. */
  onReferencesChange?: (references: ShotExecutionReference[]) => void;
  onResolutionStateChange?: (state: ReferenceResolutionState) => void;
};

export type ReferenceResolutionState = "loading" | "ready" | "error";

const PURPOSES = [
  "identity",
  "clothing",
  "scene_layout",
  "scene_lighting",
  "style",
  "action",
  "pose",
  "camera_language",
  "audio_rhythm",
  "first_frame",
  "last_frame",
  "generic_reference",
] as const;

/**
 * Creative-language labels for stored business purposes.
 *
 * The stored value stays the contract key; the creative surface must never show
 * the raw key, the provider role or the resolution mode.
 */
const PURPOSE_LABELS: Record<string, string> = {
  identity: "角色身份",
  clothing: "服装造型",
  scene_layout: "空间布局",
  scene_lighting: "场景光线",
  style: "画面风格",
  action: "动作",
  pose: "姿态",
  camera_language: "镜头语言",
  audio_rhythm: "声音节奏",
  first_frame: "首帧",
  last_frame: "尾帧",
  generic_reference: "通用参考",
};

const RESOLUTION_MODE_LABELS: Record<string, string> = {
  current_formal: "跟随当前正式版本",
  pinned_version: "固定到指定版本",
  direct_artifact: "直接使用该素材",
};

const ASSET_KIND_LABELS: Record<string, string> = {
  character: "角色",
  scene: "场景",
  prop: "道具",
  video: "视频",
  audio: "音频",
  image: "图片",
  subtitle: "字幕",
};

function purposeLabel(value: string): string {
  return PURPOSE_LABELS[value] ?? "参考";
}

function resolutionModeLabel(value: string): string {
  return RESOLUTION_MODE_LABELS[value] ?? "跟随当前正式版本";
}

function assetKindLabel(value: string): string {
  return ASSET_KIND_LABELS[value] ?? "素材";
}

/**
 * Phase 2 shot reference picker: shows the shot's business-purpose bindings,
 * lets the user bind an Asset (current_formal), and exposes the resolved
 * artifact identity used by the Workbench execution contract.  Display labels
 * and thumbnails never stand in for an execution reference.
 */
export function AssetReferencePicker({
  projectId,
  shotId,
  purpose = "identity",
  onReferencesChange,
  onResolutionStateChange,
}: AssetReferencePickerProps) {
  const queryClient = useQueryClient();
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [selectedPurpose, setSelectedPurpose] = useState<string>(purpose);
  const [resolvedReferences, setResolvedReferences] = useState<ResolvedReferenceRead[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editAssetId, setEditAssetId] = useState("");
  const [editPurpose, setEditPurpose] = useState<string>(purpose);
  const [editMode, setEditMode] = useState<"current_formal" | "pinned_version">("current_formal");
  const [editError, setEditError] = useState<string | null>(null);

  const assets = useQuery({
    queryKey: queryKeys.asset.picker(projectId),
    queryFn: () => fetchProjectAssets(projectId),
    enabled: Boolean(projectId),
  });
  const bindings = useQuery({
    queryKey: queryKeys.asset.shotReferences(projectId, shotId),
    queryFn: () => fetchShotReferences(projectId, shotId),
    enabled: Boolean(shotId),
  });

  // Resolution is a POST in the existing API because it is a server-side
  // binding resolution operation.  Keep it query-backed here so a selected
  // Shot immediately receives its persisted references without requiring a
  // second manual click.
  const resolution = useQuery({
    queryKey: queryKeys.asset.referenceResolution(projectId, shotId),
    queryFn: () => resolveShotReferences(projectId, shotId),
    enabled: Boolean(projectId) && Boolean(shotId),
  });

  const resolutionQueryKey = queryKeys.asset.referenceResolution(projectId, shotId);

  const clearResolvedReferences = () => {
    setResolvedReferences([]);
    queryClient.setQueryData<ResolvedReferenceRead[] | undefined>(resolutionQueryKey, undefined);
    onReferencesChange?.([]);
  };

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.asset.shotReferences(projectId, shotId),
      }),
      queryClient.invalidateQueries({ queryKey: resolutionQueryKey }),
    ]);
  };

  const create = useMutation({
    mutationFn: () =>
      createShotReference(projectId, shotId, {
        purpose: selectedPurpose,
        asset_id: selectedAssetId || null,
        resolution_mode: "current_formal",
        label: selectedAssetId ? labelFor(selectedAssetId) : "",
      }),
    onSuccess: async () => {
      // Do not leave the old concrete artifacts attached while the binding
      // list is being refreshed.  The next resolution response repopulates
      // the context from the server truth.
      await queryClient.cancelQueries({ queryKey: resolutionQueryKey });
      clearResolvedReferences();
      await invalidate();
    },
  });

  const update = useMutation({
    mutationFn: async (binding: ShotBindingRead) => {
      const assetId = editAssetId || binding.asset_id;
      if (!assetId) throw new Error("请先选择参考素材。");
      let assetVersionId: string | null = null;
      if (editMode === "pinned_version") {
        const card = await fetchAssetCard(projectId, assetId);
        assetVersionId = card.current_version_id;
        if (!assetVersionId) {
          throw new Error("该资产还没有正式版本，无法固定到当前版本。");
        }
      }
      return updateShotReference(projectId, binding.id, {
        expected_version: binding.version,
        asset_id: assetId,
        asset_version_id: assetVersionId,
        resolution_mode: editMode,
        purpose: editPurpose,
      });
    },
    onSuccess: async () => {
      setEditingId(null);
      setEditError(null);
      await queryClient.cancelQueries({ queryKey: resolutionQueryKey });
      clearResolvedReferences();
      await invalidate();
    },
    onError: (cause: Error) => setEditError(cause.message),
  });

  function startEditing(binding: ShotBindingRead) {
    setEditingId(binding.id);
    setEditAssetId(binding.asset_id ?? "");
    setEditPurpose(binding.purpose);
    setEditMode(binding.resolution_mode === "pinned_version" ? "pinned_version" : "current_formal");
    setEditError(null);
  }

  const remove = useMutation({
    mutationFn: (bindingId: string) => deleteShotReference(projectId, bindingId),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: resolutionQueryKey });
      clearResolvedReferences();
    },
    onSuccess: invalidate,
    onError: () => {
      // A failed delete must not leave the parent with a permanently empty
      // execution context; recover the server's still-live binding set.
      void resolution.refetch();
    },
  });

  // A recycled asset is retired from production, so it is neither offered here
  // nor accepted by the server when a binding is created/updated. Existing
  // bindings that still point at one stay readable (labelled below).
  const allAssets = Array.isArray(assets.data) ? assets.data : [];
  const assetOptions = allAssets.filter((asset) => asset.status !== "recycled");
  const rows = useMemo(() => (Array.isArray(bindings.data) ? bindings.data : []), [bindings.data]);

  useEffect(() => {
    // A Shot switch must clear the previous Shot's concrete references before
    // the new query resolves.  SceneWorkspace also remounts this component by
    // Shot id, but this guard keeps the component safe when embedded elsewhere.
    setSelectedAssetId("");
    setSelectedPurpose(purpose);
    clearResolvedReferences();
    onResolutionStateChange?.("loading");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only reset on identity change
  }, [projectId, shotId, purpose]);

  useEffect(() => {
    onResolutionStateChange?.(
      resolution.isFetching
        ? "loading"
        : resolution.isError
          ? "error"
          : resolution.isSuccess
            ? "ready"
            : "loading",
    );
  }, [onResolutionStateChange, resolution.isError, resolution.isFetching, resolution.isSuccess]);

  useEffect(() => {
    if (!Array.isArray(resolution.data)) return;
    const next = resolution.data as ResolvedReferenceRead[];
    setResolvedReferences(next);
    onReferencesChange?.(next.map((reference) => toExecutionReference(reference, rows)));
  }, [onReferencesChange, resolution.data, rows]);

  const resolved = resolvedReferences;
  // A binding that produced no resolved reference does not reach generation even
  // though it is stored: after a version change without usable material, or for a
  // recycled asset, resolution is empty. Surface that instead of showing nothing.
  const resolvedBindingIds = new Set(
    resolved
      .map((reference) => bindingIdForResolvedReference(reference, rows))
      .filter((id): id is string => Boolean(id)),
  );
  const invalidBindings = rows.filter(
    (binding) => resolution.isSuccess && !resolvedBindingIds.has(binding.id),
  );

  function labelFor(assetId: string): string {
    const asset = allAssets.find((item) => item.id === assetId);
    if (!asset) return "@已移除素材";
    return asset.status === "recycled" ? `@${asset.name}（已回收）` : `@${asset.name}`;
  }

  const bindingLabels = rows.map((binding) => binding.label);

  return (
    <div className="qc-reference-picker" data-testid="asset-reference-picker" data-shot-id={shotId}>
      <header>
        <strong>镜头资产引用</strong>
        <span>保存业务目的，不保存 provider role；@文本仅供人类阅读。</span>
      </header>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (selectedAssetId) create.mutate();
        }}
      >
        <select
          aria-label="选择资产"
          value={selectedAssetId}
          onChange={(event) => setSelectedAssetId(event.target.value)}
        >
          <option value="">选择资产…</option>
          {assetOptions.map((asset) => (
            <option key={asset.id} value={asset.id}>
              {asset.name}（{assetKindLabel(asset.kind)}）
            </option>
          ))}
        </select>
        <select
          aria-label="引用目的"
          value={selectedPurpose}
          onChange={(event) => setSelectedPurpose(event.target.value)}
        >
          {PURPOSES.map((item) => (
            <option key={item} value={item}>
              {purposeLabel(item)}
            </option>
          ))}
        </select>
        <button type="submit" disabled={!selectedAssetId || create.isPending}>
          添加引用
        </button>
        <button
          type="button"
          onClick={() => void resolution.refetch()}
          disabled={resolution.isFetching}
        >
          解析引用
        </button>
      </form>

      {editError && (
        <p className="flash err" role="alert">
          引用修改失败：{editError}
        </p>
      )}

      <ul className="qc-binding-list" data-testid="binding-list">
        {rows.map((binding) => (
          <li key={binding.id}>
            {editingId === binding.id ? (
              <div className="qc-binding-editor" data-testid={`binding-editor-${binding.id}`}>
                <select
                  aria-label={`参考素材 ${binding.id}`}
                  value={editAssetId}
                  onChange={(event) => setEditAssetId(event.target.value)}
                >
                  <option value="">选择资产…</option>
                  {assetOptions.map((asset) => (
                    <option key={asset.id} value={asset.id}>
                      {asset.name}（{assetKindLabel(asset.kind)}）
                    </option>
                  ))}
                </select>
                <select
                  aria-label={`参考用途 ${binding.id}`}
                  value={editPurpose}
                  onChange={(event) => setEditPurpose(event.target.value)}
                >
                  {PURPOSES.map((item) => (
                    <option key={item} value={item}>
                      {purposeLabel(item)}
                    </option>
                  ))}
                </select>
                <select
                  aria-label={`参考方式 ${binding.id}`}
                  value={editMode}
                  onChange={(event) =>
                    setEditMode(
                      event.target.value === "pinned_version" ? "pinned_version" : "current_formal",
                    )
                  }
                >
                  <option value="current_formal">跟随正式版本</option>
                  <option value="pinned_version">固定到当前版本</option>
                </select>
                <button
                  type="button"
                  aria-label={`保存引用 ${binding.id}`}
                  onClick={() => update.mutate(binding)}
                  disabled={update.isPending}
                >
                  保存引用
                </button>
                <button
                  type="button"
                  aria-label={`取消编辑 ${binding.id}`}
                  onClick={() => {
                    setEditingId(null);
                    setEditError(null);
                  }}
                >
                  取消
                </button>
              </div>
            ) : (
              <>
                <span>
                  {binding.label || "（无标签）"} · {purposeLabel(binding.purpose)} ·{" "}
                  {resolutionModeLabel(binding.resolution_mode)}
                </span>
                {resolution.isSuccess && !resolvedBindingIds.has(binding.id) && (
                  <strong
                    className="status-bad"
                    data-testid={`reference-binding-invalid-${binding.id}`}
                  >
                    已失效：解析不到素材
                  </strong>
                )}
                {binding.asset_id && (
                  <details className="editing-diagnostics">
                    <summary>开发 / 诊断详情（只读）</summary>
                    <code>{binding.asset_id}</code>
                  </details>
                )}
                <button
                  type="button"
                  aria-label={`编辑引用 ${binding.label || binding.id}`}
                  onClick={() => startEditing(binding)}
                >
                  修改引用
                </button>
                <button
                  type="button"
                  aria-label={`删除引用 ${binding.label || binding.id}`}
                  onClick={() => remove.mutate(binding.id)}
                  disabled={remove.isPending}
                >
                  删除引用
                </button>
              </>
            )}
          </li>
        ))}
      </ul>

      {invalidBindings.length > 0 && (
        <p className="muted" data-testid="reference-binding-invalid-hint">
          已失效的引用不会进入生成。请更换参考素材，或重新选定版本。
        </p>
      )}

      {resolution.isSuccess && (
        <div className="qc-resolved-references" data-testid="resolved-references">
          <h4>本次生成将使用的参考素材</h4>
          <ul>
            {resolved.map((item, index) => (
              <li key={`${item.artifact_id}-${index}`}>
                <span>
                  {purposeLabel(item.purpose)} ·{" "}
                  {item.source === "pinned_version" ? "固定版本" : "跟随正式版本"}
                </span>
                {item.role ? <small className="muted">{roleLabel(item.role)}</small> : null}
                <details className="editing-diagnostics">
                  <summary>开发 / 诊断详情（只读）</summary>
                  <code>{item.artifact_id}</code>
                </details>
              </li>
            ))}
          </ul>
          {resolved.length === 0 && (
            <p className="muted">
              {rows.length > 0
                ? "已绑定的参考当前解析不到内容：素材换版后没有可用素材，或素材已被回收。请更换参考素材。"
                : "尚未绑定参考素材。"}
            </p>
          )}
        </div>
      )}

      {resolution.isError && (
        <p className="qc-reference-picker-error" role="alert">
          引用解析失败：
          {resolution.error instanceof Error ? resolution.error.message : String(resolution.error)}
        </p>
      )}

      {bindingLabels.length === 0 && <p className="muted">尚未绑定资产引用。</p>}
    </div>
  );
}

/** Convert the server's resolved reference (including concrete artifact id)
 * into the exact WorkbenchExecutionInput shape. */
function toExecutionReference(
  reference: ResolvedReferenceRead,
  bindings: ShotBindingRead[],
): ShotExecutionReference {
  const resolutionMode =
    reference.source === "pinned_version"
      ? "pinned_version"
      : reference.source === "direct_artifact"
        ? "direct_artifact"
        : "current_formal";
  return {
    binding_id: reference.binding_id ?? bindingIdForResolvedReference(reference, bindings),
    purpose: reference.purpose,
    asset_version_id: reference.asset_version_id ?? null,
    artifact_id: reference.artifact_id,
    resolution_mode: resolutionMode,
    mime_type: reference.mime_type || "image/png",
    fingerprint: reference.fingerprint ?? null,
  };
}

function bindingIdForResolvedReference(
  reference: ResolvedReferenceRead,
  bindings: ShotBindingRead[],
): string | null {
  const matching = bindings.find((binding) => {
    if (binding.purpose !== reference.purpose) return false;
    if (reference.source === "direct_artifact") {
      return (
        binding.resolution_mode === "direct_artifact" &&
        binding.artifact_id === reference.artifact_id
      );
    }
    if (reference.source === "pinned_version") {
      return (
        binding.resolution_mode === "pinned_version" &&
        binding.asset_version_id === reference.asset_version_id
      );
    }
    return binding.resolution_mode === "current_formal" && binding.asset_id === reference.asset_id;
  });
  return matching?.id ?? null;
}
