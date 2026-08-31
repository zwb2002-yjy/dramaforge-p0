import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import {
  AssetReferencePicker,
  type ReferenceResolutionState,
} from "../../components/assets/AssetReferencePicker";
import { CinematicCanvas } from "../shots/CinematicCanvas";
import { ShotDesignPanel } from "../shots/ShotDesignPanel";
import { ShotProductionTrace } from "../shots/ShotProductionTrace";
import { ShotProductionActions } from "../shots/ShotProductionActions";
import { ShotFormalOutputActions } from "../shots/ShotFormalOutputActions";
import { ShotStrip } from "../shots/ShotStrip";
import type { ShotExecutionReference } from "../shots/api";
import { fetchSceneWorkspace, type SceneWorkspaceRead, type ShotLite } from "./api";

type SceneWorkspaceProps = {
  projectId: string;
  sceneId: string;
};

type ShotReferenceContext = {
  shotId: string | null;
  references: ShotExecutionReference[];
  ready: boolean;
};

function sameReferences(left: ShotExecutionReference[], right: ShotExecutionReference[]): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/** Phase 3 scene workspace: shot strip + central canvas + design panel + trace. */
export function SceneWorkspace({ projectId, sceneId }: SceneWorkspaceProps) {
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [referenceContext, setReferenceContext] = useState<ShotReferenceContext>({
    shotId: null,
    references: [],
    ready: false,
  });
  const workspace = useQuery({
    queryKey: ["scene-workspace", projectId, sceneId],
    queryFn: () => fetchSceneWorkspace(projectId, sceneId),
    enabled: Boolean(projectId) && Boolean(sceneId) && projectId !== "demo",
  });
  useEffect(() => {
    setSelectedShotId(null);
    setReferenceContext({ shotId: null, references: [], ready: false });
  }, [projectId, sceneId]);
  const data = workspace.data as SceneWorkspaceRead | undefined;
  const shots = data?.shots ?? [];
  const selected = (shots.find((shot) => shot.id === selectedShotId) ??
    shots[0] ??
    null) as ShotLite | null;
  const selectedShotKey = selected?.id ?? null;

  // The fallback first Shot is still a selected Shot from the user's point of
  // view.  Establish its context as soon as the workspace snapshot arrives,
  // and clear it whenever the selected identity changes.
  useEffect(() => {
    setReferenceContext((current) =>
      current.shotId === selectedShotKey
        ? current
        : { shotId: selectedShotKey, references: [], ready: false },
    );
  }, [selectedShotKey]);

  const selectShot = useCallback((shotId: string) => {
    setSelectedShotId(shotId);
    setReferenceContext({ shotId, references: [], ready: false });
  }, []);

  const updateSelectedReferences = useCallback(
    (references: ShotExecutionReference[]) => {
      if (selectedShotKey === null) return;
      setReferenceContext((current) => {
        if (current.shotId !== selectedShotKey || sameReferences(current.references, references)) {
          return current;
        }
        return {
          shotId: selectedShotKey,
          references: references.map((reference) => ({ ...reference })),
          ready: current.ready,
        };
      });
    },
    [selectedShotKey],
  );
  const updateReferenceResolutionState = useCallback(
    (state: ReferenceResolutionState) => {
      if (selectedShotKey === null) return;
      setReferenceContext((current) => {
        if (current.shotId !== null && current.shotId !== selectedShotKey) return current;
        if (current.shotId === selectedShotKey && current.ready === (state === "ready")) {
          return current;
        }
        return {
          ...current,
          shotId: selectedShotKey,
          ready: state === "ready",
        };
      });
    },
    [selectedShotKey],
  );
  const selectedReferences =
    referenceContext.shotId === selectedShotKey ? referenceContext.references : [];
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

      <div className="qc-scene-layout">
        <ShotStrip shots={shots} selectedShotId={selectedShotKey} onSelectShot={selectShot} />
        <CinematicCanvas projectId={projectId} shot={selected} />
        <aside className="qc-scene-side">
          {selected && (
            <ShotDesignPanel
              projectId={projectId}
              shot={selected}
              onSaved={() => void workspace.refetch()}
            />
          )}
          {selected && (
            <ShotFormalOutputActions
              key={`formal:${selected.id}`}
              projectId={projectId}
              shot={selected}
              candidates={data?.candidates?.[selected.id] ?? []}
              onConfirmed={async () => {
                await workspace.refetch();
              }}
            />
          )}
          {selected && (
            <ShotProductionActions
              key={`production:${selected.id}`}
              projectId={projectId}
              shot={selected}
              references={selectedReferences}
              referencesReady={referenceContext.ready}
              onExecuted={async () => {
                await workspace.refetch();
              }}
            />
          )}
          {selected && (
            <AssetReferencePicker
              key={`references:${selected.id}`}
              projectId={projectId}
              shotId={selected.id}
              onReferencesChange={updateSelectedReferences}
              onResolutionStateChange={updateReferenceResolutionState}
            />
          )}
        </aside>
      </div>

      <ShotProductionTrace shotId={selected?.id ?? ""} trace={trace} />
    </div>
  );
}
