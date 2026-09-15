import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "../../components/ui";
import { creativeCapabilityLabels } from "../../lib/creativeLabels";
import { queryKeys } from "../../lib/queryKeys";
import { fetchCreativeProvenance, freezeCreativeCapabilities } from "./workflow-api";

const GENRES = [
  "short_drama_romance_v1",
  "short_drama_suspense_v1",
  "short_drama_revenge_v1",
  "dynamic_comic_v1",
  "commercial_product_v1",
  "music_montage_v1",
];

const STYLES = [
  "cinematic_realism_v1",
  "chinese_drama_v1",
  "film_noir_v1",
  "hong_kong_urban_v1",
  "cyberpunk_neon_v1",
  "chinese_ancient_v1",
  "anime_clean_v1",
  "dynamic_comic_v1",
  "commercial_premium_v1",
  "documentary_natural_v1",
];

const SHOT_LANGUAGES = [
  "dialogue_classic_coverage_v1",
  "subjective_tension_v1",
  "handheld_documentary_v1",
  "action_dynamic_v1",
  "commercial_product_v1",
  "montage_rhythmic_v1",
];

const QUALITY_POLICIES = [
  "dialogue_identity_quality_v1",
  "multi_character_quality_v1",
  "action_motion_quality_v1",
  "comic_consistency_quality_v1",
  "commercial_product_quality_v1",
];

const SKILLS = [
  "short-drama-hook-v1",
  "suspense-reversal-v1",
  "emotional-conflict-v1",
  "adaptation-compression-v1",
  "dialogue-scene-direction-v1",
  "action-scene-direction-v1",
  "emotional-performance-v1",
  "montage-direction-v1",
  "character-consistency-v1",
  "continuity-guardian-v1",
];

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
            {GENRES.map((g) => (
              <option key={g} value={g}>
                {creativeCapabilityLabels.genre(g)}
              </option>
            ))}
          </select>
        </label>
        <label>
          风格
          <select aria-label="风格" value={style} onChange={(e) => setStyle(e.target.value)}>
            <option value="">默认</option>
            {STYLES.map((s) => (
              <option key={s} value={s}>
                {creativeCapabilityLabels.style(s)}
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
            {SHOT_LANGUAGES.map((s) => (
              <option key={s} value={s}>
                {creativeCapabilityLabels.shotLanguage(s)}
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
            {QUALITY_POLICIES.map((q) => (
              <option key={q} value={q}>
                {creativeCapabilityLabels.qualityPolicy(q)}
              </option>
            ))}
          </select>
        </label>

        <div className="creative-skill-list">
          <small>启用的创作技能</small>
          {SKILLS.map((key) => (
            <label key={key} className="creative-skill-toggle">
              <input
                type="checkbox"
                checked={skills.includes(key)}
                onChange={() => toggleSkill(key)}
              />
              <span>{creativeCapabilityLabels.skill(key)}</span>
            </label>
          ))}
        </div>

        <Button
          tone="primary"
          onClick={() => freeze.mutate()}
          disabled={freeze.isPending || !targetId}
        >
          {freeze.isPending ? "冻结中…" : "冻结创意能力"}
        </Button>
        {msg && (
          <div className="canvas-save-message" role="status">
            {msg}
          </div>
        )}
      </div>

      {prov && Object.keys(prov).length > 0 && (
        <div className="creative-provenance" data-testid="creative-provenance">
          <small>当前冻结的创作意图</small>
          <ul data-testid="creative-provenance-summary" className="creative-provenance-summary">
            {summary.genre?.key && (
              <li>创作类型：{creativeCapabilityLabels.genre(summary.genre.key)}</li>
            )}
            {summary.style?.key && (
              <li>风格：{creativeCapabilityLabels.style(summary.style.key)}</li>
            )}
            {summary.shot_language?.key && (
              <li>镜头语言：{creativeCapabilityLabels.shotLanguage(summary.shot_language.key)}</li>
            )}
            {summary.quality_policy?.key && (
              <li>
                质量策略：{creativeCapabilityLabels.qualityPolicy(summary.quality_policy.key)}
              </li>
            )}
            {summary.skill_guidance?.map((entry) => (
              <li key={entry.skill_key}>
                {creativeCapabilityLabels.skill(entry.skill_key)}
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
