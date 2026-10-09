import { ApiError, createProviderModelBinding, type ProviderModelBindingRead } from "../../lib/api";
import type { ModelChoice } from "./providerSetup";
import { MEDIA_LABEL } from "./providerSetup";

export type BindingBatchResult = {
  created: ProviderModelBindingRead[];
  failed: Array<{ choice: ModelChoice; message: string }>;
};

/**
 * Create one binding per checked model. Each request is independent; partial
 * success is reported as such and never presented as an all-or-nothing save.
 */
export async function createBindings(
  workspaceId: string,
  connectionId: string,
  choices: ModelChoice[],
): Promise<BindingBatchResult> {
  const result: BindingBatchResult = { created: [], failed: [] };
  for (const choice of choices) {
    try {
      result.created.push(
        await createProviderModelBinding(workspaceId, connectionId, {
          media_type: choice.mediaType,
          model_id: choice.modelId,
          purpose: choice.mediaType === "image" ? "keyframe" : "video",
          capability_contract_id: choice.contractId,
        }),
      );
    } catch (cause) {
      const code = cause instanceof ApiError ? (cause.details.code ?? cause.code) : null;
      if (code === "PROVIDER_MODEL_BINDING_EXISTS") continue;
      result.failed.push({
        choice,
        message:
          code === "MODEL_NOT_DISCOVERED"
            ? "当前目录未返回该模型"
            : cause instanceof Error
              ? cause.message
              : "添加失败",
      });
    }
  }
  return result;
}

export function bindingBatchMessage(result: BindingBatchResult): string | null {
  if (!result.failed.length) return null;
  const names = result.failed
    .map(
      (item) => `${item.choice.modelId}（${MEDIA_LABEL[item.choice.mediaType]}）：${item.message}`,
    )
    .join("；");
  return result.created.length
    ? `已添加 ${result.created.length} 个，${result.failed.length} 个未添加：${names}`
    : `未能添加：${names}`;
}
