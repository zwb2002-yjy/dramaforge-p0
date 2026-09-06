import { useQuery } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";

import { fetchProjectAssets, type AssetRead } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";

export type MentionSuggestion = {
  asset_id: string;
  name: string;
  kind: string;
};

type AssetMentionInputProps = {
  projectId: string;
  value: string;
  onChange: (value: string) => void;
  onCreateBinding: (label: string, assetId: string, purpose: string) => void;
  purpose?: string;
  placeholder?: string;
  ariaLabel?: string;
};

const MENTION_RE = /@([\p{L}\p{N}_\-\u4e00-\u9fff]*)$/u;

/**
 * Phase 2 @Asset input: the user must pick a real Asset from autocomplete to
 * create a ShotReferenceBinding. Typed-but-unbound @text is marked as
 * "未解析引用" and never silently becomes a binding.
 */
export function AssetMentionInput({
  projectId,
  value,
  onChange,
  onCreateBinding,
  purpose = "identity",
  placeholder = "@输入资产名…",
  ariaLabel = "提示词（@ 引用资产）",
}: AssetMentionInputProps) {
  const [open, setOpen] = useState(false);
  const [boundLabels, setBoundLabels] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const assets = useQuery({
    queryKey: queryKeys.asset.mentions(projectId),
    queryFn: () => fetchProjectAssets(projectId),
    enabled: Boolean(projectId) && projectId !== "demo",
  });

  const currentMention = useMemo(() => {
    const match = value.match(MENTION_RE);
    return match ? match[1].toLowerCase() : "";
  }, [value]);

  const suggestions = useMemo<MentionSuggestion[]>(() => {
    const rows = assets.data ?? [];
    const matched = currentMention
      ? rows.filter((asset) => asset.name.toLowerCase().includes(currentMention))
      : rows;
    return matched.slice(0, 8).map((asset) => ({
      asset_id: asset.id,
      name: asset.name,
      kind: asset.kind,
    }));
  }, [assets.data, currentMention]);

  const unresolved = useMemo(() => {
    const tokens = value.match(/@([\p{L}\p{N}_\-\u4e00-\u9fff]+)/gu) ?? [];
    return tokens.map((token) => token.slice(1)).filter((name) => !boundLabels.includes(name));
  }, [value, boundLabels]);

  const pick = (asset: AssetRead) => {
    const token = currentMention;
    const before = value.slice(0, value.length - token.length - 1);
    const next = `${before}@${asset.name}`;
    onChange(next);
    setBoundLabels((labels) => [...labels, asset.name]);
    setOpen(false);
    onCreateBinding(`@${asset.name}`, asset.id, purpose);
    inputRef.current?.focus();
  };

  return (
    <div className="qc-mention-input" data-testid="asset-mention-input">
      <input
        ref={inputRef}
        aria-label={ariaLabel}
        value={value}
        placeholder={placeholder}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && currentMention !== undefined && suggestions.length > 0 && (
        <ul className="qc-mention-options" role="listbox" data-testid="mention-options">
          {suggestions.map((suggestion) => (
            <li
              key={suggestion.asset_id}
              role="option"
              aria-selected="false"
              onMouseDown={(event) => {
                event.preventDefault();
                const asset = (assets.data ?? []).find((item) => item.id === suggestion.asset_id);
                if (asset) pick(asset);
              }}
            >
              <strong>{suggestion.name}</strong>
              <span>{suggestion.kind}</span>
            </li>
          ))}
        </ul>
      )}
      {unresolved.length > 0 && (
        <p className="qc-mention-unresolved" data-testid="mention-unresolved">
          未解析引用：{unresolved.map((name) => `@${name}`).join("、")}（从建议中选择才会建立绑定）
        </p>
      )}
    </div>
  );
}
