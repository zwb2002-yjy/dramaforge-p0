import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";

import { Button, Field, Textarea } from "../ui";
import { fetchProjectAssets, type AssetRead } from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import {
  createShotReference,
  deleteShotReference,
  fetchShotReferences,
  resolveShotReferences,
} from "../../features/assets/api";
import "./asset-reference-picker.css";

type AssetMentionInputProps = {
  projectId: string;
  shotId: string;
  stage: "image" | "video";
  value: string;
  onChange: (value: string) => void;
  onValidityChange?: (ready: boolean) => void;
  purpose?: string;
  placeholder?: string;
  ariaLabel?: string;
  label?: string;
};

const TOKEN = /@[\p{L}\p{N}_-]*/gu;

/** A confirmed suggestion writes the existing binding; text alone never resolves an Asset. */
export function AssetMentionInput({
  projectId,
  shotId,
  stage,
  value,
  onChange,
  onValidityChange,
  purpose = "identity",
  placeholder = "输入提示词，使用 @ 选择素材",
  ariaLabel = "提示词（@ 引用资产）",
  label = ariaLabel,
}: AssetMentionInputProps) {
  const listId = useId();
  const input = useRef<HTMLTextAreaElement>(null);
  const mounted = useRef(true);
  const scopeKey = `${projectId}:${shotId}:${stage}`;
  const currentScope = useRef(scopeKey);
  currentScope.current = scopeKey;
  const [settling, setSettling] = useState(false);
  useEffect(() => {
    mounted.current = true;
    setSettling(false);
    return () => {
      mounted.current = false;
    };
  }, [scopeKey]);
  const [cursor, setCursor] = useState(value.length);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const client = useQueryClient();
  const tokens = [...new Set(value.match(TOKEN) ?? [])];
  const match = value.slice(0, cursor).match(/@([\p{L}\p{N}_-]*)$/u);
  const referenceActive = tokens.length > 0 || (open && match !== null);
  const assets = useQuery({
    queryKey: queryKeys.asset.picker(projectId),
    queryFn: () => fetchProjectAssets(projectId),
    enabled: open && match !== null,
  });
  const bindings = useQuery({
    queryKey: queryKeys.asset.shotReferences(projectId, shotId),
    queryFn: () => fetchShotReferences(projectId, shotId),
    enabled: referenceActive,
  });
  const resolution = useQuery({
    queryKey: queryKeys.asset.referenceResolution(projectId, shotId),
    queryFn: () => resolveShotReferences(projectId, shotId),
    enabled: referenceActive,
  });
  const allBindings = Array.isArray(bindings.data) ? bindings.data : [];
  const rows = allBindings.filter((row) => row.stage === "both" || row.stage === stage);
  const resolved = Array.isArray(resolution.data) ? resolution.data : [];
  const unresolved = tokens.filter((token) => {
    const matches = rows.filter((row) => row.label === token);
    return matches.length !== 1 || !resolved.some((ref) => ref.binding_id === matches[0].id);
  });
  const options = (Array.isArray(assets.data) ? assets.data : [])
    .filter(
      (asset) =>
        asset.project_id === projectId &&
        asset.status !== "recycled" &&
        (!match?.[1] || asset.name.toLocaleLowerCase().includes(match[1].toLocaleLowerCase())),
    )
    .slice(0, 8);
  const visible = open && match !== null;
  const invalidate = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: queryKeys.asset.shotReferences(projectId, shotId) }),
      client.invalidateQueries({
        queryKey: queryKeys.asset.referenceResolution(projectId, shotId),
      }),
      client.invalidateQueries({ queryKey: queryKeys.scene.workspaceRoot(projectId) }),
    ]);
  const create = useMutation({
    retry: false,
    mutationFn: async (asset: AssetRead) => {
      const existing = rows.find(
        (row) =>
          row.asset_id === asset.id &&
          row.purpose === purpose &&
          row.stage === stage &&
          /^@[\p{L}\p{N}_-]+$/u.test(row.label),
      );
      if (existing) return existing;
      const base = `@${asset.name.replace(/[^\p{L}\p{N}_-]/gu, "_").slice(0, 130) || "素材"}`;
      let label = base;
      for (let index = 2; allBindings.some((row) => row.label === label); index += 1)
        label = `${base}_${index}`;
      return createShotReference(projectId, shotId, {
        asset_id: asset.id,
        purpose,
        stage,
        label,
        sort_order: allBindings.reduce((max, row) => Math.max(max, row.sort_order), -1) + 1,
        resolution_mode: "current_formal",
      });
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteShotReference(projectId, id),
    retry: false,
  });
  const pending = create.isPending || remove.isPending || settling;
  const ready =
    !tokens.length ||
    (!pending &&
      bindings.isSuccess &&
      resolution.isSuccess &&
      !resolution.isFetching &&
      !unresolved.length);
  useEffect(() => {
    onValidityChange?.(ready);
  }, [ready, onValidityChange]);
  async function pick(asset: AssetRead) {
    if (!match || pending) return;
    const before = value.slice(0, cursor - match[0].length);
    const after = value.slice(cursor);
    setSettling(true);
    try {
      const saved = await create.mutateAsync(asset);
      if (!mounted.current || currentScope.current !== scopeKey) {
        await invalidate();
        return;
      }
      onChange(`${before}${saved.label} ${after}`);
      setOpen(false);
      await invalidate();
      input.current?.focus();
    } catch {
      await invalidate();
      /* Mutation feedback keeps the typed draft intact. */
    } finally {
      if (mounted.current && currentScope.current === scopeKey) setSettling(false);
    }
  }
  async function removeMention(label: string, id: string) {
    setSettling(true);
    try {
      await remove.mutateAsync(id);
      if (!mounted.current || currentScope.current !== scopeKey) {
        await invalidate();
        return;
      }
      onChange(value.replace(TOKEN, (token) => (token === label ? "" : token)));
      await invalidate();
    } catch {
      /* A refused delete keeps both the label and the server binding. */
    } finally {
      if (mounted.current && currentScope.current === scopeKey) setSettling(false);
    }
  }
  return (
    <div className="df-mention" data-testid="asset-mention-input" data-stage={stage}>
      <Field>
        {label}
        <Textarea
          ref={input}
          rows={4}
          aria-label={ariaLabel}
          value={value}
          placeholder={placeholder}
          disabled={pending}
          aria-autocomplete="list"
          aria-controls={visible ? listId : undefined}
          aria-expanded={visible}
          aria-activedescendant={
            visible && options.length
              ? `${listId}-${Math.min(active, options.length - 1)}`
              : undefined
          }
          onChange={(event) => {
            onChange(event.target.value);
            setCursor(event.target.selectionStart);
            setActive(0);
            setOpen(true);
          }}
          onSelect={(event) => setCursor(event.currentTarget.selectionStart)}
          onBlur={() => setOpen(false)}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (!visible) return;
            if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
            }
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              setActive(
                (index) =>
                  (index + (event.key === "ArrowDown" ? 1 : -1) + options.length) %
                  Math.max(1, options.length),
              );
            }
            if (event.key === "Enter" && !event.shiftKey && options.length) {
              event.preventDefault();
              void pick(options[Math.min(active, options.length - 1)]);
            }
          }}
        />
      </Field>
      {visible && (
        <ul
          className="df-mention-options"
          id={listId}
          role="listbox"
          aria-label="选择引用素材"
          data-testid="mention-options"
        >
          {options.map((asset, index) => (
            <li
              key={asset.id}
              role="option"
              id={`${listId}-${index}`}
              aria-selected={active === index}
            >
              <Button
                tone="ghost"
                tabIndex={-1}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => void pick(asset)}
              >
                {asset.name}
                <small>
                  {asset.kind === "character" ? "角色" : asset.kind === "scene" ? "场景" : "素材"} ·{" "}
                  {asset.id.slice(0, 8)}
                </small>
              </Button>
            </li>
          ))}
          {!options.length && (
            <li>
              {assets.isError
                ? "素材读取失败，请稍后重试"
                : assets.isPending
                  ? "正在读取素材…"
                  : "没有匹配的素材"}
            </li>
          )}
        </ul>
      )}
      {tokens.length > 0 && (
        <div className="df-mention-chips" aria-label={`${ariaLabel}中的引用`}>
          {tokens.map((token) => {
            const row = rows.find((item) => item.label === token);
            return (
              <span key={token} data-resolved={!unresolved.includes(token)}>
                {token}
                {row && (
                  <Button
                    tone="ghost"
                    aria-label={`删除提示词引用 ${token}`}
                    disabled={pending}
                    onClick={() => void removeMention(token, row.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Delete" || event.key === "Backspace") {
                        event.preventDefault();
                        void removeMention(token, row.id);
                      }
                    }}
                  >
                    移除
                  </Button>
                )}
              </span>
            );
          })}
        </div>
      )}
      {!!unresolved.length && (
        <p className="df-ref-note err" data-testid="mention-unresolved">
          未解析引用：{unresolved.join("、")}。请从建议中选择，或修复已失效的素材绑定。
        </p>
      )}
      {pending && (
        <p className="df-ref-note" role="status">
          正在保存引用…
        </p>
      )}
      {(create.isError || remove.isError) && (
        <p className="df-ref-note err" role="alert">
          引用保存失败：{String((create.error ?? remove.error)?.message ?? "请重新读取后处理")}
        </p>
      )}
    </div>
  );
}
