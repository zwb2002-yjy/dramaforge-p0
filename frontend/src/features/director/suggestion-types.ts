import type { components } from "../../shared/api/generated";

export type DirectorTurnRead = components["schemas"]["DirectorTurnRead"];
export type ModelSlot = components["schemas"]["ModelSlot"];
export type DirectorNextActionRead = components["schemas"]["DirectorNextActionRead"];

export type DirectorInvocationEvidence =
  components["schemas"]["DirectorInvocationEvidence"]; /** Canonical one-shot Director suggestion preview. */
export type ShotDirectorSuggestion = components["schemas"]["ShotDirectorSuggestion"];
export type DirectorRecommendationOperation =
  components["schemas"]["DirectorRecommendationOperation"];
export type DirectorRecommendation = components["schemas"]["DirectorRecommendation"];
