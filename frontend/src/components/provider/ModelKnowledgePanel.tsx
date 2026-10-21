import type {
  ProviderModelBindingRead,
  ProviderPluginModelRead,
  ProviderPluginRead,
} from "../../lib/api";
import { Disclosure, Table } from "../ui";
import {
  boundLabel,
  CONTROL_LABEL,
  constraintLabel,
  contractLabel,
  createBlockerLabel,
  groupEvidence,
  OPERATION_LABEL,
  parameterEvidence,
  parameterLabel,
  parameterValue,
  pointerSegment,
  protocolFactValue,
  ROLE_LABEL,
  type KnowledgeOperation,
  type KnowledgeParameter,
  type ModelKnowledge,
} from "./modelKnowledge";

function ParameterFacts({
  values,
  knowledge,
  path,
  fieldPaths,
}: {
  values: Record<string, KnowledgeParameter>;
  knowledge: ModelKnowledge;
  path: string;
  fieldPaths?: Record<string, string>;
}) {
  if (!Object.keys(values).length) return <p className="muted">参数尚未明确。</p>;
  return (
    <div className="df-knowledge-table-wrap">
      <Table
        size="small"
        pagination={false}
        rowKey="name"
        scroll={{ x: true }}
        dataSource={Object.entries(values).map(([name, parameter]) => ({ name, parameter }))}
        columns={[
          { title: "参数", dataIndex: "name", render: (name: string) => parameterLabel(name) },
          {
            title: "取值或限制",
            render: (_, { name, parameter }) => parameterValue(parameter, name),
          },
          { title: "控制方式", render: (_, { parameter }) => CONTROL_LABEL[parameter.control] },
          {
            title: "核验状态",
            render: (_, { name, parameter }) =>
              parameterEvidence(
                knowledge,
                fieldPaths?.[name] ?? `${path}/${pointerSegment(name)}`,
                parameter.claim_status,
              ),
          },
        ]}
      />
    </div>
  );
}

