import { Field, Checkbox, Select, Textarea, Input, Slider } from "../../components/ui";
/**
 * DynamicCapabilityForm (P4-03/MS8).
 *
 * Renders a CapabilitySpec's options purely from the manifest. Every control
 * shape (switch/slider/select/input/textarea) and every cross-field rule
 * (conditional allowed values, mutually exclusive groups) comes from
 * CapabilitySpecRead. No provider/model-name branching.
 */

/**
 * DynamicCapabilityForm (P4-03/MS8).
 *
 * Renders a CapabilitySpec's options purely from the manifest. Every control
 * shape (switch/slider/select/input/textarea) and every cross-field rule
 * (conditional allowed values, mutually exclusive groups) comes from
 * CapabilitySpecRead. No provider/model-name branching.
 */
import type { CapabilitySpecRead, ParameterSpecRead } from "./api";
import { allowedValuesFor, uiComponentFor, type OptionValue } from "../../lib/manifestOptions";

const EMPTY_SPEC: CapabilitySpecRead = {
  capability: "image.generate",
  minimum_total_references: 0,
  auto_match_contract: false,
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
  for (const group of spec.constraints?.mutually_exclusive ?? []) {
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

  const baseClass = "df-model-option";
  const labelNode = (
    <span className="df-shot-label">
      {label}
      {hint ? <span className="df-shot-hint">{hint}</span> : null}
    </span>
  );

  if (component === "switch") {
    return (
      <Field>
        <Checkbox
          aria-label={label}
          type="checkbox"
          checked={Boolean(value)}
          disabled={effectiveDisabled}
          onChange={(event) => onChange(keyName, event.target.checked)}
        />
        {label}
      </Field>
    );
  }
  if (component === "slider") {
    const min = parameter.minimum ?? 0;
    const max = parameter.maximum ?? 100;
    return (
      <div>
        {labelNode}
        <Slider
          ariaLabelForHandle={label}
          min={min}
          max={max}
          value={typeof value === "number" ? value : ((parameter.default as number) ?? min)}
          disabled={effectiveDisabled}
          onChange={(value) => onChange(keyName, value)}
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
        <Select
          aria-label={label}
          value={value == null ? "__inherit__" : String(value)}
          disabled={effectiveDisabled}
          onChange={(selected) =>
            onChange(
              keyName,
              selected === "__inherit__"
                ? undefined
                : options.find((option) => String(option) === selected),
            )
          }
          className={baseClass}
        >
          <option value="__inherit__">（继承默认）</option>
          {options.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </Select>
      </div>
    );
  }
  if (component === "textarea") {
    return (
      <div>
        {labelNode}
        <Textarea
          aria-label={label}
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
        <Input
          aria-label={label}
          type="number"
          value={typeof value === "number" ? value : ""}
          disabled={effectiveDisabled}
          min={parameter.minimum ?? undefined}
          max={parameter.maximum ?? undefined}
          step={parameter.type === "integer" ? 1 : "any"}
          onChange={(event) =>
            onChange(keyName, event.target.value === "" ? undefined : Number(event.target.value))
          }
          className={baseClass}
        />
      </div>
    );
  }
  return (
    <div>
      {labelNode}
      <Input
        aria-label={label}
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
  disabled?: boolean;
}

export function DynamicCapabilityForm({
  spec,
  values,
  onChange,
  optionKeys,
  disabled,
}: DynamicCapabilityFormProps) {
  const commonOptions = spec.common_options ?? {};
  const keys = optionKeys ?? Object.keys(commonOptions);
  return (
    <div className="space-y-3" data-testid="dynamic-capability-form">
      {keys.map((key) => {
        const parameter = commonOptions[key];
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
            disabled={disabled}
          />
        );
      })}
    </div>
  );
}
