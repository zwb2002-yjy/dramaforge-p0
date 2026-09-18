import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import "./creative-settings.css";
import { Button, Checkbox, Disclosure, Field, Select } from "../../components/ui";
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
  const inheritedFromProject = provenance.data?.target === "project";
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
  }, [targetId, frozenGenre, frozenStyle, frozenShotLanguage, frozenQuality, frozenSkills]);

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
      setMsg("设置已保存，后续生成时生效。");
      void qc.invalidateQueries({
        queryKey: queryKeys.production.provenance(projectId, targetId, targetScope),
      });
    },
    onError: (e: Error) => setMsg(`保存失败：${e.message}`),
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
          <h3>局部创作设置</h3>
        </div>
        <span className="fact-source-badge" data-testid="creative-capability-scope">
          {targetScope === "scene" ? "场景配置（镜头继承）" : "当前镜头配置"}
        </span>
      </header>

      <div className="creative-capability-form">
        <Field>
          创作类型
          <Select aria-label="创作类型" value={genre} onChange={(e) => setGenre(e.target.value)}>
            <option value="">默认</option>
            {(catalog.data?.genres ?? []).map((item) => (
              <option key={item.key} value={item.key} title={item.description}>
                {item.display_name}
              </option>
            ))}
          </Select>
        </Field>
        <Field>
          风格
          <Select aria-label="风格" value={style} onChange={(e) => setStyle(e.target.value)}>
            <option value="">默认</option>
            {(catalog.data?.styles ?? []).map((item) => (
              <option key={item.key} value={item.key} title={item.description}>
                {item.display_name}
              </option>
            ))}
          </Select>
        </Field>
        <Disclosure title="更多生成设置">
          <Field>
            镜头语言
            <Select
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
            </Select>
          </Field>
          <Field>
            质量策略
            <Select
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
            </Select>
          </Field>

          <div className="creative-skill-list">
            <small>启用的创作技能</small>
            {(catalog.data?.skills ?? []).map((item) => (
              <Field key={item.key} className="creative-skill-toggle" title={item.description}>
                <Checkbox
                  type="checkbox"
                  checked={skills.includes(item.key)}
                  onChange={() => toggleSkill(item.key)}
                />
                <span>{item.display_name}</span>
              </Field>
            ))}
          </div>
        </Disclosure>
        <Button
          tone="primary"
          onClick={() => freeze.mutate()}
          disabled={
            freeze.isPending ||
            !targetId ||
            !catalog.data ||
            provenance.isPending ||
            provenance.isError
          }
        >
          {freeze.isPending ? "保存中…" : "保存局部设置"}
        </Button>
        {msg && (
          <div className="canvas-save-message" role="status">
            {msg}
          </div>
        )}
        {provenance.isError && (
          <p role="alert">
            无法读取当前设置，请重试后再保存。
            <Button onClick={() => void provenance.refetch()}>重试</Button>
          </p>
        )}
        {catalog.isError && (
          <div className="flash err" role="alert">
            无法加载创意能力目录：{String(catalog.error)}
          </div>
        )}
      </div>

      {prov && Object.keys(prov).length > 0 && (
        <Disclosure title="已保存的设置" testId="creative-provenance">
          <small>
            {inheritedFromProject
              ? "沿用项目设置"
              : inheritedFromScene
                ? "沿用场景设置"
                : "当前设置"}
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
            <summary>技术记录</summary>
            <pre>{JSON.stringify(prov, null, 2)}</pre>
          </details>
        </Disclosure>
      )}
    </div>
  );
}
