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

/** The latest passed catalog read for the connection, if any. */
export function latestCatalogRead(
  probes: ProviderProbeRead[] | undefined,
): ProviderProbeRead | null {
  return (
    probes?.find((probe) => probe.capability === "auth_models" && probe.status === "passed") ?? null
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
  return `${binding.media_type}:${binding.model_id}`;
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
