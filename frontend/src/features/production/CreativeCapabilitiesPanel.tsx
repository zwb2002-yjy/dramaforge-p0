import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "../../components/ui";
import { queryKeys } from "../../lib/queryKeys";
import {
  fetchCreativeCapabilityCatalog,
  fetchCreativeProvenance,
  freezeCreativeCapabilities,
  type CreativeCapabilityCatalogItem,
} from "./workflow-api";

export type CreativeCapabilitiesPanelProps = {
  projectId: string;
  sceneId?: string | null;
  shotId?: string | null;
};

/** CC10 functional UI: Genre / Style / Shot Language / Quality Policy / Skills.
 *
 * A user-explicit selection is frozen via POST; nothing is applied silently.
 * Read-only exposure includes both provenance and the compiled effective
 * intent that production will consume. No Provider call is made here.
 */
export function CreativeCapabilitiesPanel({
  projectId,
  sceneId,
  shotId,
}: CreativeCapabilitiesPanelProps) {
  const qc = useQueryClient();
  const [genre, setGenre] = useState("");
  const [style, setStyle] = useState("");
  const [shotLanguage, setShotLanguage] = useState("");
  const [quality, setQuality] = useState("");
  const [skills, setSkills] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  const targetId = shotId ?? sceneId ?? null;
  const catalog = useQuery({
    queryKey: queryKeys.production.creativeCatalog(projectId),
    queryFn: () => fetchCreativeCapabilityCatalog(projectId),
    enabled: Boolean(projectId),
  });
  const provenance = useQuery({
    queryKey: queryKeys.production.provenance(projectId, targetId),
    queryFn: () =>
      fetchCreativeProvenance(projectId, {
        shot_id: shotId ?? undefined,
        scene_id: sceneId ?? undefined,
      }),
    enabled: Boolean(projectId) && Boolean(targetId),
  });
  const prov = provenance.data?.creative_capabilities ?? {};
  // The provenance payload is an open record; these are the parts the panel
  // renders as readable labels before the raw record.
  const summary = prov as {
    genre?: { key?: string };
    style?: { key?: string };
    shot_language?: { key?: string };
    quality_policy?: { key?: string };
    skill_guidance?: Array<{ skill_key: string; strategy?: string }>;
  };
  const capabilityLabel = (items: CreativeCapabilityCatalogItem[] | undefined, key: string) =>
    items?.find((item) => item.key === key)?.display_name ?? key.replace(/[_-]+/g, " ");

  const freeze = useMutation({
    mutationFn: () =>
      freezeCreativeCapabilities(projectId, {
        genre_key: genre || undefined,
        style_key: style || undefined,
        shot_language_key: shotLanguage || undefined,
        quality_policy_key: quality || undefined,
        skill_keys: skills,
        shot_id: shotId ?? undefined,
        // Freeze and read must address the same canonical target.  When the
        // production page has a selected Shot it also knows its parent Scene;
        // sending both made the backend freeze the Scene while this panel read
        // the Shot provenance.
        scene_id: shotId ? undefined : (sceneId ?? undefined),
      }),
    onSuccess: () => {
      setMsg("已冻结有效创作意图与来源说明。");
      void qc.invalidateQueries({ queryKey: queryKeys.production.provenance(projectId, targetId) });
    },
    onError: (e: Error) => setMsg(`冻结失败：${e.message}`),
  });

  function toggleSkill(key: string) {
    setSkills((current) =>
      current.includes(key) ? current.filter((s) => s !== key) : [...current, key],
    );
  }

  return (
    <div className="creative-capabilities-panel" data-testid="creative-capabilities-panel">
      <header className="panel-header">
        <div>
          <h3>创意能力选择</h3>
        </div>
        <span className="fact-source-badge">人工指定</span>
      </header>

      <div className="creative-capability-form">
        <label>
          创作类型
          <select aria-label="创作类型" value={genre} onChange={(e) => setGenre(e.target.value)}>
            <option value="">默认</option>
            {(catalog.data?.genres ?? []).map((item) => (
              <option key={item.key} value={item.key} title={item.description}>
                {item.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          风格
          <select aria-label="风格" value={style} onChange={(e) => setStyle(e.target.value)}>
            <option value="">默认</option>
            {(catalog.data?.styles ?? []).map((item) => (
              <option key={item.key} value={item.key} title={item.description}>
                {item.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          镜头语言
          <select
            aria-label="镜头语言"
            value={shotLanguage}
            onChange={(e) => setShotLanguage(e.target.value)}
          >
            <option value="">默认</option>
            {(catalog.data?.shot_languages ?? []).map((item) => (
              <option key={item.key} value={item.key} title={item.description}>
                {item.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          质量策略
          <select
            aria-label="质量策略"
            value={quality}
            onChange={(e) => setQuality(e.target.value)}
          >
            <option value="">默认</option>
            {(catalog.data?.quality_policies ?? []).map((item) => (
              <option key={item.key} value={item.key} title={item.description}>
                {item.display_name}
              </option>
            ))}
          </select>
        </label>

        <div className="creative-skill-list">
          <small>启用的创作技能</small>
          {(catalog.data?.skills ?? []).map((item) => (
            <label key={item.key} className="creative-skill-toggle" title={item.description}>
              <input
                type="checkbox"
                checked={skills.includes(item.key)}
                onChange={() => toggleSkill(item.key)}
              />
              <span>{item.display_name}</span>
            </label>
          ))}
        </div>

        <Button
          tone="primary"
          onClick={() => freeze.mutate()}
          disabled={freeze.isPending || !targetId || !catalog.data}
        >
          {freeze.isPending ? "冻结中…" : "冻结创意能力"}
        </Button>
        {msg && (
          <div className="canvas-save-message" role="status">
            {msg}
          </div>
        )}
        {catalog.isError && (
          <div className="flash err" role="alert">
            无法加载创意能力目录：{String(catalog.error)}
          </div>
        )}
      </div>

      {prov && Object.keys(prov).length > 0 && (
        <div className="creative-provenance" data-testid="creative-provenance">
          <small>当前冻结的创作意图</small>
          <ul data-testid="creative-provenance-summary" className="creative-provenance-summary">
            {summary.genre?.key && (
              <li>创作类型：{capabilityLabel(catalog.data?.genres, summary.genre.key)}</li>
            )}
            {summary.style?.key && (
              <li>风格：{capabilityLabel(catalog.data?.styles, summary.style.key)}</li>
            )}
            {summary.shot_language?.key && (
              <li>
                镜头语言：
                {capabilityLabel(catalog.data?.shot_languages, summary.shot_language.key)}
              </li>
            )}
            {summary.quality_policy?.key && (
              <li>
                质量策略：
                {capabilityLabel(catalog.data?.quality_policies, summary.quality_policy.key)}
              </li>
            )}
            {summary.skill_guidance?.map((entry) => (
              <li key={entry.skill_key}>
                {capabilityLabel(catalog.data?.skills, entry.skill_key)}
                {entry.strategy ? `：${entry.strategy}` : ""}
              </li>
            ))}
          </ul>
          <details className="creative-provenance-raw">
            <summary>查看冻结的原始记录</summary>
            <pre>{JSON.stringify(prov, null, 2)}</pre>
          </details>
        </div>
      )}
    </div>
  );
}
