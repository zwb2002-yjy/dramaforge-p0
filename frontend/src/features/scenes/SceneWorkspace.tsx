import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { DirectorSidebar } from "../director/DirectorSidebar";
import { CinematicCanvas } from "../shots/CinematicCanvas";
import { ShotStrip } from "../shots/ShotStrip";
import type { ReferenceResolutionState } from "../../components/assets/AssetReferencePicker";
import type { ShotExecutionReference } from "../shots/api";
import { fetchSceneWorkspace, type SceneWorkspaceRead, type ShotLite } from "./api";

type SceneWorkspaceProps = {
  projectId: string;
  sceneId: string;
};

type ShotReferenceContext = {
  references: ShotExecutionReference[];
  ready: boolean;
};

const EMPTY_REFERENCE_CONTEXT: ShotReferenceContext = { references: [], ready: false };

function sameReferences(left: ShotExecutionReference[], right: ShotExecutionReference[]): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/**
 * Scene workspace composition root.
 *
 * The selected Shot is the only interaction identity shared by all three
 * columns.  Scene/Shot/Artifact/NodeRun state stays in the scene snapshot;
 * the small per-shot map is only a draft transport context for references
 * while a picker is resolving them.
 */
export function SceneWorkspace({ projectId, sceneId }: SceneWorkspaceProps) {
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [referenceDrafts, setReferenceDrafts] = useState<Record<string, ShotReferenceContext>>({});
  const workspace = useQuery({
    queryKey: ["scene-workspace", projectId, sceneId],
    queryFn: () => fetchSceneWorkspace(projectId, sceneId),
    enabled: Boolean(projectId) && Boolean(sceneId) && projectId !== "demo",
  });
  useEffect(() => {
    setSelectedShotId(null);
    setReferenceDrafts({});
  }, [projectId, sceneId]);
  const data = workspace.data as SceneWorkspaceRead | undefined;
  const shots = data?.shots ?? [];
  const selected = (shots.find((shot) => shot.id === selectedShotId) ??
    shots[0] ??
    null) as ShotLite | null;
  const selectedShotKey = selected?.id ?? null;

  // The fallback first Shot is still a selected Shot from the user's point of
  // view. Establish a draft context as soon as the snapshot arrives. Drafts
  // are keyed by Shot so returning to A can restore A's in-flight references,
  // while a switch to B can never read A's context.
  useEffect(() => {
    if (selectedShotKey === null) return;
    setReferenceDrafts((current) =>
      current[selectedShotKey]
        ? current
        : { ...current, [selectedShotKey]: { ...EMPTY_REFERENCE_CONTEXT } },
    );
  }, [selectedShotKey]);

  const selectShot = useCallback((shotId: string) => {
    setSelectedShotId(shotId);
  }, []);

  const updateSelectedReferences = useCallback(
    (references: ShotExecutionReference[]) => {
      if (selectedShotKey === null) return;
      setReferenceDrafts((current) => {
        const previous = current[selectedShotKey] ?? EMPTY_REFERENCE_CONTEXT;
        if (sameReferences(previous.references, references)) return current;
        return {
          ...current,
          [selectedShotKey]: {
            references: references.map((reference) => ({ ...reference })),
            ready: previous.ready,
          },
        };
      });
    },
    [selectedShotKey],
  );
  const updateReferenceResolutionState = useCallback(
    (state: ReferenceResolutionState) => {
      if (selectedShotKey === null) return;
      setReferenceDrafts((current) => {
        const previous = current[selectedShotKey] ?? EMPTY_REFERENCE_CONTEXT;
        const ready = state === "ready";
        if (previous.ready === ready) return current;
        return {
          ...current,
          [selectedShotKey]: { ...previous, ready },
        };
      });
    },
    [selectedShotKey],
  );
  const selectedReferenceContext =
    (selectedShotKey && referenceDrafts[selectedShotKey]) || EMPTY_REFERENCE_CONTEXT;
  const selectedReferences = selectedReferenceContext.references;
  const selectedReferencesReady = selectedReferenceContext.ready;
  const candidates = selected ? (data?.candidates?.[selected.id] ?? []) : [];
  const trace = selected ? (data?.trace?.[selected.id] ?? []) : [];

  return (
    <div className="qc-scene-workspace" data-testid="scene-workspace">
      <header className="qc-page-heading">
        <p>场景工作区</p>
        <h1>{data?.scene.location_name ?? "场景"}</h1>
        <span>
          {data?.scene.episode_number}.{data?.scene.scene_number} · {data?.scene.time_of_day}
        </span>
        <a
          className="qc-overview-primary"
          href={`/projects/${projectId}/edit`}
          data-testid="scene-edit-entry"
        >
          进入剪辑
        </a>
      </header>

      {workspace.isError && (
        <div className="flash err">无法读取场景工作区：{String(workspace.error)}</div>
      )}
      {workspace.isLoading && !data && (
        <p className="qc-scene-loading" data-testid="scene-workspace-loading">
          正在读取场景与镜头事实…
        </p>
      )}

      <div className="qc-scene-layout" data-selected-shot-id={selectedShotKey ?? undefined}>
        <aside
          className="qc-scene-navigation"
          data-testid="scene-navigation"
          aria-label="场景镜头导航"
        >
          <section className="qc-scene-context" data-testid="scene-context">
            <span className="director-stage-kicker">Scene context</span>
            <strong>
              {data?.scene.episode_number}.{data?.scene.scene_number} ·{" "}
              {data?.scene.location_name ?? "场景"}
            </strong>
            <span>{data?.scene.time_of_day ?? "—"}</span>
            {data?.scene.synopsis && <p>{data.scene.synopsis}</p>}
          </section>
          <ShotStrip shots={shots} selectedShotId={selectedShotKey} onSelectShot={selectShot} />
        </aside>
        <CinematicCanvas
          projectId={projectId}
          shot={selected}
          candidates={candidates}
          trace={trace}
        />
        <DirectorSidebar
          projectId={projectId}
          shot={selected}
          candidates={candidates}
          trace={trace}
          references={selectedReferences}
          referencesReady={selectedReferencesReady}
          onReferencesChange={updateSelectedReferences}
          onResolutionStateChange={updateReferenceResolutionState}
          onWorkspaceRefresh={async () => {
            await workspace.refetch();
          }}
        />
      </div>
    </div>
  );
}
