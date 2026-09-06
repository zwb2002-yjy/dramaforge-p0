/**
 * Manifest-driven model option rendering (V3 spec §59).
 *
 * The frontend must never branch on a model/provider name. All parameter
 * shapes, advanced options, and legal combinations come from the model's
 * capability spec. These pure helpers turn a CapabilitySpec into renderable
 * controls and apply cross-field constraints (e.g. duration=10 restricts
 * resolution to ["720p"]) client-side as a *hint* — the backend re-validates.
 */

import type { CapabilitySpecRead, ParameterSpecRead } from "./api";

export type OptionValue = unknown;

export interface RenderableOption {
  key: string;
  label: string;
  parameter: ParameterSpecRead;
  /** True for model-native advanced options (collapsed behind "高级参数"). */
  native: boolean;
  /** Constraints that mention this option as a dependent. */
  constraints: string[];
}

export function uiComponentFor(
  parameter: ParameterSpecRead,
): NonNullable<ParameterSpecRead["ui_component"]> {
  if (parameter.ui_component) return parameter.ui_component;
  if (parameter.type === "boolean") return "switch";
  if (parameter.type === "integer" || parameter.type === "number") return "number";
  if (parameter.enum && parameter.enum.length > 0) return "select";
  if (parameter.type === "array") return "multi_select";
  return "input";
}

/**
 * Which options does this condition depend on? Only applied when the
 * "when" keys are present in the current values.
 */
function whenKeys(conditional: CapabilitySpecRead["constraints"]["conditional"]): string[] {
  const keys = new Set<string>();
  for (const condition of conditional) {
    for (const key of Object.keys(condition.when)) keys.add(key);
  }
  return [...keys];
}

/**
 * Filter the allowed values of `optionKey` given the current values and the
 * spec's conditional constraints. Returns the full list when no condition
 * applies.
 */
export function allowedValuesFor(
  spec: CapabilitySpecRead,
  optionKey: string,
  parameter: ParameterSpecRead,
  values: Record<string, OptionValue>,
): unknown[] {
  if (!parameter.enum) return [];
  for (const condition of spec.constraints.conditional) {
    const matches = Object.entries(condition.when).every(([key, value]) => values[key] === value);
    if (!matches) continue;
    const allowed = condition.allowed[optionKey];
    if (allowed !== undefined) return allowed;
  }
  return parameter.enum;
}

/**
 * Current invalid option pairs (client hint only; backend is authoritative).
 * e.g. duration=10 + resolution=1080p when 10s only allows 720p.
 */
export function constraintViolations(
  spec: CapabilitySpecRead,
  values: Record<string, OptionValue>,
): string[] {
  const violations: string[] = [];
  for (const condition of spec.constraints.conditional) {
    const matches = Object.entries(condition.when).every(([key, value]) => values[key] === value);
    if (!matches) continue;
    for (const key of Object.keys(condition.forbid)) {
      if (values[key] !== undefined) {
        violations.push(`${key} 不能与当前选项同时使用`);
      }
    }
    for (const [optionKey, allowed] of Object.entries(condition.allowed)) {
      const current = values[optionKey];
      if (current !== undefined && !allowed.includes(current)) {
        violations.push(`${optionKey} 当前值不被该时长允许`);
      }
    }
  }
  for (const group of spec.constraints.mutually_exclusive) {
    const present = group.filter((key) => values[key] !== undefined);
    if (present.length > 1) {
      violations.push(`${present.join(" / ")} 互斥，只能选择一个`);
    }
  }
  return violations;
}

/**
 * Renderable option list for one capability spec: common options first (in
 * spec order), then native options. Native options declare which conditions
 * they participate in so the UI can show/hide constraints.
 */
export function renderableOptions(spec: CapabilitySpecRead): {
  common: RenderableOption[];
  native: RenderableOption[];
} {
  const dependentKeys = new Set(whenKeys(spec.constraints.conditional));
  const common = Object.entries(spec.common_options).map(([key, parameter]) => ({
    key,
    label: parameter.title ?? key,
    parameter,
    native: false,
    constraints: dependentKeys.has(key) ? [...dependentKeys].filter((k) => k === key) : [],
  }));
  const native = Object.entries(spec.native_options).map(([key, parameter]) => ({
    key,
    label: parameter.title ?? key,
    parameter,
    native: true,
    constraints: dependentKeys.has(key) ? [...dependentKeys].filter((k) => k === key) : [],
  }));
  return { common, native };
}
