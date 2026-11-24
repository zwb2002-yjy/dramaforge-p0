import { apiGet, apiSend, fetchCsrf } from "../../lib/api";
import type { components } from "../../shared/api/generated";

export type ReviewAnnotationRead = components["schemas"]["AnnotationRead"];

export function fetchReviewAnnotations(
  projectId: string,
  shotId: string,
): Promise<ReviewAnnotationRead[]> {
  return apiGet(`/api/v1/projects/${projectId}/shots/${shotId}/annotations`);
}

export async function createReviewAnnotation(
  projectId: string,
  shotId: string,
  input: Omit<components["schemas"]["AnnotationCreateBody"], "severity"> &
    Partial<Pick<components["schemas"]["AnnotationCreateBody"], "severity">>,
): Promise<ReviewAnnotationRead> {
  const csrf = await fetchCsrf();
  return apiSend("POST", `/api/v1/projects/${projectId}/shots/${shotId}/annotations`, input, csrf);
}

export async function decideReviewAnnotation(
  projectId: string,
  shotId: string,
  annotationId: string,
  status: "open" | "resolved",
): Promise<ReviewAnnotationRead> {
  const csrf = await fetchCsrf();
  return apiSend(
    "POST",
    `/api/v1/projects/${projectId}/shots/${shotId}/annotations/${annotationId}/decision`,
    { status },
    csrf,
  );
}
