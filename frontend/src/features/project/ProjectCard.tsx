import { ArrowRight, Clapperboard } from "lucide-react";
import { Button, Card } from "../../components/ui";
import type { ProjectRead } from "./api";
import { ProjectActions } from "./ProjectActions";
import { projectCopy as copy } from "./projectCopy";
import { WORK_TYPE_LABELS } from "./projectIntent";

/** One explicit open target per project; the independent menu keeps delete gated. */
export function ProjectCard({
  project,
  onOpen,
}: {
  project: ProjectRead;
  onOpen: (id: string) => void;
}) {
  const format =
    project.aspect_ratio === "16:9"
      ? copy.landscape
      : project.aspect_ratio === "9:16"
        ? copy.portrait
        : project.aspect_ratio === "1:1"
          ? copy.square
          : copy.otherFormat;
  return (
    <Card className="df-project-card" role="article" aria-label={project.name}>
      <div className="df-project-card-row">
        <span className="df-project-cover" aria-hidden="true">
          <Clapperboard size={24} />
        </span>
        <div className="df-project-card-body">
          <h2 title={project.name}>{project.name}</h2>
          {project.creative_goal && <p className="df-project-goal">{project.creative_goal}</p>}
          <span className="df-project-card-meta">
            {project.work_type ? WORK_TYPE_LABELS[project.work_type] : "作品类型待确认"} · {format}{" "}
            · {project.aspect_ratio}
          </span>
        </div>
        <div className="df-project-card-actions">
          <Button
            tone="ghost"
            className="df-project-open"
            onClick={() => onOpen(project.id)}
            aria-label={copy.enterProject(project.name)}
          >
            <span>{copy.enter}</span>
            <ArrowRight size={18} aria-hidden="true" />
          </Button>
        </div>
        <ProjectActions project={project} />
      </div>
    </Card>
  );
}
