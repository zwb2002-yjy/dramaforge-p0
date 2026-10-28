import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Disclosure } from "../../components/ui";
import { getSelectedWorkspaceId } from "../../lib/navigationPreferences";
import { queryKeys } from "../../lib/queryKeys";
import {
  generationOptionLabel,
  generationOptionSourceLabel,
  generationSettingsCopy as copy,
} from "../../lib/generationOptionLabels";
import {
  executionModelSourceLabel,
  executionModelBlockerLabel,
} from "../../lib/modelResolutionLabels";
import { optionValueIsValid } from "../../lib/manifestOptions";
import type { CapabilitySpecRead } from "../../lib/api";
import { AdvancedModelOptions, DynamicCapabilityForm } from "../model-controls";
import { fetchShotModelCapabilities, type ShotExecutionStage } from "./api";

function mapping(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

type Props = {
  projectId: string;
  stage: ShotExecutionStage;
  mode: string;
  settings: Record<string, unknown>;
  disabled?: boolean;
  onChange: (settings: Record<string, unknown>) => void;
  onOpenModelSettings?: () => void;
};

function StageOptions({
  projectId,
  stage,
  mode,
  settings,
  disabled,
  onChange,
  onOpenModelSettings,
}: Props) {
  const workspaceId = getSelectedWorkspaceId();
  const query = useQuery({
    queryKey: queryKeys.model.generationOptions(projectId, workspaceId, stage, mode),
    queryFn: ({ signal }) =>
      fetchShotModelCapabilities(projectId, stage, mode, workspaceId, signal),
    retry: false,
    enabled: Boolean(projectId),
  });
  const options = query.data?.generation_options ?? {};
  const common = mapping(settings.common_options);
  const native = mapping(settings.native_options);
  const overrides = { ...common, ...native };
  if (settings.request_duration_seconds != null) {
    overrides.duration_seconds = settings.request_duration_seconds;
  }
  const values = Object.fromEntries(
    Object.entries(options).map(([name, option]) => [
      name,
      overrides[name] ?? option.inherited_value ?? undefined,
    ]),
  );
  const setOption = (name: string, value: unknown) => {
    const nextCommon = { ...common };
    const nextNative = { ...native };
    delete nextNative[name];
    if (value === undefined) delete nextCommon[name];
    else nextCommon[name] = value;
    const next: Record<string, unknown> = {
      ...settings,
      common_options: nextCommon,
      native_options: nextNative,
      source_contract_hash: settings.source_contract_hash ?? query.data?.report.manifest_hash,
    };
    if (name === "duration_seconds") {
      delete next.request_duration_seconds;
      delete nextCommon.duration;
      delete nextNative.duration;
    }
    onChange(next);
  };
  const writable = Object.fromEntries(
    Object.entries(options)
      .filter(([, option]) => option.editable)
      .map(([name, option]) => [name, { ...option.parameter, title: generationOptionLabel(name) }]),
  );
  const primaryNames = ["aspect_ratio", "duration_seconds", "resolution", "size"];
  const advanced = Object.fromEntries(
    Object.entries(writable).filter(([name]) => !primaryNames.includes(name)),
  );
  const spec: CapabilitySpecRead = {
    capability: stage === "video" ? "video.image_to_video" : "image.generate",
    minimum_total_references: 0,
    auto_match_contract: false,
    transport_profile_id: "workbench",
    common_options: writable,
  };
  const incompatible = Object.keys(overrides).filter(
    (name) =>
      name !== "duration" &&
      overrides[name] != null &&
      (!options[name] ||
        options[name].reason === "compiler_unavailable" ||
        options[name].reason === "sensitive" ||
        options[name].reason === "deprecated" ||
        !optionValueIsValid(options[name].parameter, overrides[name]) ||
        (common[name] != null && native[name] != null && common[name] !== native[name])),
  );
  const changedContract =
    query.data &&
    settings.source_contract_hash != null &&
    settings.source_contract_hash !== query.data.report.manifest_hash;
  return (
    <div data-testid={`shot-generation-options-${stage}`}>
      {query.isPending && (
        <p className="df-shot-hint" role="status">
          {copy.loading}
        </p>
      )}
      {query.isError && (
        <p className="df-shot-hint err" role="alert">
          {copy.failed}
        </p>
      )}
      {query.data && (
        <>
          {changedContract && (
            <div className="df-shot-hint err" role="alert">
              <p>{copy.changedContract}</p>
              <Button
                tone="ghost"
                disabled={disabled || incompatible.length > 0}
                onClick={() =>
                  onChange({ ...settings, source_contract_hash: query.data.report.manifest_hash })
                }
              >
                {copy.acceptContract}
              </Button>
            </div>
          )}
          <p className="df-shot-hint">
            {copy.model}：{query.data.resolution?.invoke_model_value ?? query.data.report.model_id}
            {query.data.connection_label && ` · ${query.data.connection_label}`}
            {query.data.resolution &&
              ` · ${executionModelSourceLabel(query.data.resolution.source)}`}
          </p>
          <p className="df-shot-hint">
            合同：{query.data.report.model_revision ?? "—"} ·{" "}
            {query.data.report.manifest_hash.slice(0, 12)}
          </p>
          {query.data.resolution?.reason && (
            <p className="df-shot-hint err" role="alert">
              {executionModelBlockerLabel(query.data.resolution.reason)}
            </p>
          )}
          <DynamicCapabilityForm
            spec={spec}
            values={values}
            onChange={setOption}
            disabled={disabled}
            optionKeys={primaryNames.filter((name) => Boolean(writable[name]))}
          />
          <AdvancedModelOptions
            options={advanced}
            values={values}
            onChange={setOption}
            disabled={disabled}
          />
          {Object.entries(options)
            .filter(([, option]) => option.reason === "fixed_value")
            .map(([name, option]) => (
              <div className="df-shot-field" key={name}>
                <span className="df-shot-label">
                  {generationOptionLabel(name)} · {copy.fixed}：
                  {String(option.parameter.enum?.[0] ?? option.inherited_value ?? "—")}
                </span>
                <p className="df-shot-hint">
                  {copy.current}：{String(values[name] ?? "—")} ·
                  {generationOptionSourceLabel(
                    overrides[name] == null ? option.inherited_source : "shot",
                  )}
                </p>
                {values[name] != null && values[name] !== option.parameter.enum?.[0] && (
                  <p className="df-shot-hint err" role="alert">
                    {copy.fixedMismatch}
                  </p>
                )}
                <Button
                  tone="ghost"
                  disabled={disabled}
                  onClick={() => setOption(name, option.parameter.enum?.[0])}
                >
                  {copy.adopt}
                </Button>
                {overrides[name] != null && (
                  <Button
                    tone="ghost"
                    disabled={disabled}
                    onClick={() => setOption(name, undefined)}
                  >
                    {copy.inherit}
                  </Button>
                )}
              </div>
            ))}
          {Object.keys(writable).map((name) => (
            <p className="df-shot-hint" key={name}>
              {generationOptionLabel(name)} ·{" "}
              {generationOptionSourceLabel(
                overrides[name] == null ? options[name].inherited_source : "shot",
              )}
              {!optionValueIsValid(options[name].parameter, values[name]) && (
                <span role="alert"> · {copy.invalid}</span>
              )}
              {overrides[name] != null && (
                <Button tone="ghost" disabled={disabled} onClick={() => setOption(name, undefined)}>
                  {copy.inherit}
                </Button>
              )}
            </p>
          ))}
          {Object.values(options).some((option) => option.reason === "compiler_unavailable") && (
            <Disclosure compact title={copy.unavailableGroup}>
              {Object.entries(options)
                .filter(([, option]) => option.reason === "compiler_unavailable")
                .map(([name]) => (
                  <p className="df-shot-hint" key={name}>
                    {generationOptionLabel(name)} · {copy.unavailable}
                  </p>
                ))}
            </Disclosure>
          )}
          {incompatible.length > 0 && (
            <div className="df-shot-hint err" role="alert">
              <p>
                {copy.incompatible} {incompatible.map(generationOptionLabel).join("、")}
              </p>
              <Button
                tone="ghost"
                disabled={disabled}
                onClick={() => {
                  const nextCommon = { ...common },
                    nextNative = { ...native };
                  for (const name of incompatible) {
                    delete nextCommon[name];
                    delete nextNative[name];
                  }
                  onChange({ ...settings, common_options: nextCommon, native_options: nextNative });
                }}
              >
                {copy.remove}
              </Button>
            </div>
          )}
        </>
      )}
      {onOpenModelSettings && (
        <Button tone="ghost" onClick={onOpenModelSettings}>
          {copy.configure}
        </Button>
      )}
      <p className="df-shot-hint">{copy.save}</p>
    </div>
  );
}

/** Only expanded controls read capabilities; closing retains the Shot-owned draft. */
export function ShotGenerationSettings(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <Disclosure
      compact
      title={copy[props.stage]}
      open={open}
      onOpenChange={setOpen}
      testId={`shot-generation-settings-${props.stage}`}
    >
      {open && <StageOptions {...props} />}
    </Disclosure>
  );
}
