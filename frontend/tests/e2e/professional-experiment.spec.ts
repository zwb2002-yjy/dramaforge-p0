import { expect, test } from "@playwright/test";

import { PROJECT_ID, installProfessionalMock } from "./professional-mocks";

test("experiment branch lifecycle: create, run, adopt candidate", async ({ page }) => {
  const state = await installProfessionalMock(page);
  await page.goto(`/projects/${PROJECT_ID}/production`);
  await page.getByRole("tab", { name: "版本尝试", exact: true }).click();
  await expect(page.getByTestId("professional-workbench")).toBeVisible();

  await page.getByLabel("实验名称").fill("Model B 转头验证");
  await page.getByLabel("实验模型").selectOption("provider/model-b");
  await expect(page.getByText(/动态能力/)).toContainText("video.image_to_video");
  await page.getByRole("button", { name: "创建实验分支" }).click();
  await expect(page.getByText("Model B 转头验证")).toBeVisible();

  await page.getByRole("button", { name: "运行实验" }).click();
  await expect(page.getByText(/执行证据：1 次运行/)).toBeVisible();

  await page.getByRole("button", { name: "采纳候选" }).click();
  await expect(page.getByText(/Model B 转头验证/)).toBeVisible();
  await expect(page.getByTestId("experiment-message")).toContainText("已采用该候选");
  await expect(page.getByTestId(`experiment-stage-${state.experiments[0].id}`)).toContainText(
    "已采用",
  );
  expect(state.experiments[0].status).toBe("accepted");
});

for (const failedRead of [false, true]) {
  test(`experiment start fails closed for ${failedRead ? "failed read" : "unknown submission"}`, async ({
    page,
  }) => {
    const state = await installProfessionalMock(page);
    let workbenchReads = 0;
    await page.route("**/shots/*/workbench", async (route) => {
      workbenchReads++;
      await route.fulfill({
        status: failedRead ? 503 : 200,
        contentType: "application/json",
        body: JSON.stringify(
          failedRead
            ? { detail: "workbench unavailable" }
            : {
                trace: [{ node_key: "video", status: "failed", operation_outcome_unknown: true }],
              },
        ),
      });
    });
    await page.goto(`/projects/${PROJECT_ID}/production`);
    await page.getByRole("tab", { name: "版本尝试", exact: true }).click();
    await page.getByLabel("实验阶段").selectOption("video");
    await page.getByLabel("实验名称").fill("Do not bypass reconciliation");
    await page.getByLabel("实验模型").selectOption("provider/model-b");
    await page.getByRole("button", { name: "创建实验分支" }).click();
    await page.getByRole("button", { name: "运行实验" }).click();
    await expect(page.getByTestId("experiment-message")).toContainText(
      failedRead ? "实验请求未被接受" : "不能通过新候选任务绕过",
    );
    expect(workbenchReads).toBe(1);
    expect(state.experiments[0].status).toBe("draft");
    expect(
      state.editing.requests.filter(
        (request) => request.method === "POST" && request.path.endsWith("/start"),
      ),
    ).toEqual([]);
  });
}
