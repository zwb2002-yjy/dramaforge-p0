import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID, SHOT_ID } from "./professional-mocks";

test("project chat keeps the selected candidate across a reload and opens its original view", async ({
  page,
}) => {
  await installProfessionalMock(page);
  const first = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
    second = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2";
  const thread = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    turn = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
  const context = {
    selected_refs: [
      { kind: "shot", id: SHOT_ID },
      { kind: "artifact", id: second },
    ],
  };
  let requestKey = "",
    submissions = 0,
    complete = false;
  await page.route(`**/shots/${SHOT_ID}/workbench`, (route) =>
    route.fulfill({
      json: {
        shot: { id: SHOT_ID },
        candidates: [first, second].map((id) => ({
          stage: "image_keyframe",
          artifact_id: id,
          artifact_type: "image",
          status: "completed",
          storage_state: "available",
        })),
      },
    }),
  );
  await page.route("**/director/threads**", async (route) => {
    const r = route.request(),
      path = new URL(r.url()).pathname;
    if (path.endsWith("/messages") && r.method() === "POST") {
      const input = r.postDataJSON();
      expect(input.ui_context).toEqual(context);
      expect(input.content).toBe("让第二个画面更明亮");
      requestKey = input.request_key;
      submissions++;
      return route.fulfill({
        status: 202,
        json: { thread_id: thread, turn_id: turn, request_key: requestKey, status: "queued" },
      });
    }
    if (path.endsWith("/threads"))
      return route.fulfill({
        json: { id: thread, scope_type: "project", scope_entity_id: PROJECT_ID },
      });
    if (path.endsWith("/requests"))
      return route.fulfill({
        json: {
          acceptance: { thread_id: thread, turn_id: turn },
          turn: { thread_id: thread, turn_id: turn, status: complete ? "completed" : "thinking" },
        },
      });
    return route.fulfill({
      json: {
        id: thread,
        scope_type: "project",
        scope_entity_id: PROJECT_ID,
        messages: submissions
          ? [
              {
                id: "user-message",
                role: "user",
                content: "让第二个画面更明亮",
                turn_id: turn,
                context,
              },
            ]
          : [],
      },
    });
  });
  await page.goto(`/projects/${PROJECT_ID}`);
  await page.getByRole("button", { name: "预览第 2 个关键帧" }).click();
  expect(submissions).toBe(0);
  await page.getByRole("textbox", { name: "给导演的想法" }).fill("让第二个画面更明亮");
  await page.getByRole("button", { name: "发送给导演" }).click();
  await expect.poll(() => submissions).toBe(1);
  await page.reload();
  await expect(page.getByRole("link", { name: "查看本条讨论的画面" })).toBeVisible();
  expect(submissions).toBe(1);
  complete = true;
  await page.getByRole("link", { name: "查看本条讨论的画面" }).click();
  await expect(page.getByRole("button", { name: "预览第 2 个关键帧" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(page.getByRole("textbox", { name: "给导演的想法" })).toBeVisible();
  expect(submissions).toBe(1);
});
