import {
  AbstractChatProvider,
  type DefaultMessageInfo,
  type MessageInfo,
  type SSEOutput,
  XRequest,
  type XRequestOptions,
} from "@ant-design/x-sdk";
import type { ChatTitleRequest, ChatTitleResponse, TranscriptionResponse } from "./types";

export const getAuthHeaders = (): Record<string, string> => {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
};

export type ToolType = "sql_toolkit" | "rag_toolkit" | "code_toolkit" | "web_toolkit";

export type ToolItem = {
  part: "tool";
  id: string;
  name: string;
  args?: Record<string, unknown> | string;
  result?: string;
  status?: "loading" | "success" | "error";
};

export type FileItem = {
  part: "file";
  name?: string;
  url: string;
  type?: "binary" | "text" | "image" | "video" | "audio" | "document";
};

export type ReasoningItem = {
  part: "reasoning";
  reasoning: string;
  status?: "updating" | "success" | "error";
};

export type TextItem = {
  part: "text";
  content: string;
  status?: "updating" | "success" | "error";
};

export type ContentItem = TextItem | FileItem | ToolItem | ReasoningItem;

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content?: ContentItem[];
  success?: boolean;
  status?: "error" | "local" | "loading" | "updating" | "success" | "abort";
}

export type ChatMessageInfo = MessageInfo<ChatMessage>;
export type ChatDefaultMessageInfo = DefaultMessageInfo<ChatMessage>;

export type StreamChatParams = {
  sessionId: string;
  model: string;
  thinking: boolean;
  text: string;
  files?: FileItem[];
  tools?: ToolType[];
};

type HistoryParams = {
  sessionId: string;
};

type BackendFile = {
  name?: string | null;
  url: string;
  type?: "binary" | "text" | "image" | "video" | "audio" | "document";
};

type BackendToolCall = {
  id: string;
  name: string;
  args?: Record<string, unknown> | string;
};

type BackendMessage = {
  role: "user" | "assistant" | "system" | "tool";
  content?: string | null;
  reasoning?: string | null;
  files?: Array<string | BackendFile> | null;
  tool_calls?: BackendToolCall[] | null;
  name?: string | null;
  tool_call_id?: string;
  success?: boolean;
};

type ChatStreamChunk = SSEOutput;

const normalizeFiles = (files?: Array<string | BackendFile> | null): FileItem[] | undefined => {
  if (!files || files.length === 0) return undefined;
  return files.map((file) => {
    if (typeof file === "string") {
      return { part: "file", name: "文件", url: file };
    }
    return {
      part: "file",
      name: file.name ?? undefined,
      url: file.url,
      type: file.type,
    };
  });
};

