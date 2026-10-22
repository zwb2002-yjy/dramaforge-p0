import {
  Alert,
  Button as AntButton,
  Checkbox,
  Descriptions,
  Divider,
  Spin,
  Typography,
} from "antd";
import type { ReactNode } from "react";
import { Drawer } from "../../components/ui";
import type { ShotExecutionPlanRead, ShotExecutionStage } from "./api";

const { Text, Paragraph } = Typography;

export interface ShotPreflightDrawerProps {
  open: boolean;
  onClose: () => void;
  stage: ShotExecutionStage;
  rawPrompt: string;
  plan: ShotExecutionPlanRead | null;
  isLoading: boolean;
  error?: Error | null;
  errorSummary?: string | null;
  recoveryAction?: ReactNode;
  dirty?: boolean;
  onSaveAndRecompute?: () => void | Promise<void>;
  onConfirmGenerate: () => void | Promise<void>;
  isGenerating?: boolean;
  onAcceptApproximationsChange?: (accepted: boolean) => void;
  approximationsAccepted?: boolean;
}

type CompilerContractPreview = {
  compile_level: "provider_contract";
  readiness: "contract_validated" | "blocked";
  transport_verified: false;
  account_verified: false;
  effective_options: Record<string, unknown>;
  transformations: string[];
  errors: string[];
  warnings: string[];
};

