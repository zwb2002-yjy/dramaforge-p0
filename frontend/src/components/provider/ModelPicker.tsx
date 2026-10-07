import { useMemo, useState } from "react";

import type { ProviderPluginModelRead, ProviderPluginRead } from "../../lib/api";
import { Checkbox, Disclosure, Field, Input, Select } from "../ui";
import {
  MEDIA_LABEL,
  choiceKey,
  discoveredModels,
  protocolContracts,
  type MediaKind,
  type ModelChoice,
} from "./providerSetup";

type Row = {
  key: string;
  modelId: string;
  mediaType: MediaKind;
  contract: ProviderPluginModelRead;
};

/**
 * Check the models to use from one connection. Exact catalog contracts are
 * offered directly; other discovered ids need an explicit protocol contract or
 * stay "已发现 · 暂未支持执行". Nothing is inferred from model names.
 */
export function ModelPicker({
  plugin,
  discoveredIds,
  existingKeys,
  value,
  onChange,
  disabled = false,
}: {
  plugin: ProviderPluginRead;
  discoveredIds: readonly string[] | null;
  existingKeys: ReadonlySet<string>;
  value: ReadonlyMap<string, ModelChoice>;
  onChange: (next: Map<string, ModelChoice>) => void;
  disabled?: boolean;
}) {
  const [filter, setFilter] = useState("");
  const [mapped, setMapped] = useState<Record<string, string>>({});
  const discovered = useMemo(
    () => discoveredModels(plugin, discoveredIds),
    [plugin, discoveredIds],
  );
  const protocols = useMemo(() => protocolContracts(plugin), [plugin]);
  const needle = filter.trim().toLocaleLowerCase();
  const visible = (id: string) => !needle || id.toLocaleLowerCase().includes(needle);

  const rows: Row[] = discovered.flatMap((model) =>
    model.exact.map((contract) => ({
      key: choiceKey({ modelId: model.modelId, mediaType: contract.media_type as MediaKind }),
      modelId: model.modelId,
      mediaType: contract.media_type as MediaKind,
      contract,
    })),
  );
  const unmatched = discovered.filter((model) => !model.exact.length).map((model) => model.modelId);

  const toggle = (choice: ModelChoice, checked: boolean) => {
    const next = new Map(value);
    if (checked) next.set(choiceKey(choice), choice);
    else next.delete(choiceKey(choice));
    onChange(next);
  };

  const renderRow = (row: Row) => {
    const added = existingKeys.has(row.key);
    return (
      <li key={row.key} className={added ? "added" : undefined}>
        <Field className="df-model-check">
          <Checkbox
            checked={added || value.has(row.key)}
            disabled={disabled || added}
            onChange={(event) =>
              toggle(
                {
                  modelId: row.modelId,
                  mediaType: row.mediaType,
                  contractId: row.contract.catalog_entry_id,
                },
                event.target.checked,
              )
            }
          />
          <span className="df-model-name">
            <strong>{row.contract.display_name}</strong>
            <code>{row.modelId}</code>
          </span>
          {added && <span className="df-status ok">已添加</span>}
        </Field>
      </li>
    );
  };

  const total = rows.length + unmatched.length;
  return (
    <div className="df-model-picker" data-testid="provider-model-picker">
      {total > 10 && (
        <Input
          aria-label="搜索模型"
          placeholder="搜索模型 ID"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      )}
      {(["image", "video"] as const).map((media) => {
        const group = rows.filter((row) => row.mediaType === media && visible(row.modelId));
        if (!group.length) return null;
        return (
          <section key={media} aria-label={`${MEDIA_LABEL[media]}模型`}>
            <h4>{MEDIA_LABEL[media]}</h4>
            <ul>{group.map(renderRow)}</ul>
          </section>
        );
      })}
      {unmatched.length > 0 && protocols.length > 0 && (
        <section aria-label="选择调用方式">
          <h4>
            其他模型 <span className="muted">选择调用方式后可添加</span>
          </h4>
          <ul>
            {unmatched.filter(visible).map((modelId) => {
              const contractId = mapped[modelId] ?? "";
              const contract = protocols.find((item) => item.catalog_entry_id === contractId);
              const mediaType = (contract?.media_type ?? "image") as MediaKind;
              const key = choiceKey({ modelId, mediaType });
              const added = contract ? existingKeys.has(key) : false;
              return (
                <li key={modelId}>
                  <Field className="df-model-check">
                    <Checkbox
                      aria-label={`使用 ${modelId}`}
                      checked={added || (contract ? value.has(key) : false)}
                      disabled={disabled || !contract || added}
                      onChange={(event) =>
                        contract && toggle({ modelId, mediaType, contractId }, event.target.checked)
                      }
                    />
                    <span className="df-model-name">
                      <code>{modelId}</code>
                    </span>
                  </Field>
                  <Select
                    aria-label={`${modelId} 调用方式`}
                    value={contractId}
                    disabled={disabled || added}
                    onChange={(event) => {
                      const previous = contract
                        ? choiceKey({ modelId, mediaType: contract.media_type as MediaKind })
                        : null;
                      if (previous && value.has(previous)) {
                        const next = new Map(value);
                        next.delete(previous);
                        onChange(next);
                      }
                      setMapped((current) => ({ ...current, [modelId]: event.target.value }));
                    }}
                  >
                    <option value="">暂不使用</option>
                    {protocols.map((item) => (
                      <option key={item.catalog_entry_id} value={item.catalog_entry_id}>
                        {item.display_name}（{MEDIA_LABEL[item.media_type as MediaKind]}）
                      </option>
                    ))}
                  </Select>
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {unmatched.length > 0 && protocols.length === 0 && (
        <Disclosure title={`已发现 · 暂未支持执行 ${unmatched.length}`}>
          <ul className="df-model-unsupported">
            {unmatched.filter(visible).map((modelId) => (
              <li key={modelId}>
                <code>{modelId}</code>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
      {total === 0 && <p className="muted">供应商没有返回可用的模型。</p>}
    </div>
  );
}