function OperationFacts({
  operation,
  knowledge,
}: {
  operation: KnowledgeOperation;
  knowledge: ModelKnowledge;
}) {
  const path = `/operations/${operation.operation}`;
  return (
    <Disclosure
      title={OPERATION_LABEL[operation.operation] ?? "其他操作"}
      description={`${groupEvidence(knowledge, path, operation.claim_status)} · 尚未接入执行`}
    >
      {operation.prompt_spec && (
        <ParameterFacts
          values={{ prompt: operation.prompt_spec }}
          knowledge={knowledge}
          path={path}
          fieldPaths={{ prompt: `${path}/prompt_spec` }}
        />
      )}
      <h5>输入素材与限制</h5>
      {Object.entries(operation.input_contracts ?? {}).map(([id, contract]) => (
        <section className="df-knowledge-input" key={id}>
          <h6>{contractLabel(contract)}</h6>
          <p>
            {groupEvidence(
              knowledge,
              `${path}/input_contracts/${pointerSegment(id)}`,
              contract.claim_status,
            )}
          </p>
          <p>
            素材总数：最少 {boundLabel(contract.minimum_total_references)}；最多{" "}
            {boundLabel(contract.maximum_total_references)}
          </p>
          {Object.entries(contract.input_slots ?? {}).map(([role, slot]) => (
            <div key={role}>
              <strong>{ROLE_LABEL[role] ?? "素材"}</strong>
              <span>
                （
                {groupEvidence(
                  knowledge,
                  `${path}/input_contracts/${pointerSegment(id)}/input_slots/${role}`,
                  slot.claim_status,
                )}
                ）
              </span>
              <p>
                数量：{boundLabel(slot.minimum)} 至 {boundLabel(slot.maximum)}；单文件大小：
                {slot.max_bytes?.inclusive === false ? "小于" : "最多"}{" "}
                {boundLabel(slot.max_bytes, " 字节")}
              </p>
              <p>格式：{slot.media_types.length ? slot.media_types.join("、") : "待核实"}</p>
              {slot.min_width && !role.includes("audio") && (
                <p>
                  宽度：{boundLabel(slot.min_width)} 至 {boundLabel(slot.max_width)}；高度：
                  {boundLabel(slot.min_height)} 至 {boundLabel(slot.max_height)}
                </p>
              )}
              {knowledge.fields.some((field) =>
                ["min_pixels", "max_pixels"].some(
                  (name) =>
                    field.path ===
                    `${path}/input_contracts/${pointerSegment(id)}/input_slots/${role}/${name}`,
                ),
              ) && (
                <p>
                  像素总数：{boundLabel(slot.min_pixels)} 至 {boundLabel(slot.max_pixels)}
                </p>
              )}
              {knowledge.fields.some((field) =>
                ["min_aspect_ratio", "max_aspect_ratio"].some(
                  (name) =>
                    field.path ===
                    `${path}/input_contracts/${pointerSegment(id)}/input_slots/${role}/${name}`,
                ),
              ) && (
                <p>
                  宽高比：{boundLabel(slot.min_aspect_ratio)} 至 {boundLabel(slot.max_aspect_ratio)}
                </p>
              )}
              {(role.includes("video") || role.includes("audio")) && (
                <p>
                  时长：{boundLabel(slot.min_duration_seconds, " 秒")} 至{" "}
                  {boundLabel(slot.max_duration_seconds, " 秒")}
                </p>
              )}
              {role.includes("video") && (
                <p>
                  帧率：{boundLabel(slot.min_fps)} 至 {boundLabel(slot.max_fps)}；编码：
                  {slot.codecs.length ? slot.codecs.join("、") : "待核实"}
                </p>
              )}
              {Object.keys(slot.wire_options ?? {}).length > 0 && (
                <ParameterFacts
                  values={slot.wire_options!}
                  knowledge={knowledge}
                  path={`${path}/input_contracts/${pointerSegment(id)}/input_slots/${role}/wire_options`}
                />
              )}
            </div>
          ))}
          {Object.entries(contract.max_total_duration_seconds ?? {}).map(([role, limit]) => (
            <p key={role}>
              {ROLE_LABEL[role] ?? "素材"}合计时长：最多 {boundLabel(limit, " 秒")}
            </p>
          ))}
          {Object.entries(contract.min_total_duration_seconds ?? {}).map(([role, limit]) => (
            <p key={role}>
              {ROLE_LABEL[role] ?? "素材"}合计时长：最少 {boundLabel(limit, " 秒")}
            </p>
          ))}
          {contract.maximum_total_bytes && (
            <p>素材合计大小：{boundLabel(contract.maximum_total_bytes, " 字节")}</p>
          )}
          {Object.entries(contract.max_total_bytes_by_role ?? {}).map(([role, limit]) => (
            <p key={role}>
              {ROLE_LABEL[role] ?? "素材"}合计大小：最多 {boundLabel(limit, " 字节")}
            </p>
          ))}
          {contract.constraints.length > 0 && (
            <ul>
              {contract.constraints.map((rule, index) => (
                <li key={index}>
                  {constraintLabel(rule)}（
                  {groupEvidence(
                    knowledge,
                    `${path}/input_contracts/${pointerSegment(id)}/constraints/${index}`,
                    rule.claim_status,
                  )}
                  ）
                </li>
              ))}
            </ul>
          )}
          <ParameterFacts
            values={contract.output_options ?? {}}
            knowledge={knowledge}
            path={`${path}/input_contracts/${pointerSegment(id)}/output_options`}
          />
        </section>
      ))}
      <h5>参数记录</h5>
      <ParameterFacts
        values={operation.output_options ?? {}}
        knowledge={knowledge}
        path={`${path}/output_options`}
      />
      {operation.maximum_request_bytes && (
        <p>请求合计大小：最多 {boundLabel(operation.maximum_request_bytes, " 字节")}</p>
      )}
      {operation.constraints.length > 0 && (
        <ul>
          {operation.constraints.map((rule, index) => (
            <li key={index}>
              {constraintLabel(rule)}（
              {groupEvidence(knowledge, `${path}/constraints/${index}`, rule.claim_status)}）
            </li>
          ))}
        </ul>
      )}
      {Object.keys(operation.protocol_facts ?? {}).length > 0 && (
        <Disclosure title="协议与固定输出事实">
          <ul>
            {Object.entries(operation.protocol_facts ?? {}).map(([name, fact]) => (
              <li key={name}>
                {parameterLabel(name)}：{protocolFactValue(fact)}（
                {parameterEvidence(
                  knowledge,
                  `${path}/protocol_facts/${pointerSegment(name)}`,
                  fact.claim_status,
                )}
                ）
              </li>
            ))}
          </ul>
        </Disclosure>
      )}
    </Disclosure>
  );
}

