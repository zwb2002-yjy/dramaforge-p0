/**
 * ReferencePurposeEditor (P4-03/MS8).
 *
 * Lets the user pick the business purpose of a shot reference. The purpose
 * vocabulary mirrors the backend ShotReferenceBinding purpose set and is
 * translated to ModelManifest slots by P4-02 (reference_intents.py). No
 * provider/model branching.
 */

import { REFERENCE_PURPOSES } from "./referencePurposeOptions";

export { REFERENCE_PURPOSES } from "./referencePurposeOptions";

export interface ReferencePurposeEditorProps {
  value: string;
  onChange: (purpose: string) => void;
  disabled?: boolean;
}

export function ReferencePurposeEditor({
  value,
  onChange,
  disabled = false,
}: ReferencePurposeEditorProps) {
  return (
    <div data-testid="reference-purpose-editor">
      <label htmlFor="reference-purpose" className="mb-1 block text-xs font-medium text-gray-700">
        参考用途
      </label>
      <select
        id="reference-purpose"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50"
      >
        {REFERENCE_PURPOSES.map((purpose) => (
          <option key={purpose.value} value={purpose.value}>
            {purpose.label}（{purpose.description}）
          </option>
        ))}
      </select>
    </div>
  );
}
