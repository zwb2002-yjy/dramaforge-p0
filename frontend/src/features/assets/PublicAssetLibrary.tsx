import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Select,
} from "../../components/ui";
import { apiGet, apiSend, fetchCsrf, publicItemContentUrl } from "../../lib/api";
import { assetKindLabel } from "../../lib/assetLabels";
import { queryKeys } from "../../lib/queryKeys";
import type { components } from "../../shared/api/generated";
import "./asset-gallery.css";

type Publication = components["schemas"]["PublicAssetReadModel"];
type Link = components["schemas"]["PublicLinkReadModel"];
type AssetPage = components["schemas"]["PublicAssetPage"];
type LinkPage = components["schemas"]["PublicLinkPage"];
const pageSize = 24;
const statusLabels: Record<string, string> = {
  available: "可引用",
  restricted: "使用受限",
  withdrawn: "已撤回",
};

async function loadLinks(projectId: string, signal: AbortSignal) {
  const links = new Map<string, Link>();
  let offset: number | null = 0;
  while (offset !== null) {
    const page: LinkPage = await apiGet(
      `/api/v1/projects/${projectId}/public-asset-links?active=false&limit=100&offset=${offset}`,
      undefined,
      signal,
    );
    for (const link of page.items) links.set(link.publication_id, link);
    offset = page.next_offset;
  }
  return links;
}

function MediaPreview({ publication }: { publication: Publication }) {
  const [failed, setFailed] = useState<string[]>([]);
  return publication.items
    .filter((item) => item.preview_available)
    .map((item) => {
      const url = publicItemContentUrl(publication.id, item.id);
      const onError = () => setFailed((ids) => [...ids, item.id]);
      if (failed.includes(item.id))
        return (
          <p key={item.id} role="status">
            此项素材当前无法预览
          </p>
        );
      if (item.media_kind === "image")
        return (
          <img
            className="qc-public-preview"
            key={item.id}
            src={url}
            alt={publication.safe_name}
            onError={onError}
          />
        );
      if (item.media_kind === "video")
        return (
          <video
            className="qc-public-preview"
            key={item.id}
            src={url}
            controls
            preload="metadata"
            aria-label={publication.safe_name}
            onError={onError}
          />
        );
      if (item.media_kind === "audio")
        return (
          <audio
            className="qc-public-preview"
            key={item.id}
            src={url}
            controls
            preload="metadata"
            aria-label={publication.safe_name}
            onError={onError}
          />
        );
      return <p key={item.id}>此格式没有内嵌预览</p>;
    });
}

export function PublicAssetLibrary({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [opened, setOpened] = useState<string | null>(null);
  const queryKey = queryKeys.asset.publicLibrary(projectId, q, status, offset);
  const linksKey = queryKeys.asset.publicLinks(projectId);
  const library = useQuery({
    queryKey,
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ q, limit: String(pageSize), offset: String(offset) });
      if (status) params.set("status", status);
      return apiGet<AssetPage>(`/api/v1/public-assets?${params}`, undefined, signal);
    },
  });
  const links = useQuery({
    queryKey: linksKey,
    queryFn: ({ signal }) => loadLinks(projectId, signal),
  });
  const change = useMutation({
    mutationFn: async ({ asset, link }: { asset: Publication; link: Link | undefined }) => {
      const base = `/api/v1/projects/${projectId}/public-asset-links`;
      const csrf = await fetchCsrf();
      return link
        ? apiSend<Link>(
            "PATCH",
            `${base}/${link.id}`,
            { expected_version: link.version, attached: Boolean(link.detached_at) },
            csrf,
          )
        : apiSend<Link>(
            "POST",
            base,
            {
              publication_id: asset.id,
              local_label: asset.safe_name,
              request_key: `library-${asset.id}`,
            },
            csrf,
          );
    },
    onSettled: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: linksKey }),
        client.invalidateQueries({ queryKey: ["public-library", projectId] }),
      ]),
  });
  return (
    <section aria-label="公共资产">
      <PageHeader title="公共资产" description="从已发布的素材中选取固定版本，在当前项目中引用。" />
      <div className="qc-asset-filters">
        <Field>
          名称或描述
          <Input
            value={q}
            maxLength={200}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </Field>
        <Field>
          使用状态
          <Select
            value={status}
            onChange={(value) => {
              setStatus(value);
              setOffset(0);
            }}
          >
            <option value="">全部</option>
            {Object.entries(statusLabels).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {library.isPending && <p role="status">正在读取公共资产…</p>}
      {(library.isError || links.isError || change.isError) && (
        <Alert
          type="error"
          role="alert"
          showIcon
          description={String(library.error ?? links.error ?? change.error)}
        />
      )}
      {library.data?.items.length === 0 && (
        <EmptyState title={q || status ? "没有匹配的公共资产" : "尚无已发布的公共资产"} />
      )}
      <ul className="qc-asset-grid">
        {library.data?.items.map((asset) => {
          const link = links.data?.get(asset.id);
          const attached = Boolean(link && !link.detached_at);
          return (
            <li className="qc-asset-card" key={asset.id}>
              <div className="qc-asset-card-body">
                <header>
                  <strong>{asset.safe_name}</strong>
                  <span>
                    {assetKindLabel(asset.kind)} · {statusLabels[asset.status] ?? asset.status}
                  </span>
                </header>
                {asset.safe_description && <p>{asset.safe_description}</p>}
                {attached && <Badge>当前项目已引用</Badge>}
                {asset.usable && (
                  <Button onClick={() => setOpened(opened === asset.id ? null : asset.id)}>
                    {opened === asset.id ? "收起预览" : "预览素材"}
                  </Button>
                )}
                {asset.usable && opened === asset.id && <MediaPreview publication={asset} />}
                <Button
                  disabled={!links.isSuccess || change.isPending || (!attached && !asset.usable)}
                  onClick={() => change.mutate({ asset, link })}
                >
                  {attached ? "解除项目引用" : link ? "重新引用到项目" : "引用到当前项目"}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      {(offset > 0 || library.data?.next_offset != null) && (
        <nav aria-label="公共资产分页">
          <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - pageSize))}>
            上一页
          </Button>
          <Button
            disabled={library.data?.next_offset == null}
            onClick={() => {
              if (library.data?.next_offset != null) setOffset(library.data.next_offset);
            }}
          >
            下一页
          </Button>
        </nav>
      )}
    </section>
  );
}
