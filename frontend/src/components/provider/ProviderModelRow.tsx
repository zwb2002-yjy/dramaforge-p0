import { Image, Video } from "lucide-react";
import type { ReactNode } from "react";

import type { ProviderModelBindingRead, ProviderPluginRead } from "../../lib/api";
import { Badge, Disclosure } from "../ui";
import { modelInputSummary, providerConnectionCopy as copy } from "./providerConnectionCopy";

export function ProviderModelRow({
  binding,
  model,
  action,
  children,
}: {
  binding: ProviderModelBindingRead;
  model: ProviderPluginRead["models"][number] | null;
  action: ReactNode;
  children: ReactNode;
}) {
  const status = !binding.enabled
    ? copy.disabled
    : !model
      ? copy.unavailable
      : !binding.account_verified
        ? copy.unverified
        : copy.configured;
  const MediaIcon = binding.media_type === "image" ? Image : Video;
  const name = model?.display_name ?? "历史合同";
  return (
    <div className="provider-binding" data-testid={`provider-model-${binding.id}`}>
      <div className="provider-model-line">
        <span
          className="provider-model-kind"
          title={binding.media_type === "image" ? copy.image : copy.video}
        >
          <MediaIcon size={18} aria-hidden="true" />
        </span>
        <div className="provider-model-name" title={binding.model_id}>
          <strong>{name}</strong>
          {model && <span className="muted">{model.model_revision}</span>}
        </div>
        <Badge tone={status === copy.configured ? "default" : "warning"}>{status}</Badge>
        {action}
      </div>
      <Disclosure title={copy.details} testId={`provider-model-details-${binding.id}`}>
        <dl className="provider-model-metadata">
          <dt>模型 ID</dt>
          <dd>
            <code>{binding.model_id}</code>
          </dd>
          <dt>输入</dt>
          <dd>{model ? modelInputSummary(model.capabilities) : "未知"}</dd>
          <dt>配置 ID</dt>
          <dd>
            <code>{binding.id}</code>
          </dd>
        </dl>
        <div className="provider-binding-states" data-testid={`binding-states-${binding.purpose}`}>
          {(
            [
              ["documented", "文档", binding.documented],
              ["contract_tested", "协议", binding.contract_tested],
              ["account_verified", "目录", binding.account_verified],
              ["quality_gated", "质量", binding.quality_gated],
            ] as const
          ).map(([key, label, passed]) => (
            <span
              key={key}
              className={`evidence-state ${passed ? "passed" : "pending"}`}
              data-testid={`binding-${binding.purpose}-${key}`}
            >
              {label}：{passed ? "通过" : "未验证"}
            </span>
          ))}
        </div>
        {children}
      </Disclosure>
    </div>
  );
}
