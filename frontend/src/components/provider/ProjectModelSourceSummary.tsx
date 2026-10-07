import { useQuery } from "@tanstack/react-query";
import { Button } from "../ui";
import {
  getEffectiveBindings,
  getExecutionModelPreflight,
  listModelSlots,
  listProjectProviderBindings,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import {
  executionModelBlockerLabel,
  executionModelSourceLabel,
} from "../../lib/modelResolutionLabels";

/** A read model is a preview, not proof of dispatch or a replacement resolver. */
export function ProjectModelSourceSummary({
  projectId,
  projectName,
}: {
  projectId: string;
  projectName: string;
}) {
  const slots = useQuery({
    queryKey: queryKeys.model.slots(),
    queryFn: listModelSlots,
    retry: false,
  });
  const effective = useQuery({
    queryKey: queryKeys.model.effectiveBindings(projectId),
    queryFn: () => getEffectiveBindings(projectId),
    retry: false,
  });
  const bindings = useQuery({
    queryKey: queryKeys.provider.projectBindings(projectId),
    queryFn: () => listProjectProviderBindings(projectId),
    retry: false,
  });
  const preflight = useQuery({
    queryKey: queryKeys.model.executionPreflight(projectId),
    queryFn: () => getExecutionModelPreflight(projectId),
    retry: false,
  });
  const retry = () => {
    void slots.refetch();
    void effective.refetch();
    void bindings.refetch();
    void preflight.refetch();
  };
  // The legacy profile slot is not consumed by the current voice worker.
  // Keep this display boundary out of the execution resolver and do not infer
  // TTS readiness from a present or absent profile-preview row.
  const previewSlots = (slots.data ?? []).filter((slot) => slot.id !== "audio.tts");
  const missing =
    slots.isSuccess &&
    effective.isSuccess &&
    previewSlots.some((slot) => !effective.data.some((binding) => binding.slot === slot.id));
  return (
    <section
      className="df-settings-section"
      data-testid="project-model-source-summary"
      aria-label="作品模型来源"
    >
      <div className="panel-header">
        <h2>{projectName} · 模型来源</h2>
        <Button type="button" onClick={retry}>
          重新读取模型来源
        </Button>
      </div>
      <p className="muted">项目设置优先于默认模型；所选模型不可用时停止生成，不会换用其他模型。</p>
      <p className="muted" data-testid="voice-runtime-boundary">
        配音的音色和语速在镜头的「对白」中设置，不受这里控制。
      </p>
      <h3>实际使用</h3>
      {preflight.isPending ? (
        <p role="status">正在运行只读预检…</p>
      ) : preflight.isError ? (
        <p role="alert">生产预检读取失败；当前不能确认生成是否就绪。</p>
      ) : (
        <ul className="dense" data-testid="project-execution-model-preflight">
          {preflight.data.stages.map((stage) => (
            <li key={stage.stage} data-testid={`execution-model-${stage.stage}`}>
              <strong>{stage.stage === "image_keyframe" ? "关键帧" : "视频"}：</strong>
              {stage.ready && stage.resolved_model_id ? (
                <>
                  <code>{stage.resolved_model_id}</code>
                  <span> · 来源：{executionModelSourceLabel(stage.source)} · 可执行</span>
                </>
              ) : (
                <span className="status-pending">
                  不可执行 · {executionModelBlockerLabel(stage.reason)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <h3>已保存方案解析预览（不含配音派发）</h3>
      {slots.isPending || effective.isPending ? (
        <p role="status">正在读取方案解析预览…</p>
      ) : slots.isError || effective.isError ? (
        <p role="alert">方案解析预览读取失败；不能判断当前模型，不展示旧缓存为当前事实。</p>
      ) : (
        <>
          {missing && (
            <p role="status">
              部分环节未返回解析结果：可能未配置、已禁用或无法解析。不能据此判断整部作品就绪，也不会自动补选模型。
            </p>
          )}
          <ul className="dense">
            {previewSlots.map((slot) => {
              const binding = effective.data.find((item) => item.slot === slot.id);
              return (
                <li key={slot.id} data-testid={`model-source-${slot.id}`}>
                  <strong>{slot.display_name}：</strong>
                  {binding ? (
                    <>
                      <code>{binding.model_id}</code>
                      <span>
                        {" "}
                        · 来源：{executionModelSourceLabel(binding.source)}
                        {binding.profile_version != null
                          ? ` · 方案 v${binding.profile_version}`
                          : ""}
                      </span>
                    </>
                  ) : (
                    <span className="muted">未确认（本次预览未返回）</span>
                  )}
                </li>
              );
            })}
          </ul>
          {!previewSlots.length && (
            <p role="status">尚未返回可展示的非配音模型环节，不能确认方案覆盖范围。</p>
          )}
        </>
      )}
      <h3>已保存的项目供应商绑定</h3>
      <p className="muted">
        以下是保存的连接模型绑定，不等同于上方方案已采用它，也不代表已实际执行。
      </p>
      {bindings.isPending ? (
        <p role="status">正在读取项目供应商绑定…</p>
      ) : bindings.isError ? (
        <p role="alert">项目供应商绑定读取失败，不能当作未配置。</p>
      ) : bindings.data.length ? (
        <ul className="dense">
          {bindings.data.map((binding) => (
            <li key={binding.id}>
              <strong>
                {binding.purpose === "keyframe"
                  ? "关键帧"
                  : binding.purpose === "video"
                    ? "视频"
                    : "其他用途"}
                ：
              </strong>
              <code>{binding.model_id ?? "模型身份未返回"}</code>
              <span> · {binding.provider_type ?? "供应商未返回"}</span>
              {binding.model_binding_enabled === false && (
                <span className="status-pending"> · 绑定已停用</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">此项目尚未保存供应商绑定；不代表其他模型方案没有配置。</p>
      )}
      <p className="muted">
        本预览不包含本次请求覆盖、完整执行资格或正在运行任务的冻结身份；实际使用模型以生产任务记录为准。保存设置只影响后续解析，不修改已有任务和产物。
      </p>
    </section>
  );
}
