import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { apiGet, type AssetRead } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import {
  createAssetCandidate,
  fetchAssetCard,
  fetchAssetTags,
  fetchAssetVersions,
  promoteAssetVersion,
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

const ASSET_KIND_LABEL: Record<string, string> = {
  character: "角色",
  scene: "场景",
  costume: "服装",
  prop: "道具",
  action: "动作",
  expression: "表情",
  audio: "音频",
  prompt: "提示词方案",
};

const ASSET_STATUS_LABEL: Record<string, string> = {
  active: "已启用",
  draft: "草稿",
  recycled: "已回收",
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
  return apiGet<AssetRead[]>(`/api/v1/projects/${projectId}/assets${query ? `?${query}` : ""}`);
}

export function AssetCardsPanel({ projectId }: AssetCardsPanelProps) {
  const queryClient = useQueryClient();
  const [kindFilter, setKindFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [nameFilter, setNameFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");

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

  const tagOptions = useMemo(
    () => (tags.data ?? []).map((tag) => tag.normalized_name),
    [tags.data],
  );
  const rows = assets.data ?? [];

  return (
    <div data-testid="asset-cards-panel" className="qc-project-page">
      <header className="qc-page-heading">
        <p>资产</p>
        <h1>项目资产</h1>
        <span>管理版本、标签与正式提升；生成结果需显式加入资产。</span>
      </header>

      <section className="qc-asset-filters">
        <label>
          名称
          <input
            aria-label="资产名称过滤"
            value={nameFilter}
            onChange={(event) => setNameFilter(event.target.value)}
          />
        </label>
        <label>
          类型
          <select
            aria-label="资产类型过滤"
            value={kindFilter}
            onChange={(event) => setKindFilter(event.target.value)}
          >
            <option value="">全部</option>
            <option value="character">角色</option>
            <option value="scene">场景</option>
            <option value="costume">服装</option>
            <option value="prop">道具</option>
            <option value="action">动作</option>
            <option value="expression">表情</option>
            <option value="audio">音频</option>
            <option value="prompt">提示词方案</option>
          </select>
        </label>
        <label>
          状态
          <select
            aria-label="资产状态过滤"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">全部</option>
            <option value="active">active</option>
            <option value="draft">draft</option>
            <option value="recycled">recycled</option>
          </select>
        </label>
        <label>
          标签
          <input
            aria-label="资产标签过滤"
            value={tagFilter}
            onChange={(event) => setTagFilter(event.target.value)}
            placeholder="主角,雨夜"
          />
        </label>
      </section>

      {assets.isError && <div className="flash err">无法读取资产：{String(assets.error)}</div>}

      <ul className="qc-asset-grid">
        {rows.map((asset) => (
          <li key={asset.id} className="qc-asset-card" data-testid="asset-card">
            <header>
              <strong>{asset.name}</strong>
              <span>
                {ASSET_KIND_LABEL[asset.kind] ?? asset.kind} · v{asset.version}
              </span>
            </header>
            <p className="muted">{asset.description || "（无描述）"}</p>
            <footer>
              <span
                className={`qc-asset-status ${asset.status}`}
                data-status={asset.status}
                title={asset.status}
              >
                {ASSET_STATUS_LABEL[asset.status] ?? asset.status}
              </span>
              <TagEditor
                options={tagOptions}
                onSave={(names) => setTags.mutate({ assetId: asset.id, names })}
              />
              {asset.status === "recycled" ? (
                <button type="button" onClick={() => restore.mutate(asset.id)}>
                  恢复
                </button>
              ) : (
                <button type="button" onClick={() => recycle.mutate(asset.id)}>
                  回收
                </button>
              )}
              <VersionControls
                asset={asset}
                projectId={projectId}
                onAddCandidate={(name) => addCandidate.mutate({ assetId: asset.id, name })}
                onPromote={(versionId) => promote.mutate({ assetId: asset.id, versionId })}
              />
            </footer>
          </li>
        ))}
      </ul>
      {rows.length === 0 && (
        <p className="muted">暂无资产。生成结果需显式“加入资产”才会出现在这里。</p>
      )}
    </div>
  );
}

function TagEditor({ options, onSave }: { options: string[]; onSave: (names: string[]) => void }) {
  const [value, setValue] = useState("");
  const [saved, setSaved] = useState(false);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        const names = value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
        if (names.length === 0) return;
        onSave(names);
        setSaved(true);
        setTimeout(() => setSaved(false), 1500);
        setValue("");
      }}
    >
      <input
        aria-label="资产标签"
        list="asset-tag-options"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={saved ? "标签已保存" : "输入标签"}
      />
      <datalist id="asset-tag-options">
        {options.map((option) => (
          <option key={option} value={option} />
        ))}
      </datalist>
      <button type="submit">保存</button>
    </form>
  );
}

function VersionControls({
  asset,
  projectId,
  onAddCandidate,
  onPromote,
}: {
  asset: AssetRead;
  projectId: string;
  onAddCandidate: (name: string) => void;
  onPromote: (versionId: string) => void;
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
      <button type="button" onClick={() => setShowVersions((value) => !value)}>
        {showVersions ? "收起版本" : "版本"}
      </button>
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
            <input
              aria-label="候选版本名称"
              value={candidateName}
              onChange={(event) => setCandidateName(event.target.value)}
              placeholder="新候选版本名称"
            />
            <button type="submit">创建候选</button>
          </form>
          <ul>
            {rows.map((version) => (
              <li key={version.id}>
                <span>
                  v{version.version_number} · {version.name} · {version.status}
                </span>
                {version.status === "candidate" && (
                  <button type="button" onClick={() => onPromote(version.id)}>
                    提升为正式
                  </button>
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