function ModelFacts({
  model,
  bindings,
}: {
  model: ProviderPluginModelRead;
  bindings: ProviderModelBindingRead[];
}) {
  const knowledge = model.knowledge!;
  const registered = bindings.filter(
    (binding) => binding.catalog_entry_id === model.catalog_entry_id,
  );
  const matching = registered.filter(
    (binding) => binding.capability_manifest_hash === model.capability_manifest_hash,
  );
  const enabled = matching.filter((binding) => binding.enabled);
  return (
    <Disclosure
      title={model.model_id}
      description="候选能力说明 · 只读"
      testId="model-knowledge-card"
    >
      <p>
        目录合同修订：{model.model_revision}。{createBlockerLabel(model.new_create_blocker)}
      </p>
      <p className="df-status warn">候选修订未实现；产品未开放；该修订账号尚未实测。</p>
      <p>
        现有绑定：
        {enabled.length
          ? enabled.some((binding) => binding.account_verified)
            ? "目录已验证，执行仍须满足合同准入"
            : "账号目录尚未验证"
          : registered.length && !matching.length
            ? "合同内容不一致，需要维护核对"
            : matching.length
              ? "已停用"
              : "尚未绑定"}
      </p>
      <p>
        已核实 {knowledge.official_supported_fields} 组事实；未知{" "}
        {knowledge.claim_counts.unknown ?? 0} 组；冲突 {knowledge.claim_counts.conflicting ?? 0}{" "}
        组；明确不支持 {knowledge.claim_counts.documented_unsupported ?? 0} 组。
      </p>
      <p>已标注未知的限制：{knowledge.unknown_bounds} 项。未知不代表无上限。</p>
      {Object.values(knowledge.operations).map((operation) => (
        <OperationFacts key={operation.operation} operation={operation} knowledge={knowledge} />
      ))}
      <Disclosure title="来源与修订">
        <p>知识修订：{knowledge.model_revision}</p>
        <p className="df-knowledge-hash">内容 Hash：{knowledge.manifest_hash}</p>
        <ul>
          {(knowledge.sources ?? []).map((source) => (
            <li key={source.source_snapshot_ref ?? source.url}>
              <a href={source.url} target="_blank" rel="noreferrer">
                官方资料
              </a>
              {source.checked_at && ` · 检查日期 ${source.checked_at}`}
              {source.status !== "source_snapshot_reviewed" && " · 来源范围或内容仍待核验"}
            </li>
          ))}
        </ul>
        {!knowledge.sources?.length && <p>尚无适用的已审核来源。</p>}
      </Disclosure>
    </Disclosure>
  );
}

/** Knowledge remains separate from the exact Binding and all production actions. */
export function ModelKnowledgePanel({
  plugin,
  bindings,
}: {
  plugin: ProviderPluginRead;
  bindings: ProviderModelBindingRead[];
}) {
  const unique = new Map<string, ProviderPluginModelRead>();
  for (const model of plugin.models) {
    if (!model.knowledge || model.catalog_source === "protocol_contract") continue;
    const previous = unique.get(model.model_id);
    const bound = bindings.some(
      (binding) =>
        binding.enabled &&
        binding.catalog_entry_id === model.catalog_entry_id &&
        binding.capability_manifest_hash === model.capability_manifest_hash,
    );
    const previousBound =
      previous &&
      bindings.some(
        (binding) =>
          binding.enabled &&
          binding.catalog_entry_id === previous.catalog_entry_id &&
          binding.capability_manifest_hash === previous.capability_manifest_hash,
      );
    if (
      !previous ||
      (bound && !previousBound) ||
      (bound === Boolean(previousBound) &&
        model.lifecycle === "active" &&
        previous.lifecycle !== "active")
    )
      unique.set(model.model_id, model);
  }
  if (!unique.size) return null;
  return (
    <Disclosure
      title="模型能力说明"
      description="官方事实、未知限制与执行状态"
      testId="provider-model-knowledge"
    >
      <div className="df-model-knowledge">
        <p>这些候选记录用于了解模型能力。查看和展开不会调用供应商，也不会变更当前选择。</p>
        {[...unique.values()].map((model) => (
          <ModelFacts key={model.model_id} model={model} bindings={bindings} />
        ))}
      </div>
    </Disclosure>
  );
}
