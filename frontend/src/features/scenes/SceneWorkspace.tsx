import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { DirectorSidebar } from "../director/DirectorSidebar";
import type { ReferenceResolutionState } from "../../components/assets/AssetReferencePicker";
import { CinematicCanvas } from "../shots/CinematicCanvas";
import { ShotCandidateTray } from "../shots/ShotCandidateTray";
import { ShotStrip } from "../shots/ShotStrip";
import type { ShotCandidate } from "../shots/shotCandidates";
import type { ShotExecutionReference, ShotLite } from "../shots/api";
import { fetchSceneWorkspace, type SceneWorkspaceRead } from "./api";
import { queryKeys } from "../../lib/queryKeys";

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
 * Stage-first Scene/Shot Workbench composition.
 *
 * SceneWorkspaceRead remains the only server snapshot. selectedShotId, local
 * candidate preview, and reference resolution drafts are view state and are
 * scoped to the current Scene; none create a second media or production fact
 * source.
 */
export function SceneWorkspace({ projectId, sceneId }: SceneWorkspaceProps) {
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [previewCandidate, setPreviewCandidate] = useState<ShotCandidate | null>(null);
  const [referenceDrafts, setReferenceDrafts] = useState<Record<string, ShotReferenceContext>>({});
  const workspace = useQuery({
    queryKey: queryKeys.scene.workspace(projectId, sceneId),
    queryFn: () => fetchSceneWorkspace(projectId, sceneId),
    enabled: Boolean(projectId) && Boolean(sceneId) && projectId !== "demo",
  });

  useEffect(() => {
    setSelectedShotId(null);
    setPreviewCandidate(null);
    setReferenceDrafts({});
  }, [projectId, sceneId]);

  const data = workspace.data as SceneWorkspaceRead | undefined;
  const shots = data?.shots ?? [];
  const selected = (shots.find((shot) => shot.id === selectedShotId) ??
    shots[0] ??
    null) as ShotLite | null;
  const selectedShotKey = selected?.id ?? null;
  const selectedBindingRows = selected ? (data?.references?.[selected.id] ?? []) : [];
  const selectedShotHasBindings = selectedBindingRows.length > 0;

  // A fallback first Shot is still a selected Shot from the user's point of
  // view. Drafts are keyed by Shot so returning to A cannot read B's context.
  useEffect(() => {
    if (selectedShotKey === null) return;
    setReferenceDrafts((current) =>
      current[selectedShotKey]
        ? current
        : {
            ...current,
            [selectedShotKey]: {
              ...EMPTY_REFERENCE_CONTEXT,
              // An unbound Shot has no server resolution to wait for. Keep
              // generation available while the References tab remains lazy;
              // bound Shots stay fail-closed until AssetReferencePicker has
              // resolved their concrete artifacts.
              ready: !selectedShotHasBindings,
            },
          },
    );
  }, [selectedShotHasBindings, selectedShotKey]);

  useEffect(() => {
    // Canvas previews are local and must never bleed into a newly selected
    // Shot. Formal confirmation also clears this state before refetching.
    setPreviewCandidate(null);
  }, [selectedShotKey]);

  const selectShot = useCallback((shotId: string) => {
    setSelectedShotId(shotId);
    setPreviewCandidate(null);
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

  const selectedReferenceContext = (selectedShotKey && referenceDrafts[selectedShotKey]) || {
    ...EMPTY_REFERENCE_CONTEXT,
    ready: !selectedShotHasBindings,
  };
  const selectedReferences = selectedReferenceContext.references;
  const selectedReferencesReady = selectedReferenceContext.ready;
  const candidates = selected ? (data?.candidates?.[selected.id] ?? []) : [];
  const trace = selected ? (data?.trace?.[selected.id] ?? []) : [];

  return (
    <div className="qc-scene-workspace" data-testid="scene-workspace">
      <header className="qc-scene-header">
        <div className="qc-scene-context" data-testid="scene-context">
          <span className="director-stage-kicker">场景工作台</span>
          <h1>{data?.scene.location_name ?? "场景"}</h1>
          <span>
            {data?.scene.episode_number}.{data?.scene.scene_number} ·{" "}
            {data?.scene.time_of_day ?? "—"}
          </span>
          {data?.scene.synopsis && <p>{data.scene.synopsis}</p>}
        </div>
        <div className="qc-scene-header-actions">
          <span>{shots.length} 个镜头</span>
          <a
            className="qc-overview-primary"
            href={`/projects/${projectId}/edit`}
            data-testid="scene-edit-entry"
          >
            进入剪辑
          </a>
        </div>
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
        <div className="qc-scene-stage" data-testid="scene-stage">
          <CinematicCanvas
            projectId={projectId}
            shot={selected}
            candidates={candidates}
            selectedCandidate={previewCandidate}
            trace={trace}
          />
          <ShotCandidateTray
            projectId={projectId}
            shot={selected}
            candidates={candidates}
            selectedCandidate={previewCandidate}
            onPreviewCandidate={setPreviewCandidate}
            onConfirmed={async () => {
              setPreviewCandidate(null);
              await workspace.refetch();
            }}
          />
          <ShotStrip
            projectId={projectId}
            shots={shots}
            selectedShotId={selectedShotKey}
            onSelectShot={selectShot}
            traceByShot={(data?.trace ?? {}) as Record<string, unknown[]>}
          />
        </div>
        <DirectorSidebar
          projectId={projectId}
          shot={selected}
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
