import { Outlet, createRootRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { Alert } from "../components/ui";
import { WorkstationShell } from "../components/workstation/WorkstationShell";
import { apiGet } from "../lib/api";

export const rootRoute = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  const {data}=useQuery({
    queryKey:["system","runtime-admission"],
    queryFn:()=>apiGet<{runtime_admission_mode: string}>("/api/v1/status"),
    staleTime:30000,
    retry:false,
  });
  return (
    <WorkstationShell>
      {data?.runtime_admission_mode==="maintenance" && <Alert type="warning" description="实例维护中，暂不能开始新操作。"/>}
      {data?.runtime_admission_mode==="recovery_only" && <Alert type="warning" description="仅恢复已有任务，可查看原回执。"/>}
      <Outlet />
    </WorkstationShell>
  );
}
