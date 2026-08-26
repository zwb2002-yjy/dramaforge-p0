/**
 * DynamicCapabilityForm (P4-03/MS8).
 *
 * Renders a CapabilitySpec's options purely from the manifest. Every control
 * shape (switch/slider/select/input/textarea) and every cross-field rule
 * (conditional allowed values, mutually exclusive groups) comes from
 * CapabilitySpecRead. No provider/model-name branching.
 */

import type { CapabilitySpecRead, ParameterSpecRead } from "../../lib/api";
import { allowedValuesFor, uiComponentFor, type OptionValue } from "../../lib/manifestOptions";

const EMPTY_SPEC: CapabilitySpecRead = {
  capability: "",
  input_slots: {},
  common_options: {},
  native_options: {},
  constraints: { mutually_exclusive: [], requires: {}, conditional: [] },
  transport_profile_id: "",
};

export interface OptionFieldProps {
  keyName: string;
  label: string;
  parameter: ParameterSpecRead;
  value: OptionValue;
  onChange: (key: string, value: OptionValue) => void;
  disabled?: boolean;
  /** Values of the sibling options (for conditional / exclusive hints). */
  values: Record<string, OptionValue>;
  spec?: CapabilitySpecRead;
}

function isDisabledByExclusiveGroup(
  spec: CapabilitySpecRead,
  keyName: string,
  values: Record<string, OptionValue>,
): boolean {
  for (const group of spec.constraints.mutually_exclusive) {
    if (!group.includes(keyName)) continue;
    const occupied = group.find((member) => member !== keyName && values[member] !== undefined);
    if (occupied !== undefined) return true;
  }
  return false;
}

export function OptionField({
  keyName,
  label,
  parameter,
  value,
  onChange,
  disabled = false,
  values,
  spec = EMPTY_SPEC,
}: OptionFieldProps) {
  const exclusive = isDisabledByExclusiveGroup(spec, keyName, values);
  const effectiveDisabled = disabled || exclusive;
  const component = uiComponentFor(parameter);
  const allowed = allowedValuesFor(spec, keyName, parameter, values);
  const hint = exclusive ? "与已选项互斥" : undefined;

  const baseClass = "w-full rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50";
  const labelNode = (
    <span className="mb-1 block text-xs font-medium text-gray-700">
      {label}
      {hint ? <span className="ml-2 text-amber-600">{hint}</span> : null}
    </span>
  );

  if (component === "switch") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(value)}
          disabled={effectiveDisabled}
          onChange={(event) => onChange(keyName, event.target.checked)}
        />
        {label}
      </label>
    );
  }
  if (component === "slider") {
    const min = parameter.minimum ?? 0;
    const max = parameter.maximum ?? 100;
    return (
      <div>
        {labelNode}
        <input
          type="range"
          min={min}
          max={max}
          value={typeof value === "number" ? value : (parameter.default as number) ?? min}
          disabled={effectiveDisabled}
          onChange={(event) => onChange(keyName, Number(event.target.value))}
          className="w-full"
        />
      </div>
    );
  }
  if (component === "select") {
    const options = allowed.length > 0 ? allowed : (parameter.enum ?? []);
    return (
      <div>
        {labelNode}
        <select
          value={String(value ?? "")}
          disabled={effectiveDisabled}
          onChange={(event) => onChange(keyName, event.target.value)}
          className={baseClass}
        >
          <option value="">（默认）</option>
          {options.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      </div>
    );
  }
  if (component === "textarea") {
    return (
      <div>
        {labelNode}
        <textarea
          value={String(value ?? "")}
          disabled={effectiveDisabled}
          onChange={(event) => onChange(keyName, event.target.value)}
          rows={3}
          className={baseClass}
        />
      </div>
    );
  }
  if (component === "number") {
    return (
      <div>
        {labelNode}
        <input
          type="number"
          value={typeof value === "number" ? value : ""}
          disabled={effectiveDisabled}
          onChange={(event) => onChange(keyName, Number(event.target.value))}
          className={baseClass}
        />
      </div>
    );
  }
  return (
    <div>
      {labelNode}
      <input
        type="text"
        value={String(value ?? "")}
        disabled={effectiveDisabled}
        onChange={(event) => onChange(keyName, event.target.value)}
        className={baseClass}
      />
    </div>
  );
}

export interface DynamicCapabilityFormProps {
  spec: CapabilitySpecRead;
  values: Record<string, OptionValue>;
  onChange: (key: string, value: OptionValue) => void;
  /** Keys to render in the main form (defaults to common_options). */
  optionKeys?: string[];
}

export function DynamicCapabilityForm({
  spec,
  values,
  onChange,
  optionKeys,
}: DynamicCapabilityFormProps) {
  const keys = optionKeys ?? Object.keys(spec.common_options);
  return (
    <div className="space-y-3" data-testid="dynamic-capability-form">
      {keys.map((key) => {
        const parameter = spec.common_options[key];
        if (!parameter) return null;
        return (
          <OptionField
            key={key}
            keyName={key}
            label={parameter.title ?? key}
            parameter={parameter}
            value={values[key]}
            onChange={onChange}
            values={values}
            spec={spec}
          />
        );
      })}
    </div>
  );
}
