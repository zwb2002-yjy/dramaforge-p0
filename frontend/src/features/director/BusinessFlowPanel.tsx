import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card } from "../../components/ui";
import { listBusinessFlowSteps, listBusinessFlows } from "./api";

type BusinessFlowPanelProps = {
  projectId: string;
  runId: string;
};

/**
 * Read-only view of a master run's BusinessFlows and their steps.
 *
 * The worker is the only driver of step execution; this panel never submits a
 * command and only re-reads the persisted status.
 */
export function BusinessFlowPanel({ projectId, runId }: BusinessFlowPanelProps) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const flows = useQuery({
    queryKey: ["business-flows", projectId, runId],
    queryFn: () => listBusinessFlows(projectId, runId),
    retry: false,
  });
  const steps = useQuery({
    queryKey: ["business-flow-steps", projectId, expanded],
    queryFn: () => listBusinessFlowSteps(projectId, expanded!),
    enabled: expanded !== null,
    retry: false,
  });

  return (
    <Card aria-label="业务流程">
      <div className="panel-header">
        <h3>业务流程</h3>
        <Button
          type="button"
          tone="ghost"
          disabled={flows.isFetching}
          onClick={() => void flows.refetch()}
        >
          刷新
        </Button>
      </div>
      {flows.isError && <p role="alert">业务流程读取失败，请稍后重试。</p>}
      {flows.isPending && <p role="status">正在读取业务流程…</p>}
      {flows.data?.length === 0 && <p className="muted">当前目标还没有业务流程。</p>}
      <ul className="business-flow-list">
        {(flows.data ?? []).map((flow) => (
          <li key={flow.id}>
            <Button
              type="button"
              tone="ghost"
              aria-expanded={expanded === flow.id}
              onClick={() => setExpanded(expanded === flow.id ? null : flow.id)}
            >
              {flow.definition_key} · {flow.status}
              {flow.wait_reason ? `（${flow.wait_reason}）` : ""}
            </Button>
            {expanded === flow.id && (
              <ul className="business-flow-steps">
                {steps.isPending && <li>正在读取步骤…</li>}
                {steps.isError && <li role="alert">步骤读取失败。</li>}
                {(steps.data ?? []).map((step) => (
                  <li key={step.id}>
                    {step.step_key} · {step.status}
                    {step.wait_reason ? `（${step.wait_reason}）` : ""}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
