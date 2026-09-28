import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  assetKindsForArtifactType,
  createAssetFromArtifact,
  createShotReference,
  roleLabel,
  rolesForAssetKind,
  type AssetRead,
} from "./api";

type AddArtifactToAssetDialogProps = {
  projectId: string;
  /** Immutable Artifact being added; never re-resolved from "current formal". */
  artifactId: string;
  /** Default card name, normally the Shot's character or scene name. */
  defaultName: string;
  /** Asset kind proposed from the artifact type. */
  defaultKind: string;
  /** Media type of the Artifact, which bounds the kinds it may become. */
  artifactType?: string | null;
  /** Human-readable provenance shown before the explicit confirmation. */
  sourceLabel: string;
  /** Shot that may be bound to the new asset version afterwards. */
  shotId?: string | null;
  onCreated?: (asset: AssetRead) => void | Promise<void>;
  onClose: () => void;
};

const KIND_LABELS: Record<string, string> = {
  character: "角色",
  scene: "场景",
  video: "视频",
  audio: "音频",
  subtitle: "字幕",
};

/**
 * Explicit "generated Artifact becomes an Asset" confirmation dialog.
 *
 * Creation is one action; binding the new version to a Shot is a second,
 * separate action. Neither happens on its own.
 */
export function AddArtifactToAssetDialog({
  projectId,
  artifactId,
  defaultName,
  defaultKind,
  artifactType,
  sourceLabel,
  shotId,
  onCreated,
  onClose,
}: AddArtifactToAssetDialogProps) {
  // Only kinds this Artifact may actually become: the server refuses the rest,
  // and a late refusal after an explicit confirmation is a dead end.
  const allowedKinds = assetKindsForArtifactType(artifactType);
  const initialKind = allowedKinds.includes(defaultKind)
    ? defaultKind
    : (allowedKinds[0] ?? defaultKind);
  const [name, setName] = useState(defaultName);
  const [kind, setKind] = useState(initialKind);
  const [referenceRole, setReferenceRole] = useState(
    rolesForAssetKind(initialKind)[0] ?? "primary",
  );
  const [description, setDescription] = useState("");
  const [created, setCreated] = useState<AssetRead | null>(null);
  const [bound, setBound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // One explicit operation keeps one request key across retries; a second,
  // deliberate creation must start a new operation (and a new key).
  const requestKey = useRef(`asset-from-artifact:${globalThis.crypto.randomUUID()}`);

  const createMut = useMutation({
    mutationFn: async () =>
      createAssetFromArtifact(
        projectId,
        {
          kind,
          name: name.trim(),
          artifact_id: artifactId,
          description: description.trim(),
          metadata: { source_artifact_id: artifactId },
          reference_role: referenceRole,
        },
        requestKey.current,
      ),
    onSuccess: async (asset) => {
      setError(null);
      setCreated(asset);
      await onCreated?.(asset);
    },
    onError: (cause: unknown) => {
      setError(cause instanceof Error ? cause.message : String(cause));
    },
  });

  const bindMut = useMutation({
    mutationFn: async (asset: AssetRead) => {
      if (!shotId) throw new Error("请先选择镜头，再绑定资产版本。");
      // Bind the exact Artifact this dialog turned into the asset ("direct
      // artifact"). AssetRead does not carry the current version id, and the
      // browser must not invent one; choosing "current formal" stays a separate
      // action the user can take later from the asset panel.
      return createShotReference(projectId, shotId, {
        purpose: referenceRole,
        asset_id: asset.id,
        artifact_id: artifactId,
        resolution_mode: "direct_artifact",
        label: asset.name,
      });
    },
    onSuccess: () => {
      setError(null);
      setBound(true);
    },
    onError: (cause: unknown) => {
      setError(cause instanceof Error ? cause.message : String(cause));
    },
  });

  return (
    <div className="qc-unsaved-backdrop" data-testid="add-artifact-to-asset-dialog">
      <section
        className="qc-unsaved-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-asset-title"
      >
        <span className="director-stage-kicker">显式动作</span>
        <h2 id="add-asset-title">将生成结果加入资产</h2>
        <p className="muted" data-testid="add-asset-source">
          来源：{sourceLabel} · 素材 {artifactId.slice(0, 8)}
        </p>

        {created ? (
          <div data-testid="add-asset-result" role="status">
            <p>已创建资产「{created.name}」，并将此版本设为正式（v1，status=formal）。</p>
            {shotId ? (
              <button
                type="button"
                data-testid="add-asset-bind-shot"
                disabled={bound || bindMut.isPending}
                onClick={() => bindMut.mutate(created)}
              >
                {bound ? "已绑定到当前镜头" : "绑定到当前镜头"}
              </button>
            ) : (
              <p className="muted">未选择镜头，本次不会自动绑定引用。</p>
            )}
            <div className="qc-unsaved-actions">
              <button type="button" className="secondary" onClick={onClose}>
                完成
              </button>
            </div>
          </div>
        ) : (
          <>
            <label>
              资产名称
              <input
                aria-label="资产名称"
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={createMut.isPending}
              />
            </label>
            <label>
              资产类型
              <select
                aria-label="资产类型"
                value={kind}
                onChange={(event) => {
                  const next = event.target.value;
                  setKind(next);
                  setReferenceRole(rolesForAssetKind(next)[0] ?? "primary");
                }}
                disabled={createMut.isPending}
              >
                {allowedKinds.map((option) => (
                  <option key={option} value={option}>
                    {KIND_LABELS[option] ?? option}
                  </option>
                ))}
              </select>
            </label>
            <label>
              参考角色
              <select
                aria-label="参考角色"
                value={referenceRole}
                onChange={(event) => setReferenceRole(event.target.value)}
                disabled={createMut.isPending}
              >
                {rolesForAssetKind(kind).map((role) => (
                  <option key={role} value={role}>
                    {roleLabel(role)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              说明
              <input
                aria-label="资产说明"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                disabled={createMut.isPending}
              />
            </label>

            {error && (
              <p className="flash err" data-testid="add-asset-error" role="alert">
                {error}
              </p>
            )}

            <div className="qc-unsaved-actions">
              <button type="button" className="secondary" onClick={onClose}>
                取消
              </button>
              <button
                type="button"
                data-testid="add-asset-confirm"
                disabled={createMut.isPending || !name.trim() || !artifactId}
                onClick={() => createMut.mutate()}
              >
                创建资产并将此版本设为正式
              </button>
            </div>
          </>
        )}

        {created && error && (
          <p className="flash err" data-testid="add-asset-error" role="alert">
            {error}
          </p>
        )}
      </section>
    </div>
  );
}