export function ShotPreflightDrawer({
  open,
  onClose,
  stage,
  rawPrompt,
  plan,
  isLoading,
  error,
  errorSummary,
  recoveryAction,
  dirty = false,
  onSaveAndRecompute,
  onConfirmGenerate,
  isGenerating = false,
  onAcceptApproximationsChange,
  approximationsAccepted = false,
}: ShotPreflightDrawerProps): ReactNode {
  const p = plan?.plan;
  // The generated API contract will be regenerated with the next OpenAPI sync.
  // This optional read-only field does not participate in the plan fingerprint.
  const compilerPreview = (
    plan as (ShotExecutionPlanRead & { compiler_contract_preview?: CompilerContractPreview | null }) | null
  )?.compiler_contract_preview;
  const references = p?.planned_references ?? [];
  const exactRefs = references.filter((r) => r.delivery === "exact");
  const approxRefs = references.filter((r) => r.delivery === "approximate");
  const unsupportedRefs = references.filter((r) => r.delivery === "unsupported");
  const capabilityGaps = p?.capability_gaps ?? [];
  const hasFatalGaps = capabilityGaps.some((g) => g.severity === "fatal");
  const hasWarningGaps = capabilityGaps.some((g) => g.severity === "warning");

  const hasUnacceptedApproximations =
    (hasWarningGaps || approxRefs.length > 0) && !approximationsAccepted;

  // A plan preview is not itself the Provider wire payload. Do not permit
  // confirmation when its execution-stage identity or effective duration is
  // incomplete, even if a malformed/old response reached this drawer.
  const durationConfirmed =
    stage !== "video" ||
    (typeof p?.duration_seconds === "number" &&
      Number.isSafeInteger(p.duration_seconds) &&
      p.duration_seconds > 0 &&
      p.effective_options?.duration_seconds === p.duration_seconds);
  const planStageConfirmed = p?.stage === stage;
  const canConfirm =
    !dirty &&
    !isLoading &&
    !error &&
    Boolean(plan) &&
    planStageConfirmed &&
    durationConfirmed &&
    !hasFatalGaps &&
    !hasUnacceptedApproximations;

  const actions = (
    <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
      <AntButton onClick={onClose} disabled={isGenerating}>
        取消
      </AntButton>
      {dirty && onSaveAndRecompute ? (
        <AntButton
          type="primary"
          onClick={() => void onSaveAndRecompute()}
          loading={isLoading}
          data-testid="preflight-save-recompute-btn"
        >
          保存并刷新预检
        </AntButton>
      ) : (
        <AntButton
          type="primary"
          onClick={() => void onConfirmGenerate()}
          loading={isGenerating}
          disabled={!canConfirm}
          data-testid="confirm-generate-button"
        >
          {isGenerating ? "提交中..." : "确认生成"}
        </AntButton>
      )}
    </div>
  );

  return (
    <Drawer
      open={open}
      onClose={onClose}
      title="本次发送核对"
      kicker="同源预检"
      size="wide"
      testId="shot-preflight-drawer"
      actions={actions}
    >
      {dirty && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: "16px" }}
          title="存在未保存的设计草稿"
          description="镜头设计或参数已发生变更。执行前必须先保存草稿并基于最新设计重算预检。"
        />
      )}

      {error && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: "16px" }}
          title="预检计算失败"
          description={
            <>
              {errorSummary ?? "无法编译当前方案，请检查输入并重新预检。"}
              {recoveryAction}
            </>
          }
        />
      )}

      {isLoading && (
        <div style={{ textAlign: "center", padding: "32px 0" }}>
          <Spin description="正在从服务端构建冻结计划..." />
        </div>
      )}

      {!isLoading && plan && (
        <div>
          <p className="df-shot-hint" data-testid="preflight-plan-boundary">
            当前显示服务端冻结的执行计划；最终供应商协议请求由 Worker 的 Provider Compiler
            编译，尚未提供逐字段同源 Payload 预览。
          </p>
          {!planStageConfirmed && (
            <Alert type="error" showIcon title="执行阶段不一致，请重新预检。" />
          )}
          {!durationConfirmed && (
            <Alert type="error" showIcon title="生成时长与有效参数未能一致确认，请重新预检。" />
          )}
          {/* Section A: 提示词与引用核对 */}
          <div data-testid="preflight-prompt-section">
            <Typography.Title level={5}>1. 原文与发送提示词核对</Typography.Title>
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="创作原始输入">
                <Text code>{rawPrompt || "（空）"}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="最终发送提示词">
                <Paragraph style={{ margin: 0 }}>{p?.prompt}</Paragraph>
              </Descriptions.Item>
              {p?.supports_prompt_override && (
                <Descriptions.Item label="提示词覆盖（覆盖槽已声明）">
                  {p?.prompt_override ? (
                    <Text code data-testid="preflight-prompt-override-value">
                      {p.prompt_override}
                    </Text>
                  ) : (
                    <Text type="secondary" data-testid="preflight-prompt-override-unset">
                      （未设置覆盖，按原始提示词发送）
                    </Text>
                  )}
                </Descriptions.Item>
              )}
              <Descriptions.Item label="参考资产">
                {references.length === 0 ? (
                  <Text type="secondary">无外部参考</Text>
                ) : (
                  <div>
                    {exactRefs.length > 0 && (
                      <div>
                        <Text type="success">✓ 完全匹配 ({exactRefs.length})：</Text>
                        {exactRefs.map((r, i) => (
                          <span key={i} style={{ marginLeft: 6 }}>
                            [{r.purpose} → {r.role || "默认槽"}]
                          </span>
                        ))}
                      </div>
                    )}
                    {approxRefs.length > 0 && (
                      <div>
                        <Text type="warning">⚠ 近似适配 ({approxRefs.length})：</Text>
                        {approxRefs.map((r, i) => (
                          <span key={i} style={{ marginLeft: 6 }}>
                            [{r.purpose}: {r.reason || "格式或尺寸适配"}]
                          </span>
                        ))}
                      </div>
                    )}
                    {unsupportedRefs.length > 0 && (
                      <div>
                        <Text type="danger">✕ 不支持 ({unsupportedRefs.length})：</Text>
                        {unsupportedRefs.map((r, i) => (
                          <span key={i} style={{ marginLeft: 6 }}>
                            [{r.purpose}: {r.reason}]
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </Descriptions.Item>
            </Descriptions>
          </div>

          <Divider style={{ margin: "16px 0" }} />

          {/* Section B: 目标模型与有效参数 */}
          <div data-testid="preflight-parameters-section">
            <Typography.Title level={5}>2. 目标模型与执行参数</Typography.Title>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="阶段">
                {stage === "video" ? "视频生成 (video)" : "关键帧图像 (image_keyframe)"}
              </Descriptions.Item>
              <Descriptions.Item label="输入模式">
                <Text code>{p?.mode_id}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="解析模型">
                <Text strong>{p?.resolved_model?.resolved_model_id ?? "未解析"}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="生成时长">
                {stage === "video"
                  ? p?.duration_seconds !== undefined && p?.duration_seconds !== null
                    ? `${p.duration_seconds} 秒`
                    : "未确定（不能提交生成）"
                  : "单帧静态"}
              </Descriptions.Item>
              <Descriptions.Item label="有效参数" span={2}>
                {p?.effective_options && Object.keys(p.effective_options).length > 0 ? (
                  <pre style={{ margin: 0, fontSize: "12px" }}>
                    {JSON.stringify(p.effective_options, null, 2)}
                  </pre>
                ) : (
                  <Text type="secondary">（继承自项目与模型合同默认值）</Text>
                )}
              </Descriptions.Item>
            </Descriptions>
          </div>

          {compilerPreview && (
            <div data-testid="preflight-compiler-contract-preview">
              <Typography.Title level={5}>编译器合同预览（不包含真实媒体传输）</Typography.Title>
              <Alert
                type={compilerPreview.readiness === "contract_validated" ? "info" : "warning"}
                showIcon
                title={
                  compilerPreview.readiness === "contract_validated"
                    ? "已通过只读编译器合同映射"
                    : "编译器合同暂未验证通过"
                }
                description="仅证明参数映射符合当前模型编译器。素材字节、传输地址、账户权限与最终发送请求尚未验证。"
              />
              <pre data-testid="preflight-compiler-options" style={{ fontSize: "12px" }}>
                {JSON.stringify(compilerPreview.effective_options, null, 2)}
              </pre>
              {compilerPreview.errors.length > 0 && (
                <Text type="warning">{compilerPreview.errors.join("、")}</Text>
              )}
            </div>
          )}

          <Divider style={{ margin: "16px 0" }} />

          {/* Section C: 近似与确认指纹 */}
          <div data-testid="preflight-fingerprint-section">
            <Typography.Title level={5}>3. 差异与确认指纹</Typography.Title>

            {(hasWarningGaps || approxRefs.length > 0) && (
              <div style={{ marginBottom: "12px" }}>
                <Alert
                  type={approximationsAccepted ? "info" : "warning"}
                  showIcon
                  title={approximationsAccepted ? "已确认接受模型近似适配" : "检测到模型近似适配"}
                  description={
                    <div>
                      {capabilityGaps
                        .filter((g) => g.severity === "warning")
                        .map((g, i) => (
                          <div key={i}>{g.reason}</div>
                        ))}
                      {capabilityGaps.filter((g) => g.severity === "warning").length === 0 &&
                        approxRefs.map((r, i) => (
                          <div key={i}>
                            {r.purpose}: {r.reason || "格式或尺寸适配"}
                          </div>
                        ))}
                      <div style={{ marginTop: "8px" }}>
                        <Checkbox
                          checked={approximationsAccepted}
                          onChange={(e) => onAcceptApproximationsChange?.(e.target.checked)}
                          data-testid="accept-approximations-checkbox"
                        >
                          我理解并接受以上模型近似适配
                        </Checkbox>
                      </div>
                    </div>
                  }
                />
              </div>
            )}

            {hasFatalGaps && (
              <div style={{ marginBottom: "12px" }}>
                <Alert
                  type="error"
                  showIcon
                  title="存在致命能力缺口，无法生成"
                  description={capabilityGaps
                    .filter((g) => g.severity === "fatal")
                    .map((g, i) => (
                      <div key={i}>{g.reason}</div>
                    ))}
                />
              </div>
            )}

            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="执行计划指纹 (SHA-256)">
                <Text copyable code>
                  {plan.plan_fingerprint}
                </Text>
              </Descriptions.Item>
            </Descriptions>
          </div>
        </div>
      )}
    </Drawer>
  );
}
