import { useMutation, useQuery } from "@tanstack/react-query";
import { createRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import {
  createOrganization,
  fetchHealth,
  loginUser,
  registerUser,
  startProject,
} from "../lib/api";
import { rootRoute } from "./__root";

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});

function HomePage() {
  const navigate = useNavigate();
  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: 8_000,
    retry: 1,
  });
  const [email, setEmail] = useState(`creator-${Date.now()}@example.com`);
  const [password, setPassword] = useState("password123");
  const [name, setName] = useState("霓虹雨夜 · 试产项目");
  const [error, setError] = useState<string | null>(null);

  const bootstrap = useMutation({
    mutationFn: async () => {
      setError(null);
      try {
        await registerUser(email, password, "Creator");
      } catch {
        await loginUser(email, password);
      }
      const org = await createOrganization(`Org-${Date.now()}`);
      const project = await startProject({
        organization_id: org.id,
        name,
        aspect_ratio: "9:16",
        idea: "neon rain short drama",
      });
      return project;
    },
    onSuccess: (project) => {
      void navigate({
        to: "/projects/$projectId/quick",
        params: { projectId: project.project_id },
      });
    },
    onError: (e: Error) => setError(e.message),
  });

  const dbUp = health.data?.db === "up" || (health.data?.status === "ok" && !health.data?.db);
  const apiLive = !!health.data && !health.isError && health.data.status === "ok" && dbUp !== false;

  return (
    <div className="hero-home" data-testid="home-panel">
      <section className="panel">
        <div className="page-title-row">
          <div>
            <h2>短剧生产工作台</h2>
            <p className="muted" style={{ margin: "0.35rem 0 0" }}>
              创意 → Brief/Plan → 角色一致性 → 分镜流水线 → 审核交付。
              信息密度对标行业生产台，产品合同以 DramaForge 冻结包为准。
            </p>
          </div>
        </div>

        <div className="callout">
          <strong>标准 P0 路径</strong>
          <br />
          ① 创建正式项目 → ② 快速创作竖切首帧（Agent 或手工）→ ③ 专业板 10 Shot → ④ 可追溯导出
        </div>

        <div className="status-grid" data-testid="api-status">
          <div className="status-card">
            <span className="status-label">API /health</span>
            {health.isLoading && <strong className="status-pending">连接中…</strong>}
            {health.isError && (
              <strong className="status-bad">离线 — 启动 Postgres + API</strong>
            )}
            {health.data && health.data.status === "ok" && (health.data.db === "up" || !health.data.db) && (
              <strong className="status-ok">
                在线 · db {health.data.db ?? "ok"} · {health.data.env}
              </strong>
            )}
            {health.data && (health.data.status !== "ok" || health.data.db === "down") && (
              <strong className="status-bad">
                {health.data.status} · db {health.data.db ?? "?"}
              </strong>
            )}
          </div>
          <div className="status-card">
            <span className="status-label">画幅</span>
            <strong>9:16 竖屏</strong>
          </div>
          <div className="status-card">
            <span className="status-label">双模式</span>
            <strong>同 Project</strong>
          </div>
          <div className="status-card">
            <span className="status-label">P0 验收</span>
            <strong className="status-pending">§3.1 未盖章</strong>
          </div>
        </div>

        <form
          className="auth-form"
          onSubmit={(e) => {
            e.preventDefault();
            bootstrap.mutate();
          }}
        >
          <label>
            工作账号 Email
            <input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
          </label>
          <label>
            密码
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          <label>
            项目名称
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <div className="toolbar">
            <button className="primary" type="submit" disabled={bootstrap.isPending || !apiLive}>
              {bootstrap.isPending ? "创建中…" : "进入工作台 · 注册/登录并创建项目"}
            </button>
          </div>
          {!apiLive && (
            <p className="status-bad">
              后端未就绪时无法创建项目。请运行{" "}
              <code>scripts/start_p0_stack.ps1</code> 保证 PostgreSQL + API(:8010)。
            </p>
          )}
          {error && <p className="flash err">{error}</p>}
        </form>
      </section>

      <section className="panel">
        <h3>工作台地图</h3>
        <ul className="clean">
          <li>
            <strong>快速创作</strong>：创意 → Agent/手工 Brief·Plan → 主角 canonical → 竖屏首帧预览
          </li>
          <li>
            <strong>专业生产板</strong>：10 Shot 分镜板、节点轨、导出回链（非假黄金冒充验收）
          </li>
          <li>
            <strong>检查器</strong>：Run 统计、失败、产物哈希（右侧栏实时）
          </li>
        </ul>
        <div className="pipeline-rail" aria-hidden>
          {["prompt", "keyframe", "face", "video", "voice", "subtitle", "composite", "continuity"].map(
            (n) => (
              <span key={n} className="pipeline-node">
                {n}
              </span>
            ),
          )}
        </div>
        <div className="callout warn" style={{ marginTop: "0.75rem" }}>
          对照行业台看信息密度与流水线感；DramaForge 不复刻 LibTV / Jellyfish / Toonflow / ArcReel
          的产品面，核心是私有化 Graph、一致性与审计。
        </div>
      </section>
    </div>
  );
}