const formatJson = (value?: unknown): string => {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

const formatToolResult = (content?: string | null, files?: FileItem[]): string => {
  const parts: string[] = [];
  if (content) {
    parts.push(content);
  }
  if (files?.length) {
    const fileLines = files.map((file) => `- ${file.name ?? "文件"}: ${file.url}`);
    parts.push(`文件列表:\n${fileLines.join("\n")}`);
  }
  return parts.join("\n\n").trim();
};

const appendReasoningItem = (items: ContentItem[], reasoning?: string | null, success?: boolean) => {
  const last = items[items.length - 1];
  if (last?.part === "reasoning") {
    if (reasoning) {
      last.reasoning += reasoning;
    }
    if (success === true) {
      last.status = "success";
    } else if (success === false) {
      last.status = "error";
    } else {
      last.status = "updating";
    }
    return;
  }
  if (reasoning) {
    items.push({ part: "reasoning", reasoning, status: "updating" });
  }
};

const appendTextItem = (items: ContentItem[], text?: string | null, success?: boolean) => {
  const last = items[items.length - 1];
  if (last?.part === "text") {
    if (text) {
      last.content += text;
    }
    if (success === true) {
      last.status = "success";
    } else if (success === false) {
      last.status = "error";
    } else {
      last.status = "updating";
    }
    return;
  }
  if (text) {
    items.push({ part: "text", content: text, status: "updating" });
  }
};

const appendFiles = (items: ContentItem[], files?: Array<string | BackendFile> | null) => {
  const normalized = normalizeFiles(files) ?? [];
  if (normalized.length) {
    items.push(...normalized);
  }
};

const appendToolCalls = (items: ContentItem[], toolCalls?: BackendToolCall[] | null) => {
  if (!toolCalls?.length) return;
  const newToolCalls: ToolItem[] = toolCalls.map((tc) => ({
    part: "tool",
    id: tc.id,
    name: tc.name,
    args: formatJson(tc.args),
    status: "loading",
  }));
  items.push(...newToolCalls);
};

const mergeToolResult = (
  items: ContentItem[],
  toolCallId?: string,
  success?: boolean,
  content?: string | null,
  files?: Array<string | BackendFile> | null,
) => {
  if (!toolCallId) return;
  const resultText = formatToolResult(content ?? undefined, normalizeFiles(files));
  if (!resultText) return;
  for (const item of items) {
    if (item.part === "tool" && item.id === toolCallId) {
      item.result = resultText;
      if (success === true) {
        item.status = "success";
      } else if (success === false) {
        item.status = "error";
      }
      return;
    }
  }
};

const parseSsePayload = (raw: string): BackendMessage | null => {
  if (!raw || raw === "[DONE]") return null;
  try {
    return JSON.parse(raw) as BackendMessage;
  } catch {
    return null;
  }
};

const parseChunkPayloads = (chunk?: ChatStreamChunk): BackendMessage[] => {
  if (!chunk) return [];
  const data = chunk.data;
  if (!data) return [];
  return data
    .split("\n")
    .map((line: string) => line.trim())
    .filter(Boolean)
    .map((line: string) => line.replace(/^data:\s?/, ""))
    .map((line: string) => parseSsePayload(line))
    .filter((payload: BackendMessage | null): payload is BackendMessage => payload !== null);
};

const applyPayloadToAssistant = (currentMessage: ChatMessage, payload: BackendMessage): ChatMessage => {
  const nextMessage = structuredClone(currentMessage);
  nextMessage.content = nextMessage.content ?? [];

  if (payload.success !== undefined) {
    nextMessage.success = payload.success;
  }

  if (payload.role === "assistant") {
    appendReasoningItem(nextMessage.content, payload.reasoning, payload.success);
    appendTextItem(nextMessage.content, payload.content, payload.success);
    appendFiles(nextMessage.content, payload.files);
    appendToolCalls(nextMessage.content, payload.tool_calls);
  } else if (payload.role === "tool") {
    mergeToolResult(nextMessage.content, payload.tool_call_id, payload.success, payload.content, payload.files);
  }

  return nextMessage;
};

const chatRequestFetch = async (
  baseURL: Parameters<typeof fetch>[0],
  options: XRequestOptions<StreamChatParams, ChatStreamChunk, ChatMessage>,
): Promise<Response> => {
  const params = options.params;
  if (!params?.sessionId) {
    throw new Error("缺少会话信息，无法发送消息");
  }

  const { sessionId, ...payload } = params;
  const { headers, params: _params, ...requestInit } = options;

  return fetch(`${String(baseURL)}/${sessionId}/stream`, {
    ...requestInit,
    method: "POST",
    headers: {
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      ...headers,
      ...getAuthHeaders(),
    },
    body: JSON.stringify(payload),
  });
};

class RAGBuildChatProvider extends AbstractChatProvider<ChatMessage, StreamChatParams, ChatStreamChunk> {
  transformParams(
    requestParams: Partial<StreamChatParams>,
    options: XRequestOptions<StreamChatParams, ChatStreamChunk, ChatMessage>,
  ): StreamChatParams {
    if (!requestParams.sessionId) {
      throw new Error("缺少会话信息，无法发送消息");
    }

    return {
      ...(options.params ?? {}),
      ...(requestParams ?? {}),
    } as StreamChatParams;
  }

  transformLocalMessage(requestParams: Partial<StreamChatParams>): ChatMessage {
    const text = requestParams.text?.trim() ?? "";
    const files = requestParams.files ?? [];
    return {
      role: "user",
      content: [{ part: "text", content: text }, ...files],
    };
  }

  transformMessage(info: {
    originMessage?: ChatMessage;
    chunk: ChatStreamChunk;
    chunks: ChatStreamChunk[];
    status: ChatMessage["status"];
    responseHeaders: Headers;
  }): ChatMessage {
    const { originMessage, chunk } = info;
    let nextMessage: ChatMessage = structuredClone(originMessage ?? { role: "assistant", content: [] });
    if (chunk) {
      const payloads = parseChunkPayloads(chunk);
      for (const payload of payloads) {
        nextMessage = applyPayloadToAssistant(nextMessage, payload);
      }
    }
    return nextMessage;
  }
}

export const createChatProvider = () => {
  return new RAGBuildChatProvider({
    request: XRequest<StreamChatParams, ChatStreamChunk, ChatMessage>("/api/chat", {
      manual: true,
      fetch: chatRequestFetch,
    }),
  });
};

export const getHistoryMessages = async (params: HistoryParams): Promise<ChatDefaultMessageInfo[]> => {
  const response = await fetch(`/api/chat/${params.sessionId}/history`, {
    method: "GET",
    headers: {
      Accept: "application/json",
      ...getAuthHeaders(),
    },
  });
  if (!response.ok) {
    throw new Error("获取历史记录失败");
  }

  const data = (await response.json()) as { messages?: BackendMessage[] };
  const rawMessages = data.messages ?? [];
  const merged: ChatDefaultMessageInfo[] = [];
  let pendingAssistant: ChatMessage | null = null;
  let assistantIndex = 0;

  const flushAssistant = () => {
    if (pendingAssistant?.content?.length) {
      merged.push({
        id: `assistant-${assistantIndex}`,
        status: "success",
        message: pendingAssistant,
      });
      assistantIndex += 1;
    }
    pendingAssistant = null;
  };

  rawMessages.forEach((msg, index) => {
    if (msg.role === "user") {
      flushAssistant();
      const contentItems: ContentItem[] = [];
      appendTextItem(contentItems, msg.content, msg.success);
      appendFiles(contentItems, msg.files);
      merged.push({
        id: `user-${index}`,
        status: "success",
        message: {
          role: "user",
          content: contentItems,
          success: msg.success,
        },
      });
      return;
    }

    if (msg.role === "assistant") {
      if (!pendingAssistant) {
        pendingAssistant = {
          role: "assistant",
          content: [],
          success: msg.success,
        };
      }
      const contentItems = pendingAssistant.content ?? [];
      pendingAssistant.content = contentItems;
      appendReasoningItem(contentItems, msg.reasoning, msg.success);
      appendTextItem(contentItems, msg.content, msg.success);
      appendToolCalls(contentItems, msg.tool_calls);
      appendFiles(contentItems, msg.files);
      return;
    }

    if (msg.role === "tool") {
      if (!pendingAssistant) {
        pendingAssistant = {
          role: "assistant",
          content: [],
          success: msg.success,
        };
      }
      mergeToolResult(pendingAssistant.content ?? [], msg.tool_call_id, msg.success, msg.content, msg.files);
    }
  });

  flushAssistant();

  return merged;
};

export const generateSessionTitle = async (payload: ChatTitleRequest): Promise<ChatTitleResponse> => {
  const response = await fetch("/api/chat/title", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...getAuthHeaders(),
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error("生成标题失败");
  }

  return (await response.json()) as ChatTitleResponse;
};

export const transcribeAudio = async (audio: Blob, fileName = "recording.webm"): Promise<TranscriptionResponse> => {
  const formData = new FormData();
  formData.append("file", audio, fileName);

  const response = await fetch("/api/chat/transcribe", {
    method: "POST",
    headers: {
      Accept: "application/json",
      ...getAuthHeaders(),
    },
    body: formData,
  });

  if (!response.ok) {
    throw new Error("语音转写失败");
  }

  return (await response.json()) as TranscriptionResponse;
};
