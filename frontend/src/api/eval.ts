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
