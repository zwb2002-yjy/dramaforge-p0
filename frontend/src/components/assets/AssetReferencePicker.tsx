import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchProjectAssets } from "../../lib/api";
import {
  createShotReference,
  fetchShotReferences,
  resolveShotReferences,
  type ResolvedReferenceRead,
} from "../../features/assets/api";

type AssetReferencePickerProps = {
  projectId: string;
  shotId: string;
  purpose?: string;
};

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
 * Phase 2 shot reference picker: shows the shot's business-purpose bindings and
 * lets the user bind an Asset (current_formal). Resolution output is shown
 * after the user asks to resolve.
 */
export function AssetReferencePicker({ projectId, shotId, purpose = "identity" }: AssetReferencePickerProps) {
  const queryClient = useQueryClient();
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [selectedPurpose, setSelectedPurpose] = useState<string>(purpose);

  const assets = useQuery({
    queryKey: ["picker-assets", projectId],
    queryFn: () => fetchProjectAssets(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
  });
  const bindings = useQuery({
    queryKey: ["shot-references", projectId, shotId],
    queryFn: () => fetchShotReferences(projectId, shotId),
    enabled: Boolean(shotId) && shotId !== "demo",
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["shot-references", projectId, shotId] });
  };

  const create = useMutation({
    mutationFn: () =>
      createShotReference(projectId, shotId, {
        purpose: selectedPurpose,
        asset_id: selectedAssetId || null,
        resolution_mode: "current_formal",
        label: selectedAssetId ? labelFor(selectedAssetId) : "",
      }),
    onSuccess: invalidate,
  });

  const resolve = useMutation({
    mutationFn: () => resolveShotReferences(projectId, shotId),
  });

  const assetOptions = assets.data ?? [];
  const rows = bindings.data ?? [];
  const resolved = (resolve.data ?? []) as ResolvedReferenceRead[];

  function labelFor(assetId: string): string {
    return `@${assetOptions.find((asset) => asset.id === assetId)?.name ?? assetId.slice(0, 8)}`;
  }

  const bindingLabels = rows.map((binding) => binding.label);

  return (
    <div className="qc-reference-picker" data-testid="asset-reference-picker">
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
        <button type="button" onClick={() => resolve.mutate()} disabled={resolve.isPending}>
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
          </li>
        ))}
      </ul>

      {resolve.isSuccess && (
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

      {bindingLabels.length === 0 && <p className="muted">尚未绑定资产引用。</p>}
    </div>
  );
}
