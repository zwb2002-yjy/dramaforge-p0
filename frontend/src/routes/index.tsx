import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, createRoute, useNavigate } from "@tanstack/react-router";
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
    refetchInterval: 15_000,
  });
  const [email, setEmail] = useState(`user-${Date.now()}@example.com`);
  const [password, setPassword] = useState("password123");
  const [name, setName] = useState("Demo Project");
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

  return (
    <section className="panel" data-testid="home-panel">
      <h1>DramaForge 工作台</h1>
      <p>登录后创建正式 Project，进入快速模式完成 Brief → Plan → 首帧生产。</p>

      <div className="status-grid" data-testid="api-status">
        <div className="status-card">
          <span className="status-label">API /health</span>
          {health.isLoading && <strong className="status-pending">连接中…</strong>}
          {health.isError && (
            <strong className="status-bad">
              离线（API/数据库未就绪，请启动 Postgres 与后端）
            </strong>
          )}
          {health.data && health.data.status === "ok" && (
            <strong className="status-ok">
              {health.data.status}
              {health.data.db ? ` · db ${health.data.db}` : ""} · v{health.data.version}
            </strong>
          )}
          {health.data && health.data.status !== "ok" && (
            <strong className="status-bad">
              {health.data.status}
              {health.data.db ? ` · db ${health.data.db}` : ""} · v{health.data.version}
            </strong>
          )}
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
          Email
          <input value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <label>
          Project name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button type="submit" disabled={bootstrap.isPending}>
          {bootstrap.isPending ? "创建中…" : "注册/登录并创建项目"}
        </button>
        {error && <p className="status-bad">{error}</p>}
      </form>

      <div className="actions">
        <Link to="/projects/$projectId/quick" params={{ projectId: "demo" }}>
          演示壳（无后端）
        </Link>
      </div>
    </section>
  );
}
