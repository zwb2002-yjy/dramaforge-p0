import { apiSend, fetchCsrf } from "../../lib/api";
import type {
  DirectorRecommendation,
  ShotDirectorSuggestion,
} from "./suggestion-types";

const directorPath = (projectId: string, suffix: string) =>
  `/api/v1/projects/${projectId}/director${suffix}`;

/** Request one read-only suggestion for a selected Shot. */
export async function suggestShotDesign(
  projectId: string,
  shotId: string,
  input: {
    scene_id: string;
    shot_id: string;
    expected_shot_version: number;
    user_instruction: string;
  },
): Promise<ShotDirectorSuggestion> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/shots/${encodeURIComponent(shotId)}/suggestion`),
    input,
    csrf,
  );
}

export const requestShotDirectorSuggestion = suggestShotDesign;

/** Request one proactive server-fact recommendation without a user instruction. */
export async function recommendShotDesign(
  projectId: string,
  shotId: string,
  input: {
    scene_id: string;
    shot_id: string;
    expected_shot_version: number;
  },
): Promise<DirectorRecommendation> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    directorPath(projectId, `/shots/${encodeURIComponent(shotId)}/recommendation`),
    input,
    csrf,
  );
}
