import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { fetchProjectAssets } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import {
  createShotReference,
  deleteShotReference,
  fetchShotReferences,
  resolveShotReferences,
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

  const assets = useQuery({
    queryKey: queryKeys.asset.picker(projectId),
    queryFn: () => fetchProjectAssets(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
  });
  const bindings = useQuery({
    queryKey: queryKeys.asset.shotReferences(projectId, shotId),
    queryFn: () => fetchShotReferences(projectId, shotId),
    enabled: Boolean(shotId) && shotId !== "demo",
  });

  // Resolution is a POST in the existing API because it is a server-side
  // binding resolution operation.  Keep it query-backed here so a selected
  // Shot immediately receives its persisted references without requiring a
  // second manual click.
  const resolution = useQuery({
    queryKey: queryKeys.asset.referenceResolution(projectId, shotId),
    queryFn: () => resolveShotReferences(projectId, shotId),
    enabled: Boolean(projectId) && Boolean(shotId) && shotId !== "demo",
  });

  const resolutionQueryKey = queryKeys.asset.referenceResolution(projectId, shotId);

  const clearResolvedReferences = () => {
    setResolvedReferences([]);
    queryClient.setQueryData<ResolvedReferenceRead[] | undefined>(resolutionQueryKey, undefined);
    onReferencesChange?.([]);
  };

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.asset.shotReferences(projectId, shotId) }),
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

  const assetOptions = Array.isArray(assets.data) ? assets.data : [];
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

  function labelFor(assetId: string): string {
    return `@${assetOptions.find((asset) => asset.id === assetId)?.name ?? assetId.slice(0, 8)}`;
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
              {asset.name}（{asset.kind}）
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
              {item}
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

      <ul className="qc-binding-list" data-testid="binding-list">
        {rows.map((binding) => (
          <li key={binding.id}>
            <span>
              {binding.label || "（无标签）"} · {binding.purpose} · {binding.resolution_mode}
            </span>
            {binding.asset_id && <code>{binding.asset_id}</code>}
            <button
              type="button"
              aria-label={`删除引用 ${binding.label || binding.id}`}
              onClick={() => remove.mutate(binding.id)}
              disabled={remove.isPending}
            >
              删除引用
            </button>
          </li>
        ))}
      </ul>

      {resolution.isSuccess && (
        <div className="qc-resolved-references" data-testid="resolved-references">
          <h4>解析结果（冻结为 artifact_id）</h4>
          <ul>
            {resolved.map((item, index) => (
              <li key={`${item.artifact_id}-${index}`}>
                <span>
                  {item.purpose} / {item.role} / {item.source}
                </span>
                <code>{item.artifact_id}</code>
              </li>
            ))}
          </ul>
          {resolved.length === 0 && <p className="muted">当前无已解析引用。</p>}
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
