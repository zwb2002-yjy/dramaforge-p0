import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  requestEditingDirectorSuggestion,
  rejectEditingDirectorSuggestion,
  requestProactiveEditingDirectorSuggestion,
  routeEditingDirectorRepair,
  type EditSessionRead,
  type EditingRepairRoutingRead,
  type EditingDirectorSuggestionRead,
} from "./api";

type EditingSuggestionMutationInput = {
  projectId: string;
  sessionId: string;
  expectedSessionVersion: number;
  userInstruction: string;
  requestKey: string;
  proactive?: boolean;
  sequence: number;
};
type EditingSuggestionPreviewContext = {
  projectId: string;
  sessionId: string;
  sessionVersion: number;
};

function isSessionVersion(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Owns proposal observation/rejection/repair routing; never applies or saves a timeline. */
export function useEditingDirector({
  projectId,
  sessionId,
  session,
  onFeedback,
}: {
  projectId: string;
  sessionId?: string;
  session?: EditSessionRead;
  onFeedback: (message: string | null) => void;
}) {
  const currentSessionVersion = session?.version;
  const [suggestionInstruction, setSuggestionInstruction] = useState("");
  const [suggestionPreview, setSuggestionPreview] = useState<EditingDirectorSuggestionRead | null>(
    null,
  );
  const [suggestionPreviewContext, setSuggestionPreviewContext] =
    useState<EditingSuggestionPreviewContext | null>(null);
  const [suggestionStale, setSuggestionStale] = useState(false);
  const [suggestionError, setSuggestionError] = useState<string | null>(null);
  const [repairRouting, setRepairRouting] = useState<EditingRepairRoutingRead | null>(null);
  const [repairError, setRepairError] = useState<string | null>(null);
  const [selectedSuggestionOps, setSelectedSuggestionOps] = useState<Record<number, boolean>>({});
  const suggestionSequenceRef = useRef(0);
  const suggestionIdentityRef = useRef<EditingSuggestionPreviewContext | null>(null);

  suggestionIdentityRef.current =
    sessionId && isSessionVersion(currentSessionVersion)
      ? { projectId, sessionId, sessionVersion: currentSessionVersion }
      : null;

  useEffect(() => {
    // Proposals and late responses never cross a route or unmount boundary.
    setSuggestionInstruction("");
    setSuggestionPreview(null);
    setSuggestionPreviewContext(null);
    setSuggestionStale(false);
    setSuggestionError(null);
    setRepairRouting(null);
    setRepairError(null);
    setSelectedSuggestionOps({});
    suggestionSequenceRef.current += 1;
    return () => {
      suggestionSequenceRef.current += 1;
    };
  }, [projectId, sessionId]);

  const suggestionRequest = useMutation<
    EditingDirectorSuggestionRead,
    unknown,
    EditingSuggestionMutationInput
  >({
    mutationFn: ({
      projectId: requestProjectId,
      sessionId: requestSessionId,
      expectedSessionVersion,
      userInstruction,
      requestKey,
      proactive = false,
    }) =>
      proactive
        ? requestProactiveEditingDirectorSuggestion(
            requestProjectId,
            requestSessionId,
            expectedSessionVersion,
            requestKey,
          )
        : requestEditingDirectorSuggestion(requestProjectId, requestSessionId, {
            expected_session_version: expectedSessionVersion,
            user_instruction: userInstruction,
            request_key: requestKey,
          }),
    onSuccess: (result, variables) => {
      const currentIdentity = suggestionIdentityRef.current;
      if (
        variables.sequence !== suggestionSequenceRef.current ||
        !currentIdentity ||
        currentIdentity.projectId !== variables.projectId ||
        currentIdentity.sessionId !== variables.sessionId ||
        currentIdentity.sessionVersion !== variables.expectedSessionVersion
      ) {
        // A late response is intentionally ignored. It cannot become the
        // preview for a newer session/version/request.
        return;
      }
      setSuggestionPreview(result);
      setSuggestionPreviewContext(currentIdentity);
      setSuggestionStale(false);
      setSuggestionError(null);
      setSelectedSuggestionOps({});
    },
    onError: (error: unknown, variables) => {
      const currentIdentity = suggestionIdentityRef.current;
      if (
        variables.sequence !== suggestionSequenceRef.current ||
        !currentIdentity ||
        currentIdentity.projectId !== variables.projectId ||
        currentIdentity.sessionId !== variables.sessionId ||
        currentIdentity.sessionVersion !== variables.expectedSessionVersion
      ) {
        // A late error is just as stale as a late success; it must not replace
        // the error/preview belonging to the current route and version.
        return;
      }
      setSuggestionPreview(null);
      setSuggestionPreviewContext(null);
      setSuggestionStale(false);
      setSuggestionError(`建议请求失败：${errorMessage(error)}`);
      setSelectedSuggestionOps({});
    },
  });
  const suggestionRejection = useMutation({
    mutationFn: (input: {
      sequence: number;
      projectId: string;
      sessionId: string;
      proposalId: string;
      version: number;
    }) =>
      rejectEditingDirectorSuggestion(
        input.projectId,
        input.sessionId,
        input.proposalId,
        input.version,
      ),
    onSuccess: (_result, input) => {
      const identity = suggestionIdentityRef.current;
      if (
        input.sequence !== suggestionSequenceRef.current ||
        identity?.projectId !== input.projectId ||
        identity?.sessionId !== input.sessionId ||
        identity?.sessionVersion !== input.version
      )
        return;
      setSuggestionPreview(null);
      setSuggestionPreviewContext(null);
      setSuggestionStale(false);
      setSelectedSuggestionOps({});
      setSuggestionError(null);
      onFeedback("已持久拒绝当前剪辑建议，刷新后不会重新提交该分支。");
    },
    onError: (error: unknown, input) => {
      const identity = suggestionIdentityRef.current;
      if (
        input.sequence !== suggestionSequenceRef.current ||
        identity?.projectId !== input.projectId ||
        identity?.sessionId !== input.sessionId ||
        identity?.sessionVersion !== input.version
      )
        return;
      setSuggestionError(`拒绝保存失败，建议预览已保留：${errorMessage(error)}`);
    },
  });
  const rejectionResetRef = useRef(suggestionRejection.reset);
  rejectionResetRef.current = suggestionRejection.reset;

  const repairRoutingMutation = useMutation<
    EditingRepairRoutingRead,
    unknown,
    { sequence: number }
  >({
    mutationFn: () => {
      if (!sessionId || !session || !isSessionVersion(currentSessionVersion)) {
        throw new Error("无法判定修复路由：当前 EditSession 版本尚未加载。");
      }
      return routeEditingDirectorRepair(projectId, sessionId, {
        expected_session_version: currentSessionVersion,
        user_instruction: suggestionInstruction.trim(),
      });
    },
    onSuccess: (result, variables) => {
      const currentIdentity = suggestionIdentityRef.current;
      if (
        variables.sequence !== suggestionSequenceRef.current ||
        !currentIdentity ||
        currentIdentity.projectId !== projectId ||
        currentIdentity.sessionId !== sessionId ||
        currentIdentity.sessionVersion !== result.session_version
      ) {
        return;
      }
      setRepairRouting(result);
      setRepairError(null);
    },
    onError: (error: unknown, variables) => {
      if (variables.sequence !== suggestionSequenceRef.current) return;
      setRepairRouting(null);
      setRepairError(`修复路由判定失败：${errorMessage(error)}`);
    },
  });
  const suggestionRequestResetRef = useRef(suggestionRequest.reset);
  suggestionRequestResetRef.current = suggestionRequest.reset;
  const repairRoutingMutationResetRef = useRef(repairRoutingMutation.reset);
  repairRoutingMutationResetRef.current = repairRoutingMutation.reset;

  useEffect(() => {
    // Route changes invalidate any in-flight mutation state as well as the
    // local preview. The sequence guard above still ignores its eventual
    // response if the transport cannot be cancelled.
    suggestionRequestResetRef.current();
    repairRoutingMutationResetRef.current();
    rejectionResetRef.current();
  }, [projectId, sessionId]);

  useEffect(() => {
    if (!suggestionPreview || !suggestionPreviewContext) return;
    const currentIdentity = suggestionIdentityRef.current;
    if (
      !currentIdentity ||
      currentIdentity.projectId !== suggestionPreviewContext.projectId ||
      currentIdentity.sessionId !== suggestionPreviewContext.sessionId ||
      currentIdentity.sessionVersion !== suggestionPreviewContext.sessionVersion
    ) {
      setSuggestionStale(true);
    }
  }, [currentSessionVersion, projectId, sessionId, suggestionPreview, suggestionPreviewContext]);

  const suggestionIsStale =
    suggestionPreview !== null &&
    suggestionPreviewContext !== null &&
    (suggestionStale ||
      suggestionPreviewContext.projectId !== projectId ||
      suggestionPreviewContext.sessionId !== sessionId ||
      suggestionPreviewContext.sessionVersion !== currentSessionVersion);

  function submitSuggestion() {
    if (suggestionRejection.isPending) return;
    const userInstruction = suggestionInstruction.trim();
    if (!sessionId || !session || !isSessionVersion(currentSessionVersion)) {
      setSuggestionError("无法请求建议：当前 EditSession 版本尚未加载。");
      return;
    }
    if (!userInstruction) {
      setSuggestionError("请输入导演要求后再请求建议。");
      return;
    }
    const sequence = suggestionSequenceRef.current + 1;
    suggestionSequenceRef.current = sequence;
    setSuggestionPreview(null);
    setSuggestionPreviewContext(null);
    setSuggestionStale(false);
    setSuggestionError(null);
    suggestionRequest.mutate({
      projectId,
      sessionId,
      expectedSessionVersion: currentSessionVersion,
      userInstruction,
      requestKey: `editing-suggestion:${globalThis.crypto.randomUUID()}`,
      sequence,
    });
    setSelectedSuggestionOps({});
  }

  function submitProactiveSuggestion() {
    if (suggestionRejection.isPending) return;
    if (!sessionId || !session || !isSessionVersion(currentSessionVersion)) {
      setSuggestionError("无法主动分析：当前 EditSession 版本尚未加载。");
      return;
    }
    const sequence = suggestionSequenceRef.current + 1;
    suggestionSequenceRef.current = sequence;
    setSuggestionPreview(null);
    setSuggestionPreviewContext(null);
    setSuggestionStale(false);
    setSuggestionError(null);
    suggestionRequest.mutate({
      projectId,
      sessionId,
      expectedSessionVersion: currentSessionVersion,
      userInstruction: "",
      requestKey: `editing-proactive:${globalThis.crypto.randomUUID()}`,
      proactive: true,
      sequence,
    });
    setSelectedSuggestionOps({});
  }

  function submitRepairRouting() {
    if (!sessionId || !session || !isSessionVersion(currentSessionVersion)) {
      setRepairError("无法判定修复路由：当前 EditSession 版本尚未加载。");
      return;
    }
    const sequence = suggestionSequenceRef.current + 1;
    suggestionSequenceRef.current = sequence;
    setRepairRouting(null);
    setRepairError(null);
    repairRoutingMutation.mutate({ sequence });
  }

  function rejectSuggestion() {
    if (
      !suggestionPreview ||
      !sessionId ||
      suggestionIsStale ||
      suggestionRejection.isPending ||
      !isSessionVersion(currentSessionVersion)
    )
      return;
    suggestionRejection.mutate({
      sequence: suggestionSequenceRef.current,
      projectId,
      sessionId,
      proposalId: suggestionPreview.proposal_id,
      version: currentSessionVersion,
    });
  }

  function clearAfterSave() {
    suggestionSequenceRef.current += 1;
    setSuggestionPreview(null);
    setSuggestionPreviewContext(null);
    setSuggestionStale(false);
    setSuggestionError(null);
    setSelectedSuggestionOps({});
  }
  return {
    suggestionInstruction,
    setSuggestionInstruction,
    suggestionPreview,
    suggestionIsStale,
    suggestionError,
    repairRouting,
    repairError,
    selectedSuggestionOps,
    setSelectedSuggestionOps,
    suggestionPending: suggestionRequest.isPending,
    rejectionPending: suggestionRejection.isPending,
    repairPending: repairRoutingMutation.isPending,
    submitSuggestion,
    submitProactiveSuggestion,
    submitRepairRouting,
    rejectSuggestion,
    clearAfterSave,
  };
}
