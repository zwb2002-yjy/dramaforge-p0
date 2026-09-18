import { Film, Image, Music2, Package, UserRound, MapPin } from "lucide-react";
import "./asset-gallery.css";
import {
  Button,
  Field,
  Input,
  Select,
  PageHeader,
  Disclosure,
  EmptyState,
  Badge,
} from "../../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useMemo, useState } from "react";

import { apiGetList, type AssetRead } from "../../lib/api";
import {
  ASSET_KIND_LABEL,
  ASSET_STATUS_LABEL,
  assetKindLabel,
  assetStatusLabel,
} from "../../lib/assetLabels";
import { queryKeys } from "../../lib/queryKeys";
import {
  createAssetCandidate,
  fetchAssetCard,
  fetchAssetTags,
  fetchAssetVersions,
  promoteAssetVersion,
  rejectAssetVersion,
  recycleAsset,
  restoreAsset,
  setAssetTags,
} from "./api";

const ROLE_LABEL: Record<string, string> = {
  front_face: "正面",
  three_quarter: "四分之三",
  profile: "侧面",
  half_body: "半身",
  full_body: "全身",
  expression: "表情",
  outfit: "服装",
  layout_reference: "布局",
  lighting_reference: "灯光",
  style_reference: "风格",
  scene_reference: "场景",
};

const VERSION_STATUS_LABEL: Record<string, string> = {
  candidate: "候选",
  formal: "正式",
  historical: "历史",
  rejected: "已拒绝",
};

type AssetCardsPanelProps = {
  projectId: string;
};

function fetchAssetsFiltered(
  projectId: string,
  filters: { kind?: string; status?: string; name?: string; tags?: string },
): Promise<AssetRead[]> {
  const params = new URLSearchParams();
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.status) params.set("status", filters.status);
  if (filters.name) params.set("name", filters.name);
  if (filters.tags) params.set("tags", filters.tags);
  const query = params.toString();
  return apiGetList<AssetRead>(`/api/v1/projects/${projectId}/assets${query ? `?${query}` : ""}`);
}

