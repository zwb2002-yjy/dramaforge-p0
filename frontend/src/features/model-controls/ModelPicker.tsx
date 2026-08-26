/**
 * ModelPicker — manifest-driven model selection (P4-03/MS8).
 *
 * Renders models purely from `ModelRead` metadata (display name + declared
 * capabilities). It never branches on provider or model names, so new models
 * appear automatically once the backend exposes them.
 */

import type { ModelRead } from "../../lib/api";

export interface ModelPickerProps {
  models: ModelRead[];
  value: string | null;
  onChange: (modelId: string) => void;
  loading?: boolean;
}

export function ModelPicker({ models, value, onChange, loading = false }: ModelPickerProps) {
  if (loading) {
    return <div className="text-sm text-gray-500">加载模型…</div>;
  }
  if (models.length === 0) {
    return <div className="text-sm text-amber-600">当前没有可用的模型</div>;
  }
  return (
    <div role="listbox" aria-label="选择模型" className="space-y-1">
      {models.map((model) => {
        const selected = model.id === value;
        return (
          <button
            key={model.id}
            type="button"
            role="option"
            aria-selected={selected}
            disabled={!model.available}
            onClick={() => onChange(model.id)}
            className={[
              "w-full rounded border px-3 py-2 text-left text-sm",
              selected ? "border-blue-500 bg-blue-50" : "border-gray-300",
              !model.available ? "opacity-50" : "",
            ].join(" ")}
          >
            <span className="font-medium">{model.display_name}</span>
            <span className="ml-2 text-xs text-gray-500">
              {model.capabilities.join(" · ")}
            </span>
          </button>
        );
      })}
    </div>
  );
}
