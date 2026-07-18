import type { EvalRequest, EvalResultItem } from "./types";

interface EvalRunResponse {
  reports: EvalResultItem[];
}

export async function runEval(request: EvalRequest, signal?: AbortSignal): Promise<EvalResultItem[]> {
  const token = localStorage.getItem("token");
  const response = await fetch("/api/eval/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof (body as { detail?: string }).detail === "string"
        ? (body as { detail: string }).detail
        : `请求失败 (${response.status})`,
    );
  }

  const body = (await response.json()) as EvalRunResponse;
  return body.reports;
}

export async function runEvalStream(
  request: EvalRequest,
  onReport: (report: EvalResultItem) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem("token");
  const response = await fetch("/api/eval/run-stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof (body as { detail?: string }).detail === "string"
        ? (body as { detail: string }).detail
        : `请求失败 (${response.status})`,
    );
  }

  const reader = response.body?.getReader();
  if (!reader) throw new Error("不支持流式响应");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (!payload || payload === "[DONE]") continue;
        try {
          onReport(JSON.parse(payload) as EvalResultItem);
        } catch {
          // skip malformed SSE lines
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