export function AssetCardsPanel({ projectId }: AssetCardsPanelProps) {
  const queryClient = useQueryClient();
  const [kindFilter, setKindFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [nameFilter, setNameFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);

  const assets = useQuery({
    queryKey: queryKeys.asset.list(projectId, kindFilter, statusFilter, nameFilter, tagFilter),
    queryFn: () =>
      fetchAssetsFiltered(projectId, {
        kind: kindFilter,
        status: statusFilter,
        name: nameFilter,
        tags: tagFilter,
      }),
  });
  const tags = useQuery({
    queryKey: queryKeys.asset.tags(projectId),
    queryFn: () => fetchAssetTags(projectId),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.asset.root(projectId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.asset.tags(projectId) });
  };

  const recycle = useMutation({
    mutationFn: (assetId: string) => recycleAsset(projectId, assetId),
    onSuccess: invalidate,
  });
  const restore = useMutation({
    mutationFn: (assetId: string) => restoreAsset(projectId, assetId),
    onSuccess: invalidate,
  });
  const setTags = useMutation({
    mutationFn: ({ assetId, names }: { assetId: string; names: string[] }) =>
      setAssetTags(projectId, assetId, names),
    onSuccess: invalidate,
  });
  const addCandidate = useMutation({
    mutationFn: ({ assetId, name }: { assetId: string; name: string }) =>
      createAssetCandidate(projectId, assetId, { name }),
    onSuccess: invalidate,
  });
  const promote = useMutation({
    mutationFn: ({ assetId, versionId }: { assetId: string; versionId: string }) =>
      promoteAssetVersion(projectId, assetId, versionId),
    onSuccess: invalidate,
  });
  const reject = useMutation({
    mutationFn: ({ assetId, versionId }: { assetId: string; versionId: string }) =>
      rejectAssetVersion(projectId, assetId, versionId),
    onSuccess: invalidate,
  });

  const tagOptions = useMemo(
    () => (tags.data ?? []).map((tag) => tag.normalized_name),
    [tags.data],
  );
  const rows = assets.data ?? [];

  return (
    <div data-testid="asset-cards-panel" className="qc-project-page">
      <PageHeader
        title="项目资产"
        description="让角色、画面与声音，在这里相遇。"
        actions={<Badge>{assets.isPending ? "读取中…" : `${rows.length} 项素材`}</Badge>}
      />

      <section className="qc-asset-filters" aria-label="筛选资产">
        <Field>
          名称
          <Input
            aria-label="资产名称过滤"
            placeholder="搜索素材名称"
            value={nameFilter}
            onChange={(event) => setNameFilter(event.target.value)}
          />
        </Field>
        <Field>
          类型
          <Select
            aria-label="资产类型过滤"
            value={kindFilter}
            onChange={(event) => setKindFilter(event.target.value)}
          >
            <option value="">全部</option>
            {Object.entries(ASSET_KIND_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field>
          状态
          <Select
            aria-label="资产状态过滤"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">全部</option>
            {Object.entries(ASSET_STATUS_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field>
          标签
          <Input
            aria-label="资产标签过滤"
            value={tagFilter}
            onChange={(event) => setTagFilter(event.target.value)}
            placeholder="主角,雨夜"
          />
        </Field>
      </section>

      {(recycle.isError || restore.isError) && (
        <p role="alert" className="flash err">
          操作失败，请稍后重试。
        </p>
      )}
      {assets.isError && <div className="flash err">无法读取资产：{String(assets.error)}</div>}

      <ul className="qc-asset-grid">
        {rows.map((asset) => (
          <li key={asset.id} className="qc-asset-card" data-testid="asset-card">
            <AssetCover kind={asset.kind} />
            <div className="qc-asset-card-body">
              <header>
                <strong>{asset.name}</strong>
                <span>
                  {assetKindLabel(asset.kind)} · 第 {asset.version} 版
                </span>
              </header>
              {asset.description && <p className="qc-asset-description">{asset.description}</p>}
              {asset.tags?.length > 0 && (
                <div className="qc-asset-tags">
                  {asset.tags.map((tag) => (
                    <Badge key={tag}>{tag}</Badge>
                  ))}
                </div>
              )}
              <footer>
                <span
                  className={`qc-asset-status ${asset.status}`}
                  data-status={asset.status}
                  title={assetStatusLabel(asset.status)}
                >
                  {assetStatusLabel(asset.status)}
                </span>
                <Disclosure title="管理素材">
                  <TagEditor
                    options={tagOptions}
                    onSave={(names) => setTags.mutateAsync({ assetId: asset.id, names })}
                  />
                  {asset.status === "recycled" ? (
                    <Button
                      type="button"
                      onClick={() => {
                        restore.mutate(asset.id, {
                          onSuccess: () => setFeedback(`已恢复「${asset.name}」。`),
                        });
                      }}
                    >
                      恢复
                    </Button>
                  ) : (
                    <Button
                      type="button"
                      onClick={() => {
                        if (
                          !window.confirm(
                            `回收「${asset.name}」？回收后资产不再出现在正式选择中，可在本页“恢复”。`,
                          )
                        ) {
                          return;
                        }
                        recycle.mutate(asset.id, {
                          onSuccess: () => setFeedback(`已回收「${asset.name}」，可在本页恢复。`),
                        });
                      }}
                    >
                      回收
                    </Button>
                  )}
                  <VersionControls
                    asset={asset}
                    projectId={projectId}
                    onAddCandidate={(name) => addCandidate.mutate({ assetId: asset.id, name })}
                    onPromote={(versionId) => promote.mutate({ assetId: asset.id, versionId })}
                    onReject={(versionId) => reject.mutate({ assetId: asset.id, versionId })}
                  />
                </Disclosure>
              </footer>
            </div>
          </li>
        ))}
      </ul>
      {assets.isPending && (
        <p role="status" className="muted">
          正在整理素材…
        </p>
      )}
      {!assets.isPending && !assets.isError && rows.length === 0 && (
        <EmptyState
          icon={<Package />}
          title={
            kindFilter || statusFilter || nameFilter || tagFilter
              ? "没有找到匹配的素材"
              : "故事的素材，从这里积累"
          }
          description={
            kindFilter || statusFilter || nameFilter || tagFilter
              ? "试试其他名称或筛选条件。"
              : "把生成结果“加入资产”后，就能在这里整理和复用。"
          }
        >
          {(kindFilter || statusFilter || nameFilter || tagFilter) && (
            <Button
              onClick={() => {
                setKindFilter("");
                setStatusFilter("");
                setNameFilter("");
                setTagFilter("");
              }}
            >
              清除筛选
            </Button>
          )}
        </EmptyState>
      )}
      {feedback && (
        <p className="flash ok" role="status">
          {feedback}
        </p>
      )}
    </div>
  );
}

function AssetCover({ kind }: { kind: string }) {
  const Icon =
    kind === "video"
      ? Film
      : kind === "image"
        ? Image
        : kind === "audio"
          ? Music2
          : kind === "character"
            ? UserRound
            : kind === "scene"
              ? MapPin
              : Package;
  return (
    <div
      className="qc-asset-cover"
      data-kind={kind}
      aria-label={assetKindLabel(kind) + "素材类型封面"}
    >
      <Icon aria-hidden="true" />
      <span>{assetKindLabel(kind)}</span>
    </div>
  );
}

function TagEditor({
  options,
  onSave,
}: {
  options: string[];
  onSave: (names: string[]) => Promise<unknown>;
}) {
  const listId = useId();
  const [value, setValue] = useState("");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const names = value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
        if (names.length === 0) return;
        setState("saving");
        void onSave(names)
          .then(() => {
            setValue("");
            setState("saved");
          })
          .catch(() => setState("error"));
      }}
    >
      <Input
        aria-describedby={state === "error" ? `${listId}-error` : undefined}
        aria-invalid={state === "error" || undefined}
        aria-label="资产标签"
        list={listId}
        disabled={state === "saving"}
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setState("idle");
        }}
        placeholder={
          state === "saved"
            ? "标签已保存"
            : state === "error"
              ? "标签保存失败"
              : state === "saving"
                ? "正在保存…"
                : "输入标签"
        }
      />
      <datalist id={listId}>
        {options.map((option) => (
          <option key={option} value={option} />
        ))}
      </datalist>
      <Button type="submit" disabled={state === "saving" || !value.trim()}>
        保存
      </Button>
      {state === "error" && (
        <span id={`${listId}-error`} className="qc-asset-tag-message" role="alert">
          标签保存失败，输入已保留。
        </span>
      )}
    </form>
  );
}

