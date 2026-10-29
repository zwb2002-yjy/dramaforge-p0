import { Field, Checkbox, Select, Input, Textarea, Disclosure } from "../ui";
/**
 * ManifestOptionControls — renders a model's capability spec as dynamic form
 * controls (V3 spec §59). All shapes come from the manifest: common options,
 * native (advanced) options, input-slot hints, and constraint-driven value
 * filtering. The component never branches on a model/provider name.
 */

import { useMemo, useState } from "react";
import type { CapabilitySpecRead, ParameterSpecRead } from "../../features/model-controls/api";
import { allowedValuesFor, constraintViolations, uiComponentFor } from "../../lib/manifestOptions";

export interface ManifestOptionControlsProps {
  spec: CapabilitySpecRead;
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}

function OptionControl({
  keyName,
  parameter,
  value,
  allowed,
  onChange,
}: {
  keyName: string;
  parameter: ParameterSpecRead;
  value: unknown;
  allowed: unknown[];
  onChange: (key: string, value: unknown) => void;
}) {
  const component = uiComponentFor(parameter);
  if (component === "switch") {
    return (
      <Field className="option-control">
        <span>{parameter.title ?? keyName}</span>
        <Checkbox
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(keyName, event.target.checked)}
        />
      </Field>
    );
  }
  if (component === "select") {
    return (
      <Field className="option-control">
        <span>{parameter.title ?? keyName}</span>
        <Select
          value={value === undefined ? "" : String(value)}
          onChange={(event) => onChange(keyName, event)}
        >
          <option value="">未设置</option>
          {allowed.map((item) => (
            <option key={String(item)} value={String(item)}>
              {String(item)}
            </option>
          ))}
        </Select>
      </Field>
    );
  }
  if (component === "number") {
    return (
      <Field className="option-control">
        <span>{parameter.title ?? keyName}</span>
        <Input
          type="number"
          step={parameter.type === "number" ? "any" : "1"}
          value={value === undefined ? "" : String(value)}
          onChange={(event) => {
            const raw = event.target.value;
            onChange(keyName, raw === "" ? undefined : Number(raw));
          }}
        />
      </Field>
    );
  }
  if (component === "textarea") {
    return (
      <Field className="option-control">
        <span>{parameter.title ?? keyName}</span>
        <Textarea
          value={value === undefined ? "" : String(value)}
          onChange={(event) => onChange(keyName, event.target.value)}
        />
      </Field>
    );
  }
  if (component === "multi_select") {
    const selected = Array.isArray(value) ? (value as unknown[]) : [];
    return (
      <fieldset className="option-control">
        <legend>{parameter.title ?? keyName}</legend>
        {allowed.map((item) => (
          <Field key={String(item)}>
            <Checkbox
              type="checkbox"
              checked={selected.includes(item)}
              onChange={(event) => {
                const next = event.target.checked
                  ? [...selected, item]
                  : selected.filter((existing) => existing !== item);
                onChange(keyName, next);
              }}
            />
            {String(item)}
          </Field>
        ))}
      </fieldset>
    );
  }
  return (
    <Field className="option-control">
      <span>{parameter.title ?? keyName}</span>
      <Input
        type="text"
        value={value === undefined ? "" : String(value)}
        onChange={(event) => onChange(keyName, event.target.value)}
      />
    </Field>
  );
}

export function ManifestOptionControls({ spec, values, onChange }: ManifestOptionControlsProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const violations = useMemo(() => constraintViolations(spec, values), [spec, values]);

  const commonOptions = spec.common_options ?? {};
  const nativeOptions = spec.native_options ?? {};
  const commonKeys = Object.keys(commonOptions);
  const nativeKeys = Object.keys(nativeOptions);
  const inputSlotHints = Object.entries(spec.input_slots ?? {});

  return (
    <div className="manifest-options" data-testid="manifest-options">
      {violations.length > 0 && (
        <div className="manifest-warnings" role="alert">
          {violations.map((message) => (
            <div key={message}>{message}</div>
          ))}
        </div>
      )}

      {inputSlotHints.length > 0 && (
        <div className="manifest-slots">
          {inputSlotHints.map(([role, slot]) => (
            <span key={role} className="slot-hint">
              {role}
              {slot.required ? "（必需）" : ""}
              {slot.maximum ? ` ×${slot.maximum}` : ""}
            </span>
          ))}
        </div>
      )}

      {commonKeys.length === 0 && nativeKeys.length === 0 && (
        <div className="manifest-empty">该模型无额外参数</div>
      )}

      {commonKeys.map((keyName) => {
        const parameter = commonOptions[keyName];
        const allowed = allowedValuesFor(spec, keyName, parameter, values);
        return (
          <OptionControl
            key={keyName}
            keyName={keyName}
            parameter={parameter}
            value={values[keyName]}
            allowed={allowed}
            onChange={onChange}
          />
        );
      })}

      {nativeKeys.length > 0 && (
        <Disclosure
          open={advancedOpen}
          onOpenChange={(event) => setAdvancedOpen(event)}
          title={<>高级参数</>}
        >
          {nativeKeys.map((keyName) => {
            const parameter = nativeOptions[keyName];
            return (
              <OptionControl
                key={keyName}
                keyName={keyName}
                parameter={parameter}
                value={values[keyName]}
                allowed={parameter.enum ?? []}
                onChange={onChange}
              />
            );
          })}
        </Disclosure>
      )}
    </div>
  );
}
