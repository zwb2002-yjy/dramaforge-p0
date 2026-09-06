/**
 * AdvancedModelOptions (P4-03/MS8).
 *
 * Collapsible "高级参数" section for model-native options, rendered from the
 * manifest exactly like the common options (no name branching).
 */

import { Fragment, type ReactElement, useState } from "react";

import type { ParameterSpecRead } from "../../lib/api";
import { OptionField, type OptionFieldProps } from "./DynamicCapabilityForm";

export interface AdvancedModelOptionsProps {
  options: Record<string, ParameterSpecRead>;
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  /** Reuse the same OptionFieldProps to stay consistent with the form. */
  renderField?: (props: OptionFieldProps) => ReactElement;
}

export function AdvancedModelOptions({
  options,
  values,
  onChange,
  renderField = (props) => <OptionField {...props} />,
}: AdvancedModelOptionsProps) {
  const [open, setOpen] = useState(false);
  const keys = Object.keys(options);
  if (keys.length === 0) return null;
  return (
    <details
      data-testid="advanced-model-options"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer text-sm font-medium text-gray-700">高级参数</summary>
      <div className="mt-2 space-y-3">
        {keys.map((key) => {
          const parameter = options[key];
          if (!parameter) return null;
          return (
            <Fragment key={key}>
              {renderField({
                keyName: key,
                label: parameter.title ?? key,
                parameter,
                value: values[key],
                onChange: (k: string, v: unknown) => onChange(k, v),
                values,
              })}
            </Fragment>
          );
        })}
      </div>
    </details>
  );
}
