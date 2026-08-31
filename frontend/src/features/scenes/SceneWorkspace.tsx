import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { AssetReferencePicker } from "../../components/assets/AssetReferencePicker";
import { CinematicCanvas } from "../shots/CinematicCanvas";
import { ShotDesignPanel } from "../shots/ShotDesignPanel";
import { ShotProductionTrace } from "../shots/ShotProductionTrace";
import { ShotProductionActions } from "../shots/ShotProductionActions";
import { ShotStrip } from "../shots/ShotStrip";
import { fetchSceneWorkspace, type SceneWorkspaceRead, type ShotLite } from "./api";

type SceneWorkspaceProps = {
  projectId: string;
  sceneId: string;
};

/** Phase 3 scene workspace: shot strip + central canvas + design panel + trace. */
export function SceneWorkspace({ projectId, sceneId }: SceneWorkspaceProps) {
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const workspace = useQuery({
    queryKey: ["scene-workspace", projectId, sceneId],
    queryFn: () => fetchSceneWorkspace(projectId, sceneId),
    enabled: Boolean(projectId) && Boolean(sceneId) && projectId !== "demo",
  });
  useEffect(() => {
    setSelectedShotId(null);
  }, [projectId, sceneId]);
  const data = workspace.data as SceneWorkspaceRead | undefined;
  const shots = data?.shots ?? [];
  const selected = (shots.find((shot) => shot.id === selectedShotId) ??
    shots[0] ??
    null) as ShotLite | null;
  const trace = selected ? (data?.trace?.[selected.id] ?? []) : [];

  return (
    <div className="qc-scene-workspace" data-testid="scene-workspace">
      <header className="qc-page-heading">
        <p>场景工作区</p>
        <h1>{data?.scene.location_name ?? "场景"}</h1>
        <span>
          {data?.scene.episode_number}.{data?.scene.scene_number} · {data?.scene.time_of_day}
        </span>
      </header>

      {workspace.isError && (
        <div className="flash err">无法读取场景工作区：{String(workspace.error)}</div>
      )}

      <div className="qc-scene-layout">
        <ShotStrip
          shots={shots}
          selectedShotId={selected?.id ?? null}
          onSelectShot={setSelectedShotId}
        />
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
            <ShotProductionActions
              projectId={projectId}
              shot={selected}
              onExecuted={async () => {
                await workspace.refetch();
              }}
            />
          )}
          {selected && <AssetReferencePicker projectId={projectId} shotId={selected.id} />}
        </aside>
      </div>

      <ShotProductionTrace shotId={selected?.id ?? ""} trace={trace} />
    </div>
  );
}