function VersionControls({
  asset,
  projectId,
  onAddCandidate,
  onPromote,
  onReject,
}: {
  asset: AssetRead;
  projectId: string;
  onAddCandidate: (name: string) => void;
  onPromote: (versionId: string) => void;
  onReject: (versionId: string) => void;
}) {
  const [showVersions, setShowVersions] = useState(false);
  const [candidateName, setCandidateName] = useState("");
  const versions = useQuery({
    queryKey: queryKeys.asset.versions(projectId, asset.id),
    queryFn: () => fetchAssetVersions(projectId, asset.id),
    enabled: showVersions,
  });
  const card = useQuery({
    queryKey: queryKeys.asset.card(projectId, asset.id),
    queryFn: () => fetchAssetCard(projectId, asset.id),
    enabled: showVersions,
  });
  const rows = versions.data ?? [];
  return (
    <div>
      <Button
        type="button"
        aria-expanded={showVersions}
        onClick={() => setShowVersions((value) => !value)}
      >
        {showVersions ? "收起版本" : "版本"}
      </Button>
      {showVersions && (
        <div className="qc-asset-versions">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!candidateName.trim()) return;
              onAddCandidate(candidateName.trim());
              setCandidateName("");
            }}
          >
            <Input
              aria-label="候选版本名称"
              value={candidateName}
              onChange={(event) => setCandidateName(event.target.value)}
              placeholder="新候选版本名称"
            />
            <Button type="submit">创建候选</Button>
          </form>
          <ul>
            {rows.map((version) => (
              <li key={version.id}>
                <span>
                  v{version.version_number} · {version.name} ·{" "}
                  {VERSION_STATUS_LABEL[version.status] ?? version.status}
                </span>
                {version.status === "candidate" && (
                  <>
                    <Button
                      type="button"
                      data-testid="asset-version-promote"
                      onClick={() => onPromote(version.id)}
                    >
                      提升为正式
                    </Button>
                    <Button
                      type="button"
                      className="ghost danger"
                      data-testid="asset-version-reject"
                      onClick={() => onReject(version.id)}
                    >
                      拒绝候选
                    </Button>
                  </>
                )}
              </li>
            ))}
          </ul>
          {card.data?.missing_reference_roles?.length ? (
            <p className="muted" data-testid="asset-missing-roles">
              缺失：
              {card.data.missing_reference_roles
                .map((role) => ROLE_LABEL[role] ?? role)
                .join(" / ")}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}
