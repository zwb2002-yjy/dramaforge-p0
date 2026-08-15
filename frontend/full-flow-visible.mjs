import { createInterface } from "node:readline";
import { chromium } from "playwright";

const ownerEmail = process.env.DRAMAFORGE_OWNER_EMAIL;
const ownerPassword = process.env.DRAMAFORGE_OWNER_PASSWORD;
if (!ownerEmail || !ownerPassword) throw new Error("Missing Owner credentials.");

const baseUrl = "http://127.0.0.1:8080";
const projectId = "07a7ff32-ee11-465c-98a2-ad1ced13b2d2";
const projectName = "最后一班电梯 · 完整流程 191430";
const oneSentenceIdea = "停电后的最后一班电梯里，准备辞职的女程序员遇见了十年后的自己；未来的她只有二十秒，必须说服现在的自己不要按下顶楼。";
const reviewNote = "人工验收：已在前端查看真实试拍证据，接受当前人物、声线、嘴巴开合、表演和风格的已知局限，继续完成本次全流程验证。";

const browser = await chromium.launch({ channel: "msedge", headless: false, slowMo: 80 });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(30_000);
const errors = [];
page.on("pageerror", (error) => errors.push(`pageerror: ${error}`));
page.on("console", (message) => {
  if (message.type() === "error" && !message.text().includes("401 (Unauthorized)")) {
    errors.push(`console: ${message.text()}`);
  }
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForEnabled(locator, label, timeoutMs = 2_400_000) {
  const startedAt = Date.now();
  let previous = "";
  while (Date.now() - startedAt < timeoutMs) {
    const visible = await locator.isVisible().catch(() => false);
    const enabled = visible && await locator.isEnabled().catch(() => false);
    if (enabled) {
      console.log(`[ready] ${label}`);
      return;
    }
    const progress = await page.locator(".director-trial-run-list").last().innerText().catch(() => "等待页面状态");
    if (progress !== previous) {
      console.log(`[progress] ${label}\n${progress.slice(0, 2000)}`);
      previous = progress;
    }
    await sleep(5_000);
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function waitForUserDecision(label) {
  console.log(`\n[PAUSE:${label}] 输入 continue 后继续。`);
  const reader = createInterface({ input: process.stdin, output: process.stdout });
  return await new Promise((resolve) => {
    reader.once("line", (line) => {
      reader.close();
      resolve(line.trim().toLowerCase());
    });
  });
}

async function login() {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  if (await page.getByRole("heading", { name: "Owner 登录" }).isVisible().catch(() => false)) {
    await page.getByLabel("邮箱").fill(ownerEmail);
    await page.getByLabel("密码").fill(ownerPassword);
    await page.getByRole("button", { name: "登录" }).click();
  }
  await page.getByText("DramaForge Owner", { exact: true }).waitFor({ state: "visible" });
  console.log("[done] 已从前端登录 Owner");
}

async function configureExistingProject() {
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByLabel("项目 Provider 绑定").selectOption(projectId);
  const videoAccountState = page.getByTestId("binding-video-account_verified");
  if ((await videoAccountState.innerText()).includes("待定")) {
    await page.getByLabel("能力").selectOption("video_i2v");
    await page.getByLabel("预算授权金额").fill("10");
    await page.getByLabel("参考产物 ID").fill("8531a6ae-81d7-4a8e-a954-bd485e401b33");
    await page.getByRole("button", { name: "授权并运行付费探测" }).click();
    await page.getByTestId("provider-config-message").waitFor({ state: "visible" });
    const probeMessage = await page.getByTestId("provider-config-message").innerText();
    if (!probeMessage.includes("passed")) {
      throw new Error(`Video capability probe did not pass: ${probeMessage}`);
    }
    await page.getByTestId("binding-video-account_verified").getByText("通过").waitFor({ state: "visible" });
    console.log("[done] 已从前端运行 Agnes video_i2v 账号能力探测");
  }
  const bindings = page.locator(".provider-binding");
  const count = await bindings.count();
  if (count < 2) throw new Error(`Expected two provider bindings, found ${count}.`);
  for (let index = 0; index < count; index += 1) {
    const binding = bindings.nth(index);
    const purpose = (await binding.locator(".muted").first().innerText()).trim();
    const price = purpose === "video" ? "10" : "1";
    await binding.getByLabel(`${purpose} 单次价格`).fill(price);
    await binding.locator('input[type="checkbox"]').last().check();
    await binding.getByRole("button", { name: "保存价格快照" }).click();
    await page.getByTestId("provider-config-message").waitFor({ state: "visible" });
    const button = binding.getByRole("button", { name: "绑定所选项目" });
    if (!await button.isEnabled()) {
      throw new Error(`Provider binding is not ready: ${await binding.innerText()}`);
    }
    await button.click();
    await page.getByTestId("provider-config-message").waitFor({ state: "visible" });
  }
  console.log("[done] 已在前端保存保守成本并绑定关键帧与视频模型");
  await page.goto(`${baseUrl}/projects/${projectId}/quick`, { waitUntil: "networkidle" });
}

async function completeCreativeStage() {
  await page.getByRole("radio", { name: /我有一句话创意/ }).click();
  await page.getByLabel("用一句话说出你最想看到的故事").fill(oneSentenceIdea);
  await page.getByTestId("generate-concepts").click();
  await page.getByTestId("concept-set").waitFor({ state: "visible", timeout: 600_000 });
  const cards = page.locator(".director-concept-card");
  console.log(`[done] DeepSeek 返回 ${await cards.count()} 个概念`);
  for (let index = 0; index < await cards.count(); index += 1) {
    console.log(`[concept ${index + 1}] ${(await cards.nth(index).innerText()).slice(0, 800)}`);
  }
  await cards.first().click();
  await page.getByLabel("情绪走向").first().fill("戒备与否认 → 恐惧 → 理解自己 → 主动选择");
  await page.getByTestId("generate-creative-package").click();
  await page.getByTestId("creative-package-review").waitFor({ state: "visible", timeout: 600_000 });

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const passed = await page.getByText("剧本预审通过", { exact: true }).isVisible().catch(() => false);
    if (passed) break;
    if (attempt === 1) throw new Error(`Creative review did not pass: ${await page.getByTestId("creative-package-review").innerText()}`);
    await page.getByRole("button", { name: "按这些修改生成新版本" }).click();
    await page.getByText("正在生成并重新预审…", { exact: true }).waitFor({ state: "hidden", timeout: 600_000 });
  }
  console.log(`[done] 创作方案预审通过\n${(await page.getByTestId("creative-package-review").innerText()).slice(0, 3000)}`);
  await page.getByRole("button", { name: "确认创作方案，进入拍摄方案" }).click();
  await page.getByTestId("shooting-stage").waitFor({ state: "visible" });
  console.log("[done] 硬确认 1/4 已从前端完成");
}

async function completeShootingStage() {
  await page.getByRole("button", { name: "授权本次文字生成并准备拍摄方案" }).click();
  await page.getByTestId("shooting-costs").waitFor({ state: "visible", timeout: 600_000 });
  const shootingText = await page.getByTestId("shooting-stage").innerText();
  console.log(`[done] 拍摄方案已生成\n${shootingText.slice(0, 5000)}`);
  const confirm = page.getByRole("button", { name: "确认拍摄方案" });
  if (!await confirm.isEnabled()) {
    throw new Error(`Shooting plan is blocked: ${await page.getByTestId("shooting-not-ready").innerText().catch(() => shootingText)}`);
  }
  await confirm.click();
  await page.getByTestId("trial-budget-panel").waitFor({ state: "visible" });
  console.log("[done] 硬确认 2/4 已从前端完成");
}

async function runTrial() {
  const panel = page.getByTestId("trial-budget-panel");
  console.log(`[trial budget]\n${await panel.innerText()}`);
  await panel.locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "确认并授权试拍预算" }).click();
  await page.getByRole("button", { name: "开始代表镜头试拍" }).waitFor({ state: "visible" });
  console.log("[done] 硬确认 3/4 已从前端完成");
  await page.getByRole("button", { name: "开始代表镜头试拍" }).click();
  const inspect = page.getByRole("button", { name: /运行已结束，生成质量报告/ });
  await waitForEnabled(inspect, "代表镜头所有节点结束");
  await inspect.click();
  await page.getByTestId("trial-decision").waitFor({ state: "visible", timeout: 120_000 });
  const reportText = await page.getByTestId("trial-quality-report").innerText();
  const trialImage = page.getByTestId("trial-artifact-phone");
  if (await trialImage.isVisible().catch(() => false)) {
    await trialImage.screenshot({ path: "D:/dramaforge/tmp/full-flow-trial.png" });
  }
  console.log(`[trial report]\n${reportText}`);
  console.log(`[trial decision]\n${await page.getByTestId("trial-decision").innerText()}`);
  const decision = await waitForUserDecision("TRIAL_REVIEW");
  if (decision !== "continue") throw new Error(`Trial was not accepted; command=${decision}`);
  const decisionPanel = page.getByTestId("trial-decision");
  await decisionPanel.getByLabel("给 AI 导演的验收说明").fill(reviewNote);
  const accept = decisionPanel.getByRole("button", { name: "接受试拍质量" });
  if (!await accept.isEnabled()) throw new Error(`Trial has a hard blocker: ${await decisionPanel.innerText()}`);
  await accept.click();
  await page.getByTestId("production-budget-panel").waitFor({ state: "visible" });
  console.log("[done] 试拍已从前端人工验收");
}

async function runProduction() {
  const panel = page.getByTestId("production-budget-panel");
  console.log(`[production budget]\n${await panel.innerText()}`);
  await panel.locator('input[type="checkbox"]').check();
  await page.getByRole("button", { name: "确认并授权正式生产预算" }).click();
  await page.getByRole("button", { name: "开始正式生产" }).waitFor({ state: "visible" });
  console.log("[done] 硬确认 4/4 已从前端完成");
  await page.getByRole("button", { name: "开始正式生产" }).click();
  const inspect = page.getByRole("button", { name: /运行已结束，生成逐镜质量报告/ });
  await waitForEnabled(inspect, "正式生产所有节点结束");
  await inspect.click();
  await page.getByTestId("production-review").waitFor({ state: "visible", timeout: 120_000 });
  const review = page.getByTestId("production-review");
  console.log(`[production review]\n${await review.innerText()}`);
  await review.screenshot({ path: "D:/dramaforge/tmp/full-flow-production-review.png" });
  const decision = await waitForUserDecision("PRODUCTION_REVIEW");
  if (decision !== "continue") throw new Error(`Production was not accepted; command=${decision}`);
  const shots = review.locator(".director-shot-review-list article");
  for (let index = 0; index < await shots.count(); index += 1) {
    const accept = shots.nth(index).getByRole("button", { name: "接受" });
    if (!await accept.isEnabled()) throw new Error(`Shot ${index + 1} has a hard blocker: ${await shots.nth(index).innerText()}`);
    await accept.click();
  }
  await review.getByLabel("给 AI 导演的验收说明").fill("人工逐镜验收：接受当前自动证据中已披露的主观质量局限，确认本次全流程样片可导出。 ");
  await review.getByRole("button", { name: "全部接受并精确导出" }).click();
  await page.getByTestId("director-delivery").waitFor({ state: "visible", timeout: 300_000 });
  await page.getByRole("button", { name: "准备四项下载" }).click();
  await page.getByRole("link", { name: "下载成片 MP4" }).waitFor({ state: "visible" });
  const links = await page.getByTestId("director-delivery").locator("a").evaluateAll((anchors) =>
    anchors.map((anchor) => ({ text: anchor.textContent, href: anchor.href })),
  );
  console.log(`[delivery]\n${JSON.stringify(links, null, 2)}`);
  const mp4 = page.getByRole("link", { name: "下载成片 MP4" });
  const [videoPage] = await Promise.all([context.waitForEvent("page"), mp4.click()]);
  await videoPage.waitForLoadState("domcontentloaded").catch(() => undefined);
  await videoPage.bringToFront();
  console.log(`[COMPLETE] project=${projectName} url=${page.url()} video=${videoPage.url()}`);
  if (errors.length) console.log(`[browser warnings]\n${errors.join("\n")}`);
  await waitForUserDecision("COMPLETE");
}

try {
  await login();
  await configureExistingProject();
  await completeCreativeStage();
  await completeShootingStage();
  await runTrial();
  await runProduction();
  console.log(`[result] ${projectId}`);
} catch (error) {
  console.error(`[FAILED] ${error?.stack ?? error}`);
  await page.screenshot({ path: "D:/dramaforge/tmp/full-flow-failure.png", fullPage: false }).catch(() => undefined);
  process.exitCode = 1;
} finally {
  await browser.close();
}
