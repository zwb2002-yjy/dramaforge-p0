import { ApiError } from "../../lib/api";
import type {
  ProviderConnectionRead,
  ProviderModelBindingRead,
  ProviderPluginModelRead,
  ProviderPluginRead,
  ProviderProbeRead,
} from "../../lib/api";

export type MediaKind = "image" | "video";

export function pluginKey(plugin: { provider_type: string; protocol_profile: string }): string {
  return `${plugin.provider_type}/${plugin.protocol_profile}`;
}

/** Presentation names keep native cloud APIs separate from compatible endpoints. */
export function providerLabel(plugin: ProviderPluginRead): string {
  if (plugin.provider_type === "agnes") return "Agnes";
  if (plugin.provider_type === "minimax") return "MiniMax";
  if (plugin.provider_type === "volcengine") return "Seedance";
  if (plugin.provider_type === "openai_compatible_media") return "自定义供应商";
  if (plugin.kind === "text") return "文本服务";
  return plugin.display_name;
}

export function isLocalServiceUrl(value: string): boolean {
  try {
    const host = new URL(value).hostname.toLowerCase();
    if (
      host === "localhost" ||
      host === "[::1]" ||
      host.endsWith(".local") ||
      host.endsWith(".internal")
    )
      return true;
    const parts = host.split(".").map(Number);
    if (
      parts.length !== 4 ||
      parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255)
    )
      return false;
    return (
      parts[0] === 10 ||
      parts[0] === 127 ||
      (parts[0] === 192 && parts[1] === 168) ||
      (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31)
    );
  } catch {
    return false;
  }
}

export function pluginFor(
  plugins: ProviderPluginRead[] | undefined,
  connection: ProviderConnectionRead,
): ProviderPluginRead | undefined {
  return plugins?.find((plugin) => pluginKey(plugin) === pluginKey(connection));
}

export type StatusTone = "ok" | "warn" | "err" | "idle";

/** One short status per connection; the backend projection is the only source. */
export function connectionStatus(connection: ProviderConnectionRead): {
  tone: StatusTone;
  label: string;
} {
  if (!connection.enabled) return { tone: "idle", label: "已停用" };
  if (!connection.credential_configured) return { tone: "warn", label: "缺少 Key" };
  if (connection.verification_status === "failed") return { tone: "err", label: "认证失败" };
  if (connection.verification_status === "verified") return { tone: "ok", label: "已连接" };
  return { tone: "warn", label: "待验证" };
}

/** Passed discovery belongs to the current endpoint and credential revision. */
export function latestCatalogRead(
  probes: ProviderProbeRead[] | undefined,
  connection: ProviderConnectionRead,
): ProviderProbeRead | null {
  if (connection.verification_status !== "verified" || !connection.connection_revision_id)
    return null;
  return (
    probes?.find(
      (probe) =>
        probe.capability === "auth_models" &&
        probe.status === "passed" &&
        probe.connection_revision_id === connection.connection_revision_id,
    ) ?? null
  );
}

/** Explain a failed catalog read without calling every failure a bad key. */
export function catalogFailureText(probe: Pick<ProviderProbeRead, "http_status" | "error_code">) {
  if (probe.http_status === 401 || probe.http_status === 403) {
    return "Key 无效或没有权限，请检查后重试。";
  }
  if (probe.http_status === 404) return "该地址没有模型目录接口，请检查服务地址。";
  if (probe.http_status === 429) return "供应商限流，请稍后再试。";
  if (probe.http_status && probe.http_status >= 500) return "供应商服务暂时不可用，请稍后再试。";
  return probe.error_code
    ? `无法读取模型目录（${probe.error_code}）。`
    : "无法连接服务，请检查地址与网络。";
}

/** Newest active revision of each catalog contract, keyed by contract model id. */
export function activeContracts(plugin: ProviderPluginRead): ProviderPluginModelRead[] {
  const revisions = new Intl.Collator(undefined, { numeric: true });
  const latest = new Map<string, ProviderPluginModelRead>();
  for (const model of plugin.models) {
    if (model.lifecycle !== "active") continue;
    const key = `${model.media_type}:${model.model_id}`;
    const previous = latest.get(key);
    if (!previous || revisions.compare(model.model_revision, previous.model_revision) > 0) {
      latest.set(key, model);
    }
  }
  return [...latest.values()];
}

/** Protocol contracts that an explicitly chosen remote model id may use. */
export function protocolContracts(plugin: ProviderPluginRead): ProviderPluginModelRead[] {
  return activeContracts(plugin).filter((model) => model.model_id.startsWith("@contract/"));
}

export type DiscoveredModel = {
  modelId: string;
  /** Exact catalog contracts for this id, one per media kind. */
  exact: ProviderPluginModelRead[];
};

/**
 * Pair discovered remote ids with catalog contracts. Only an exact contract id
 * is matched automatically; names are never used to guess capabilities.
 * Without any discovery the official catalog ids are offered as candidates.
 */
export function discoveredModels(
  plugin: ProviderPluginRead,
  discoveredIds: readonly string[] | null,
): DiscoveredModel[] {
  const contracts = activeContracts(plugin).filter(
    (model) => !model.model_id.startsWith("@contract/"),
  );
  const ids = discoveredIds?.length
    ? [...new Set(discoveredIds)]
    : [...new Set(contracts.map((model) => model.model_id))];
  return ids
    .map((modelId) => ({
      modelId,
      exact: contracts.filter((model) => model.model_id === modelId),
    }))
    .sort((left, right) => {
      if (left.exact.length !== right.exact.length) return left.exact.length ? -1 : 1;
      return left.modelId.localeCompare(right.modelId);
    });
}

export type ModelChoice = {
  modelId: string;
  mediaType: MediaKind;
  contractId: string;
};

export function choiceKey(choice: Pick<ModelChoice, "modelId" | "mediaType">): string {
  return `${choice.mediaType}:${choice.modelId}`;
}

export function bindingChoiceKey(binding: ProviderModelBindingRead): string {
  return contractChoiceKey({
    mediaType: binding.media_type as MediaKind,
    modelId: binding.model_id,
    contractId: binding.catalog_entry_id ?? "",
  });
}

/** A remote id can have different immutable capability contract revisions. */
export function contractChoiceKey(choice: ModelChoice): string {
  return `${choiceKey(choice)}:${choice.contractId}`;
}

export const MEDIA_LABEL: Record<MediaKind, string> = { image: "图片", video: "视频" };

export function probeErrorText(cause: unknown): string {
  if (cause instanceof ApiError) {
    const code = String(cause.details.code ?? cause.code);
    if (code === "PROBE_RATE_LIMITED") return "刚刚读取过，请等待 30 秒后再试。";
    if (code === "PROVIDER_CONNECTION_DISABLED") return "连接已停用，请先启用。";
  }
  return cause instanceof Error ? cause.message : "操作未完成，请重试。";
}
