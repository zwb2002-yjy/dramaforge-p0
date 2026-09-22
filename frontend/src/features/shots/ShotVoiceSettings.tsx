import { useQuery } from "@tanstack/react-query";
import { useId } from "react";

import { Button, Field, Input, Select } from "../../components/ui";
import { queryKeys } from "../../lib/queryKeys";
import { fetchVoiceOptions, type ShotVoiceSettings as VoiceSettings } from "./api";
import "./shot-voice-settings.css";

/** Configuration only: changing these controls never synthesizes or previews audio. */
export function ShotVoiceSettings({
  projectId,
  value,
  onChange,
}: {
  projectId: string;
  value: VoiceSettings;
  onChange: (value: VoiceSettings) => void;
}) {
  const id = useId();
  const canReadOptions = Boolean(projectId);
  const options = useQuery({
    queryKey: queryKeys.shot.voiceOptions(projectId),
    queryFn: ({ signal }) => fetchVoiceOptions(projectId, signal),
    enabled: canReadOptions,
    staleTime: 60_000,
    retry: false,
    refetchOnWindowFocus: false,
  });
  // A failed refresh must not present cached configuration as current fact.
  const config = options.isError ? undefined : options.data;
  const voices = config?.voices ?? [];
  const voiceId = value.voice_id ?? null;
  const rate = value.rate_percent ?? 0;
  const listedVoice = voices.find((voice) => voice.id === voiceId);
  const defaultVoice = voices.find((voice) => voice.id === config?.default_voice);
  const rateLabel =
    rate === 0 ? "正常（0%）" : rate < 0 ? "放慢 " + -rate + "%" : "加快 " + rate + "%";

  return (
    <div className="shot-voice-settings" data-testid="shot-voice-settings">
      {!canReadOptions && <p role="status">请选择实际项目后读取配音配置。</p>}
      {canReadOptions && options.isPending && (
        <p role="status">正在读取音色配置，不会调用语音服务…</p>
      )}
      {options.isError && (
        <div role="alert">
          <p>音色目录读取失败，当前音色和语速已保留。请检查项目访问权限或重新读取。</p>
          <Button
            type="button"
            disabled={options.isFetching}
            onClick={() => void options.refetch()}
          >
            重新读取音色
          </Button>
        </div>
      )}
      {config && (
        <>
          <p className="muted" id={id + "-notice"}>
            {config.service_notice}
          </p>
          {config.network && (
            <p className="muted">
              生成时对白文本将发送至微软在线语音服务；失败不会回退为旧机械音。
            </p>
          )}
          {(!config.enabled || config.status === "disabled") && (
            <p role="status">配音服务未启用。可以保存镜头设置，导出前需先启用服务。</p>
          )}
          {config.status === "invalid" && (
            <p role="alert">
              配音配置无效。可以保存镜头设置，导出前需先修正配置；不会自动改用其他引擎。
            </p>
          )}
          {voices.length === 0 && <p role="status">当前配置未提供可选音色，已有设置不会被清空。</p>}
        </>
      )}
      <Field>
        配音音色
        <Select
          aria-label="配音音色"
          aria-describedby={config ? id + "-notice" : undefined}
          value={voiceId === null ? "" : "voice:" + voiceId}
          disabled={!config || voices.length === 0}
          onChange={(event) =>
            onChange({
              ...value,
              voice_id:
                event.target.value === "" ? null : event.target.value.slice("voice:".length),
            })
          }
        >
          <option value="">
            沿用实例默认
            {config?.default_voice
              ? "（" + (defaultVoice?.label ?? config.default_voice) + "）"
              : ""}
          </option>
          {voiceId !== null && !listedVoice && (
            <option value={"voice:" + voiceId}>
              {config ? "未在当前目录中的音色" : "当前音色（目录未读取）"}：
              {voiceId || "（空标识）"}
            </option>
          )}
          {voices.map((voice) => (
            <option key={voice.id} value={"voice:" + voice.id}>
              {voice.label} · {voice.locale}
            </option>
          ))}
        </Select>
      </Field>
      {voiceId !== null && config && !listedVoice && (
        <p role="alert">
          当前音色不在此引擎的目录中，已原样保留。请在生成前明确选择可用音色；不会静默切换到默认音色。
        </p>
      )}
      <Field>
        配音语速 · {rateLabel}
        <Input
          aria-label="配音语速"
          aria-valuetext={rateLabel}
          type="range"
          min={-30}
          max={30}
          step={1}
          value={rate}
          onChange={(event) => {
            const next = Number(event.target.value);
            if (Number.isInteger(next) && next >= -30 && next <= 30) {
              onChange({ ...value, rate_percent: next });
            }
          }}
        />
      </Field>
      <p className="muted">语速范围：放慢 30% 至加快 30%；0% 为正常语速。</p>
    </div>
  );
}
