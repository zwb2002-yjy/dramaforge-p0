import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  fetchCreativeProvenance,
  freezeCreativeCapabilities,
} from "../workbench/api";

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
 * Read-only exposure of the frozen provenance follows the same "never hidden
 * skill, never override" boundary. No Provider call is made here.
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
    queryKey: ["creative-provenance", projectId, targetId],
    queryFn: () => fetchCreativeProvenance(projectId, { shot_id: shotId ?? undefined, scene_id: sceneId ?? undefined }),
    enabled: Boolean(projectId) && Boolean(targetId),
  });
  const prov = provenance.data?.creative_capabilities ?? {};

  const freeze = useMutation({
    mutationFn: () =>
      freezeCreativeCapabilities(projectId, {
        genre_key: genre || undefined,
        style_key: style || undefined,
        shot_language_key: shotLanguage || undefined,
        quality_policy_key: quality || undefined,
        skill_keys: skills,
        scene_id: sceneId ?? undefined,
        shot_id: shotId ?? undefined,
      }),
    onSuccess: () => {
      setMsg("已冻结创意能力与 provenance。");
      void qc.invalidateQueries({ queryKey: ["creative-provenance", projectId, targetId] });
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
          <span className="director-stage-kicker">Creative Capabilities</span>
          <h3>创意能力选择</h3>
        </div>
        <span className="fact-source-badge">user-explicit</span>
      </header>

      <div className="creative-capability-form">
        <label>Genre
          <select aria-label="Genre" value={genre} onChange={(e) => setGenre(e.target.value)}>
            <option value="">默认</option>
            {GENRES.map((g) => <option key={g} value={g}>{g}</option>)}
          </select>
        </label>
        <label>Style
          <select aria-label="Style" value={style} onChange={(e) => setStyle(e.target.value)}>
            <option value="">默认</option>
            {STYLES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>Shot Language
          <select aria-label="Shot Language" value={shotLanguage} onChange={(e) => setShotLanguage(e.target.value)}>
            <option value="">默认</option>
            {SHOT_LANGUAGES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>Quality Policy
          <select aria-label="Quality Policy" value={quality} onChange={(e) => setQuality(e.target.value)}>
            <option value="">默认</option>
            {QUALITY_POLICIES.map((q) => <option key={q} value={q}>{q}</option>)}
          </select>
        </label>

        <div className="creative-skill-list">
          <small>Active Skills</small>
          {SKILLS.map((key) => (
            <label key={key} className="creative-skill-toggle">
              <input type="checkbox" checked={skills.includes(key)} onChange={() => toggleSkill(key)} />
              <span>{key}</span>
            </label>
          ))}
        </div>

        <button type="button" className="df-btn primary" onClick={() => freeze.mutate()} disabled={freeze.isPending || !targetId}>
          {freeze.isPending ? "冻结中…" : "冻结创意能力"}
        </button>
        {msg && <div className="canvas-save-message" role="status">{msg}</div>}
      </div>

      {prov && Object.keys(prov).length > 0 && (
        <div className="creative-provenance" data-testid="creative-provenance">
          <small>当前冻结 provenance</small>
          <pre>{JSON.stringify(prov, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
