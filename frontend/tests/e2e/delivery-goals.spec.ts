import { expect, test } from "@playwright/test";
import { installProfessionalMock, PROJECT_ID } from "./professional-mocks";

test("持续目标在用户确认后核验并保留缺集原因", async ({ page }) => {
  await installProfessionalMock(page);
  const prefix = `/api/v1/projects/${PROJECT_ID}/director`;
  let created = false,
    confirmed = false,
    verified = false;
  const targets = [1, 2].map((n) => ({ episode_id: `e${n}`, episode_number: n }));
  await page.route(
    (url) => url.pathname.startsWith(prefix + "/master-runs"),
    (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/verify")) {
        expect(confirmed).toBe(true);
        expect(route.request().postDataJSON()).toEqual({ expected_revision: 2 });
        verified = true;
        return route.fulfill({ json: { status: "waiting", result_revision: 3 } });
      }
      if (path.endsWith("/plans"))
        return route.fulfill({
          json: [
            {
              id: "p",
              revision: 1,
              proposal_id: "proposal",
              decision_ref: "item",
              decision_status: confirmed ? "accepted" : "pending",
              delivery_check: {
                rule_id: "project_delivery_ready_v1",
                work_type: "serial_comic",
                targets,
              },
            },
          ],
        });
      const goal = {
        id: "run",
        goal: "核对灯会两集交付",
        status: confirmed ? "waiting" : "planning",
        revision: verified ? 3 : confirmed ? 2 : 1,
        available_actions: confirmed ? ["verify"] : [],
        last_verification: verified
          ? {
              satisfied: false,
              checks: [
                {
                  rule_id: "project_delivery_ready_v1",
                  satisfied: false,
                  evidence_refs: [
                    { episode_number: 2, blockers: ["DELIVERY_CURRENT_EXPORT_MISSING"] },
                  ],
                },
              ],
            }
          : null,
      };
      return route.fulfill({ json: { items: created ? [goal] : [], next_offset: null } });
    },
  );
  await page.route(
    (url) => url.pathname === prefix + "/proposals/proposal/apply",
    (route) => {
      expect(route.request().postDataJSON()).toEqual({
        decisions: [{ item_id: "item", decision: "accepted" }],
      });
      confirmed = true;
      return route.fulfill({ json: { accepted: ["item"], rejected: [], failed: [] } });
    },
  );
  await page.route(
    (url) => url.pathname.startsWith(prefix + "/threads"),
    (route) => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      if (path.endsWith("/messages") && req.method() === "POST") {
        expect(req.postDataJSON().intent).toBe("create_goal");
        created = true;
        return route.fulfill({
          status: 202,
          json: { thread_id: "thread", turn_id: "turn", status: "queued" },
        });
      }
      if (path.endsWith("/requests"))
        return route.fulfill({ json: { turn: { status: "completed" } } });
      return route.fulfill({
        json: { id: "thread", scope_type: "project", scope_entity_id: PROJECT_ID, messages: [] },
      });
    },
  );
  await page.goto(`/projects/${PROJECT_ID}`);
  const panel = page.getByRole("complementary", { name: "项目导演对话" });
  await panel.getByRole("button", { name: "持续目标" }).click();
  await expect(panel.getByText("暂无持续目标")).toBeVisible();
  await panel.getByRole("checkbox", { name: "将本条消息建立为持续目标" }).check();
  await panel.getByRole("textbox", { name: "给导演的想法" }).fill("核对灯会两集交付");
  await panel.getByRole("button", { name: "发送给导演" }).click();
  await expect(panel.getByText(/计划 v1.*第 1 集、第 2 集/)).toBeVisible();
  expect(confirmed || verified).toBe(false);
  await panel.getByRole("button", { name: "确认核验计划" }).click();
  await panel.getByRole("button", { name: "核验已确认计划" }).click();
  await expect(panel.getByText("第 2 集 · 当前剪辑尚无对应成片")).toBeVisible();
  await page.reload();
  await panel.getByRole("button", { name: "持续目标" }).click();
  await expect(panel.getByText("第 2 集 · 当前剪辑尚无对应成片")).toBeVisible();
});
