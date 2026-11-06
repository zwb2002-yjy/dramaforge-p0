/**
 * Manifest-driven model option rendering (V3 spec §59).
 *
 * The frontend must never branch on a model/provider name. All parameter
 * shapes, advanced options, and legal combinations come from the model's
 * capability spec. These pure helpers turn a CapabilitySpec into renderable
 * controls and apply cross-field constraints (e.g. duration=10 restricts
 * resolution to ["720p"]) client-side as a *hint* — the backend re-validates.
 */

/**
 * Manifest-driven model option rendering (V3 spec §59).
 *
 * The frontend must never branch on a model/provider name. All parameter
 * shapes, advanced options, and legal combinations come from the model's
 * capability spec. These pure helpers turn a CapabilitySpec into renderable
 * controls and apply cross-field constraints (e.g. duration=10 restricts
 * resolution to ["720p"]) client-side as a *hint* — the backend re-validates.
 */
import type { CapabilitySpecRead, ParameterSpecRead } from "../features/model-controls/api";

export type OptionValue = unknown;

/** Contract hints only; server validation remains authoritative. */
export function optionValueIsValid(parameter: ParameterSpecRead, value: unknown): boolean {
  if (value == null) return true;
  if (parameter.enum && !parameter.enum.includes(value)) return false;
  if (parameter.type === "integer" && (typeof value !== "number" || !Number.isInteger(value)))
    return false;
  if (parameter.type === "number" && (typeof value !== "number" || !Number.isFinite(value)))
    return false;
  if (parameter.type === "boolean" && typeof value !== "boolean") return false;
  if (parameter.type === "string" && typeof value !== "string") return false;
  if (
    typeof value === "number" &&
    ((parameter.minimum != null && value < parameter.minimum) ||
      (parameter.maximum != null && value > parameter.maximum))
  )
    return false;
  return true;
}

export function uiComponentFor(
  parameter: ParameterSpecRead,
): NonNullable<ParameterSpecRead["ui_component"]> {
  if (parameter.ui_component) return parameter.ui_component;
  if (parameter.type === "boolean") return "switch";
  if (parameter.enum && parameter.enum.length > 0) return "select";
  if (parameter.type === "integer" || parameter.type === "number") return "number";
  if (parameter.type === "array") return "multi_select";
  return "input";
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
  for (const condition of spec.constraints?.conditional ?? []) {
    const matches = Object.entries(condition.when).every(([key, value]) => values[key] === value);
    if (!matches) continue;
    const allowed = condition.allowed?.[optionKey];
    if (allowed !== undefined) return allowed;
  }
  return parameter.enum;
}
