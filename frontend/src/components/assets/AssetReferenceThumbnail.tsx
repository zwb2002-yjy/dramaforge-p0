import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ASSET_KIND_ROLES, fetchAssetCard } from "../../features/assets/api";
import { artifactContentUrl } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";

/** Presentation of an exact resolved image; it never changes the selected reference. */
export function AssetReferenceThumbnail({
  projectId,
  artifactId,
  label,
}: {
  projectId: string;
  artifactId?: string;
  label: string;
}) {
  const [failedSource, setFailedSource] = useState<string | null>(null);
  const source = artifactId ? artifactContentUrl(projectId, artifactId) : null;
  const visible = source && failedSource !== source;
  return (
    <span className="df-ref-avatar" title={visible ? label : `${label}：暂无可预览图片`}>
      {visible ? (
        <img
          src={source}
          alt={`${label}参考图`}
          loading="lazy"
          onError={() => setFailedSource(source)}
        />
      ) : (
        <span aria-hidden="true">{label.replace(/^@/, "").slice(0, 1) || "·"}</span>
      )}
    </span>
  );
}

/** Mounted only for the bounded visible suggestion list; reads the current Formal card. */
export function FormalAssetThumbnail({
  projectId,
  assetId,
  label,
}: {
  projectId: string;
  assetId: string;
  label: string;
}) {
  const card = useQuery({
    queryKey: queryKeys.asset.card(projectId, assetId),
    queryFn: () => fetchAssetCard(projectId, assetId),
  }).data;
  // Character/scene roles explicitly describe image references. Generic "primary"
  // may be audio or video and is not sufficient evidence to display an image.
  const imageRoles = card ? ASSET_KIND_ROLES[card.kind] : undefined;
  const reference =
    card?.project_id === projectId &&
    card.asset_id === assetId &&
    card.status !== "recycled" &&
    card.current_version_id &&
    card.current_version_status === "formal" &&
    imageRoles
      ? [...card.references]
          .filter(
            (item) =>
              typeof item.reference_role === "string" &&
              imageRoles.includes(item.reference_role) &&
              typeof item.artifact_id === "string" &&
              /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(item.artifact_id),
          )
          .sort(
            (a, b) =>
              Number(a.sort_order ?? 0) - Number(b.sort_order ?? 0) ||
              String(a.label ?? "").localeCompare(String(b.label ?? "")) ||
              String(a.artifact_id).localeCompare(String(b.artifact_id)),
          )[0]
      : undefined;
  return (
    <AssetReferenceThumbnail
      projectId={projectId}
      artifactId={typeof reference?.artifact_id === "string" ? reference.artifact_id : undefined}
      label={label}
    />
  );
}
