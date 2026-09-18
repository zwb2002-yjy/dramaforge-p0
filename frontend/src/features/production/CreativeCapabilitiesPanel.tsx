import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

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
  /** Freeze target. Defaults to the Shot, which is the more specific scope. */
  scope?: "scene" | "shot";
};

/** CC10 functional UI: Genre / Style / Shot Language / Quality Policy / Skills.
 *
 * A user-explicit selection is frozen via POST; nothing is applied silently.
 * Read-only exposure includes both provenance and the compiled effective
 * intent that production will consume. No Provider call is made here.
 *
 * The freeze target is exactly one canonical scope. A Scene freeze is the
 * shared configuration the Scene's Shots inherit; a Shot freeze is the
 * override for that Shot only. Both scopes write the same frozen provenance
 * onto existing Scene/Shot state — there is no second capability system — and
 * the execution plan resolves Project + Scene + Shot into one effective
 * creative intent when it freezes a run snapshot.
 */
export function CreativeCapabilitiesPanel({
  projectId,
  sceneId,
  shotId,
  scope = "shot",
}: CreativeCapabilitiesPanelProps) {
  const qc = useQueryClient();
  const [genre, setGenre] = useState("");
  const [style, setStyle] = useState("");
  const [shotLanguage, setShotLanguage] = useState("");
  const [quality, setQuality] = useState("");
  const [skills, setSkills] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);

  const targetScope = scope === "scene" ? "scene" : "shot";
  const targetId = (targetScope === "scene" ? sceneId : shotId) ?? null;

  const catalog = useQuery({
    queryKey: queryKeys.production.creativeCatalog(projectId),
    queryFn: () => fetchCreativeCapabilityCatalog(projectId),
    enabled: Boolean(projectId),
  });
  const provenance = useQuery({
    queryKey: queryKeys.production.provenance(projectId, targetId, targetScope),
    queryFn: () =>
      fetchCreativeProvenance(
        projectId,
        targetScope === "scene"
          ? { scene_id: sceneId ?? undefined }
          : { shot_id: shotId ?? undefined },
      ),
    enabled: Boolean(projectId) && Boolean(targetId),
  });
  const prov = provenance.data?.creative_capabilities ?? {};
  // A Scene freeze is inherited by its Shots; showing where the displayed
  // value comes from keeps the two scopes distinguishable to the user.
  const inheritedFromScene = targetScope === "shot" && provenance.data?.target === "scene";
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

  // Seed the draft from what is already frozen for this exact scope so the
  // Owner edits the current configuration instead of an empty form. Selecting
  // a value is never implied by the read: the freeze stays an explicit action.
  const frozenGenre = summary.genre?.key ?? "";
  const frozenStyle = summary.style?.key ?? "";
  const frozenShotLanguage = summary.shot_language?.key ?? "";
  const frozenQuality = summary.quality_policy?.key ?? "";
  const frozenSkills = (summary.skill_guidance ?? []).map((entry) => entry.skill_key).join(",");
  useEffect(() => {
    setGenre(frozenGenre);
    setStyle(frozenStyle);
    setShotLanguage(frozenShotLanguage);
    setQuality(frozenQuality);
    setSkills(frozenSkills ? frozenSkills.split(",") : []);
    // Draft state follows the canonical frozen value, never local-only input.
  }, [frozenGenre, frozenStyle, frozenShotLanguage, frozenQuality, frozenSkills]);

  const freeze = useMutation({
    mutationFn: () =>
      freezeCreativeCapabilities(projectId, {
        genre_key: genre || undefined,
        style_key: style || undefined,
        shot_language_key: shotLanguage || undefined,
        quality_policy_key: quality || undefined,
        skill_keys: skills,
        // Freeze and read must address the same canonical target.  A Scene
        // freeze is the shared configuration its Shots inherit; a Shot freeze
        // is that Shot's override.  Exactly one target is ever sent.
        ...(targetScope === "scene"
          ? { scene_id: sceneId ?? undefined }
          : { shot_id: shotId ?? undefined }),
      }),
    onSuccess: () => {
      setMsg("已冻结有效创作意图与来源说明。");
      void qc.invalidateQueries({
        queryKey: queryKeys.production.provenance(projectId, targetId, targetScope),
      });
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
        <span className="fact-source-badge" data-testid="creative-capability-scope">
          {targetScope === "scene" ? "场景配置（镜头继承）" : "当前镜头配置"}
        </span>
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
          <small>
            {inheritedFromScene ? "当前生效的创作意图（来自场景配置）" : "当前冻结的创作意图"}
          </small>
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
