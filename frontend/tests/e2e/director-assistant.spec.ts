import { expect, test } from "@playwright/test";
import { exerciseContextualDirector, installContextualDirectorMock } from "./contextual-director";
import { PROJECT_ID, installProfessionalMock } from "./professional-mocks";

test("director assistant keeps proposal, explicit save and persisted design in the scene workspace", async ({
  page,
}) => {
  const state = await installProfessionalMock(page);
  const suggestion = await installContextualDirectorMock(page, state);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await expect(page.getByTestId("production-monitor")).toBeVisible();
  await expect(page.getByRole("heading", { name: "场景与镜头" })).toHaveCount(0);
  await exerciseContextualDirector(page, state, suggestion);
  // The single design save is authoritative; no parallel canvas/board revision is created.
  expect(state.revisions).toHaveLength(0);
  expect(state.proposals).toHaveLength(0);
  expect(state.directorState).toEqual(suggestion.suggested_director_state);
});
