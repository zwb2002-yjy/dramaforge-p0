import { expect, test } from "@playwright/test";
import { EDIT_SESSION_ID, installProfessionalMock, PROJECT_ID } from "./professional-mocks";

test("从已确认的未来分集计划进入剪辑，显式导出绑定同一计划", async ({ page }) => {
  const state = await installProfessionalMock(page);
  const base = `/api/v1/projects/${PROJECT_ID}`;
  const master = base + "/director/master-runs";
  const goal = {
    id: "goal",
    goal: "交付灯会两集",
    status: "waiting",
    desired_state: "run",
    current_plan_id: "plan",
    control_epoch: 1,
    available_actions: ["verify"],
    revision: 2,
  };
  const plan = {
    id: "plan",
    decision_status: "accepted",
    revision: 1,
    delivery_check: {
      rule_id: "project_delivery_ready_v1",
      work_type: "serial_comic",
      targets: [],
      planned_episode_count: 2,
      output_slot: {
        flow_key: "episode_delivery",
        step_key: "collect_exports",
        field: "episode_exports",
      },
    },
  };
  await page.route(
    (url) => url.pathname.startsWith(master),
    (route) => {
      const path = new URL(route.request().url()).pathname;
      return route.fulfill({
        json: path.endsWith("/plans")
          ? [plan]
          : path.endsWith("/goal")
            ? goal
            : { items: [goal], next_offset: null },
      });
    },
  );
  const cut = { ...state.editing.session, episode_id: "episode-2", name: "灯会第二集" };
  await page.route(
    (url) => url.pathname === base + "/edit-sessions",
    (route) => route.fulfill({ json: [{ ...cut, clip_count: 1 }] }),
  );
  await page.route(
    (url) => url.pathname === base + "/edit-sessions/" + EDIT_SESSION_ID,
    (route) => route.fulfill({ json: cut }),
  );
  let rendered = 0;
  await page.route(
    (url) => url.pathname === base + "/final-film/render",
    async (route) => {
      expect(route.request().postDataJSON()).toEqual({
        edit_session_id: EDIT_SESSION_ID,
        expected_timeline_version: cut.version,
        name: "V1 Final Film",
        delivery_plan: { master_run_id: "goal", plan_id: "plan", control_epoch: 1 },
      });
      expect(await route.request().headerValue("Idempotency-Key")).toBe(
        "plan-plan-1-" + "a".repeat(64),
      );
      rendered++;
      return route.fulfill({
        status: 202,
        json: { status: "queued", node_run_id: "slot-run", attempt_no: 1 },
      });
    },
  );
  await page.goto(`/projects/${PROJECT_ID}`);
  await page.getByRole("button", { name: "持续目标" }).click();
  await expect(page.getByText(/依次交付第 1 至 2 集/)).toBeVisible();
  await page.getByRole("link", { name: "按此计划导出分集" }).click();
  await page.getByRole("button", { name: /灯会第二集/ }).click();
  await expect(page.getByText(/本次分集导出将绑定已确认的计划/)).toBeVisible();
  expect(rendered).toBe(0);
  await page.getByTestId("export-final-film").click();
  await expect.poll(() => rendered).toBe(1);
});

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
