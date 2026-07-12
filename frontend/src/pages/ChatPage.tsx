import {
  AppstoreAddOutlined,
  BulbOutlined,
  CloudUploadOutlined,
  InboxOutlined,
  PaperClipOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import {
  Actions,
  Attachments,
  Bubble,
  Conversations,
  FileCard,
  type FileCardProps,
  Sender,
  Think,
  ThoughtChain,
  type ThoughtChainItemType,
} from "@ant-design/x";
import type { ItemType } from "@ant-design/x/es/actions/interface";
import type { BubbleListRef } from "@ant-design/x/es/bubble";
import { useXChat, useXConversations } from "@ant-design/x-sdk";
import styled from "@emotion/styled";
import type { MenuProps, UploadFile, UploadProps } from "antd";
import { Alert, Badge, Checkbox, Flex, Input, Modal, message, Tooltip, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ChatMessage,
  ChatMessageInfo,
  ContentItem,
  FileItem,
  StreamChatParams,
  ToolItem,
  ToolType,
} from "@/api/chat";
import { createChatProvider, generateSessionTitle, getHistoryMessages, getToolList, transcribeAudio } from "@/api/chat";
import { createSession, deleteSession, getSessionList, renameSession } from "@/api/session";
import { SuperMarkdown } from "@/components/SuperMarkdown";

const defaultTypingConfig = {
  effect: "typing" as const,
  step: 2,
  interval: 80,
  keepPrefix: true,
};

type AvailableTool = {
  value: ToolType;
  label: string;
  description: string;
  default_enabled: boolean;
  requires: ToolType[];
};

const AUTO_TITLE_PREFIX = "新会话-";
const isAutoTitleName = (name: string): boolean => name.startsWith(AUTO_TITLE_PREFIX);

type ConversationItem = {
  key: string;
  label: string;
  isAutoTitle?: boolean;
};

const createAttachmentId = (prefix = "att"): string =>
  `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const fileToDataUri = (file: File): Promise<string> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
};

const resolveFileType = (url?: string): "image" | "audio" | "video" | "file" => {
  if (url?.startsWith("data:image")) return "image";
  if (url?.startsWith("data:audio")) return "audio";
  if (url?.startsWith("data:video")) return "video";
  const ext = url?.split("?")[0].split("#")[0].split("/").slice(-1)[0].split(".").slice(-1)[0].toLowerCase();
  if (ext && ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"].includes(ext)) return "image";
  if (ext && ["mp3", "wav", "aac", "flac", "ogg"].includes(ext)) return "audio";
  if (ext && ["mp4", "webm", "mov", "mkv"].includes(ext)) return "video";
  return "file";
};

export default function ChatPage() {
  const [attachments, setAttachments] = useState<UploadFile[]>([]);
  const [senderValue, setSenderValue] = useState("");
  const [availableTools, setAvailableTools] = useState<AvailableTool[]>([]);
  const [selectedTools, setSelectedTools] = useState<ToolType[]>([]);
  const [toolVisible, setToolVisible] = useState(false);
  const [attachmentVisible, setAttachmentVisible] = useState(false);
  const [isDeepThinking, setIsDeepThinking] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [speechRecording, setSpeechRecording] = useState(false);
  const [, setIsTranscribingSpeech] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const speechChunksRef = useRef<BlobPart[]>([]);
  const [chatProvider] = useState(() => createChatProvider());
  const messagesRef = useRef<ChatMessageInfo[]>([]);

  const conversationManager = useXConversations({
    defaultConversations: [],
    defaultActiveConversationKey: "",
  });
  const conversations = useMemo(
    () => conversationManager.conversations as ConversationItem[],
    [conversationManager.conversations],
  );
  const activeConversationKey = conversationManager.activeConversationKey;
  const { addConversation, removeConversation, setActiveConversationKey, setConversation, setConversations } =
    conversationManager;

  const {
    messages: messageInfos,
    onRequest,
    abort,
    isRequesting,
    isDefaultMessagesRequesting,
  } = useXChat<ChatMessage, ChatMessage, StreamChatParams>({
    provider: chatProvider,
    conversationKey: activeConversationKey || undefined,
    defaultMessages: async (info: { conversationKey?: string }) => {
      const conversationKey = info.conversationKey;
      if (!conversationKey) return [];
      try {
        setError(null);
        return await getHistoryMessages({ sessionId: String(conversationKey) });
      } catch (err) {
        const nextError = err instanceof Error ? err : new Error("获取历史记录失败");
        setError(nextError);
        message.error("获取历史记录失败");
        return [];
      }
    },
    requestPlaceholder: { role: "assistant", content: [] },
  });

  const hasUploadingAttachments = attachments.some((item) => item.status === "uploading");
  const listRef = useRef<BubbleListRef>(null);

  useEffect(() => {
    messagesRef.current = messageInfos;
  }, [messageInfos]);

  useEffect(() => {
    void (async () => {
      try {
        const response = await getToolList();
        const tools: AvailableTool[] = Object.entries(response.tools ?? {}).map(([value, info]) => ({
          value: value as ToolType,
          label: info.label,
          description: info.description,
          default_enabled: info.default_enabled ?? false,
          requires: (info.requires ?? []) as ToolType[],
        }));
        setAvailableTools(tools);
        setSelectedTools(tools.filter((tool) => tool.default_enabled).map((tool) => tool.value));
      } catch {
        message.error("获取工具列表失败");
      }
    })();
  }, []);

  const createNewConversation = useCallback(async () => {
    const defaultName = `${AUTO_TITLE_PREFIX}${Date.now().toString().slice(-4)}`;
    try {
      const res = await createSession({ name: defaultName });
      if (!res?.session_id) throw new Error("创建会话失败");
      const sessionId = res.session_id;
      addConversation({ key: sessionId, label: res.name || defaultName, isAutoTitle: true }, "prepend");
      setActiveConversationKey(sessionId);
      message.success("已开启新会话");
    } catch {
      message.error("创建会话失败，请稍后重试");
    }
  }, [addConversation, setActiveConversationKey]);

  const refreshSessionList = useCallback(async () => {
    try {
      const response = await getSessionList();
      const sessions = response?.sessions ?? [];
      const list: ConversationItem[] = sessions.map((session) => ({
        key: session.session_id,
        label: session.name,
        isAutoTitle: isAutoTitleName(session.name),
      }));
      setConversations(list);
      if (list.length === 0) {
        await createNewConversation();
        return;
      }
      if (!activeConversationKey) {
        setActiveConversationKey(list[0].key);
      }
    } catch {
      await createNewConversation();
    }
  }, [activeConversationKey, setActiveConversationKey, createNewConversation, setConversations]);

  useEffect(() => {
    void refreshSessionList();
  }, [refreshSessionList]);

  const handleToolsChange = useCallback(
    (values: ToolType[]) => {
      const next = new Set(values);
      for (const value of values) {
        const tool = availableTools.find((item) => item.value === value);
        for (const require of tool?.requires ?? []) {
          next.add(require);
        }
      }
      setSelectedTools(Array.from(next));
    },
    [availableTools],
  );

  const updateConversationTitleFromMessage = useCallback(
    async (messageText: string) => {
      if (!activeConversationKey) return;
      const target = conversations.find((item) => item.key === activeConversationKey);
      if (!target?.isAutoTitle) return;
      const normalized = messageText.replace(/\s+/g, " ").trim();
      if (!normalized) return;
      try {
        const response = await generateSessionTitle({ text: normalized });
        if (!response?.success || !response.title?.trim()) return;
        const generatedTitle = response.title.trim();
        await renameSession(activeConversationKey, { name: generatedTitle });
        setConversation(activeConversationKey, { ...target, label: generatedTitle, isAutoTitle: false });
      } catch {
        // ignore
      }
    },
    [activeConversationKey, conversations, setConversation],
  );

  const handleConversationSelect = useCallback(
    (value: string) => {
      if (!value || value === activeConversationKey) return;
      if (isRequesting) {
        message.warning("请先终止当前回答，再切换会话。");
        return;
      }
      setActiveConversationKey(value);
      setError(null);
      setAttachments([]);
    },
    [activeConversationKey, isRequesting, setActiveConversationKey],
  );

  const handleConversationMenuCommand = useCallback(
    async (command: string, item: ConversationItem) => {
      if (!item?.key) return;
      if (command === "rename") {
        const newName = await new Promise<string | null>((resolve) => {
          let value = item.label;
          Modal.confirm({
            title: "重命名会话",
            content: (
              <Input
                defaultValue={item.label}
                autoFocus
                onChange={(e) => {
                  value = e.target.value;
                }}
              />
            ),
            okText: "确定",
            cancelText: "取消",
            onOk: async () => {
              if (!value.trim()) {
                message.warning("会话名称不能为空");
                throw new Error("invalid");
              }
              resolve(value.trim());
            },
            onCancel: () => resolve(null),
          });
        });
        if (!newName) return;
        try {
          await renameSession(item.key, { name: newName });
          setConversation(item.key, { ...item, label: newName, isAutoTitle: false });
          message.success("会话重命名成功");
        } catch {
          message.error("重命名会话失败");
        }
        return;
      }
      if (command === "delete") {
        Modal.confirm({
          title: "删除确认",
          content: "确定删除当前会话吗？",
          okText: "删除",
          cancelText: "取消",
          onOk: async () => {
            try {
              await deleteSession(item.key);
              removeConversation(item.key);
              if (activeConversationKey === item.key) {
                const fallback = conversations.find((c) => c.key !== item.key);
                if (fallback) setActiveConversationKey(fallback.key);
                else await createNewConversation();
              }
              message.success("会话已删除");
            } catch {
              message.error("删除会话失败");
            }
          },
        });
      }
    },
    [
      activeConversationKey,
      conversations,
      createNewConversation,
      removeConversation,
      setActiveConversationKey,
      setConversation,
    ],
  );

  const conversationMenu = useCallback(
    (item: { key?: string }): MenuProps => ({
      items: [
        { key: "rename", label: "重命名" },
        { key: "delete", label: "删除" },
      ],
      onClick: (info) => {
        const target = conversations.find((c) => c.key === item.key) as ConversationItem | undefined;
        if (target) void handleConversationMenuCommand(String(info.key), target);
      },
    }),
    [conversations, handleConversationMenuCommand],
  );

  const handleSubmit = useCallback(async () => {
    if (!senderValue.trim() || isRequesting) return;
    if (hasUploadingAttachments) {
      message.warning("文件上传中，请稍后发送");
      return;
    }
    if (!activeConversationKey) {
      message.warning("缺少会话信息，无法发送消息");
      return;
    }

    const fileItems: FileItem[] = attachments
      .filter((item) => item.url && item.name)
      .map((item) => ({
        part: "file" as const,
        name: item.name ?? "文件",
        url: item.url as string,
      }));

    setError(null);
    listRef.current?.scrollTo({ top: "bottom" });
    const messageText = senderValue;
    setSenderValue("");
    setAttachments([]);

    await updateConversationTitleFromMessage(messageText);

    onRequest({
      model: "deepseek-v4-flash",
      thinking: isDeepThinking,
      sessionId: activeConversationKey,
      text: messageText,
      files: fileItems,
      tools: selectedTools,
    });
  }, [
    activeConversationKey,
    attachments,
    hasUploadingAttachments,
    isDeepThinking,
    isRequesting,
    selectedTools,
    senderValue,
    onRequest,
    updateConversationTitleFromMessage,
  ]);

  const handleCancel = useCallback(() => {
    if (!isRequesting) return;
    abort();
    message.info("已终止生成");
  }, [abort, isRequesting]);

  const handleAttachmentUpload: UploadProps["customRequest"] = async (options) => {
    const { file, onSuccess, onError } = options;
    if (!(file instanceof File)) {
      onError?.(new Error("文件格式错误"));
      return;
    }
    const uid = createAttachmentId("upload");
    const uploadItem: UploadFile = {
      uid,
      name: file.name,
      status: "uploading",
      originFileObj: file as UploadFile["originFileObj"],
    };
    setAttachments((prev) => [...prev, uploadItem]);
    try {
      const dataUri = await fileToDataUri(file);
      setAttachments((prev) =>
        prev.map((item) => (item.uid === uid ? { ...item, status: "done", url: dataUri } : item)),
      );
      onSuccess?.({ success: true }, file);
      message.success(`文件 ${file.name} 上传成功`);
    } catch (error) {
      setAttachments((prev) => prev.filter((item) => item.uid !== uid));
      const err = error instanceof Error ? error : new Error(String(error || ""));
      onError?.(err);
      message.error(err.message || "文件上传失败");
    }
  };

  const handleSpeechRecordingChange = useCallback(async (nextRecording: boolean) => {
    if (nextRecording) {
      if (!("mediaDevices" in navigator) || !navigator.mediaDevices.getUserMedia) {
        message.error("当前浏览器不支持录音");
        setSpeechRecording(false);
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const recorder = new MediaRecorder(stream);
        mediaStreamRef.current = stream;
        mediaRecorderRef.current = recorder;
        speechChunksRef.current = [];

        recorder.ondataavailable = (event: BlobEvent) => {
          if (event.data.size > 0) speechChunksRef.current.push(event.data);
        };
        recorder.onstop = () => {
          const chunks = speechChunksRef.current;
          speechChunksRef.current = [];
          setSpeechRecording(false);
          mediaRecorderRef.current = null;
          for (const track of mediaStreamRef.current?.getTracks() ?? []) {
            track.stop();
          }
          mediaStreamRef.current = null;
          if (!chunks.length) return;
          const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
          if (blob.size === 0) return;
          void (async () => {
            setIsTranscribingSpeech(true);
            try {
              const response = await transcribeAudio(blob, `recording-${Date.now()}.webm`);
              if (!response.success) throw new Error(response.status || "语音转写失败");
              const text = response.text?.trim();
              if (!text) return;
              setSenderValue((prev) => (prev ? `${prev.trimEnd()}\n${text}` : text));
              message.success("语音识别成功");
            } catch (err) {
              message.error(err instanceof Error ? err.message : "语音转写失败");
            } finally {
              setIsTranscribingSpeech(false);
            }
          })();
        };
        recorder.start();
        setSpeechRecording(true);
      } catch {
        setSpeechRecording(false);
        message.error("无法开始录音，请检查麦克风权限");
      }
      return;
    }
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    } else {
      setSpeechRecording(false);
    }
  }, []);

  const bubbleItems = useMemo(() => {
    const renderContentItems = (contentItems: ContentItem[] | undefined, role: ChatMessage["role"]) => {
      if (!contentItems?.length) return { nodes: null, copyText: "" };
      const nodes: React.ReactNode[] = [];
      let copyText = "";
      let index = 0;

      while (index < contentItems.length) {
        const current = contentItems[index];
        if (current.part === "text") {
          let mergedText = current.content ?? "";
          let nextIndex = index + 1;
          while (nextIndex < contentItems.length && contentItems[nextIndex].part === "text") {
            mergedText += (contentItems[nextIndex] as ContentItem & { part: "text" }).content ?? "";
            nextIndex += 1;
          }
          nodes.push(
            role === "user" ? (
              <Typography.Paragraph key={`text-${index}`} style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>
                {mergedText}
              </Typography.Paragraph>
            ) : (
              <SuperMarkdown key={`text-${index}`} streaming={{ hasNextChunk: current.status !== "success" }}>
                {mergedText}
              </SuperMarkdown>
            ),
          );
          copyText += mergedText;
          index = nextIndex;
          continue;
        }
        if (current.part === "reasoning") {
          let mergedReasoning = current.reasoning ?? "";
          let nextIndex = index + 1;
          while (nextIndex < contentItems.length && contentItems[nextIndex].part === "reasoning") {
            mergedReasoning += (contentItems[nextIndex] as ContentItem & { part: "reasoning" }).reasoning ?? "";
            nextIndex += 1;
          }
          nodes.push(
            <Think key={`reasoning-${index}`} title="深度思考" defaultExpanded={current.status !== "success"}>
              {mergedReasoning}
            </Think>,
          );
          index = nextIndex;
          continue;
        }
        if (current.part === "file") {
          const fileItems: FileCardProps[] = [];
          let nextIndex = index;
          while (nextIndex < contentItems.length && contentItems[nextIndex].part === "file") {
            const file = contentItems[nextIndex];
            if (file.part === "file") {
              fileItems.push({
                name: file.name ?? "文件",
                src: file.url,
                type: resolveFileType(file.url),
              });
            }
            nextIndex += 1;
          }
          if (fileItems.length) nodes.push(<FileCard.List key={`file-${index}`} items={fileItems} />);
          index = nextIndex;
          continue;
        }
        if (current.part === "tool") {
          const toolItems: ToolItem[] = [];
          let nextIndex = index;
          while (nextIndex < contentItems.length && contentItems[nextIndex].part === "tool") {
            toolItems.push(contentItems[nextIndex] as ToolItem);
            nextIndex += 1;
          }
          if (toolItems.length) {
            const thoughtItems: ThoughtChainItemType[] = toolItems.map((tool) => ({
              title: tool.name,
              content: (
                <Flex vertical>
                  {tool.args ? (
                    <>
                      <ThoughtChain.Item variant="solid" title="调用工具" icon={<ToolOutlined />} />
                      <Typography.Text type="secondary">
                        {typeof tool.args === "string" ? tool.args : JSON.stringify(tool.args)}
                      </Typography.Text>
                    </>
                  ) : null}
                  {tool.result ? (
                    <>
                      <ThoughtChain.Item variant="solid" title="返回结果" icon={<BulbOutlined />} />
                      <Typography.Text type="secondary">
                        {typeof tool.result === "string" ? tool.result : JSON.stringify(tool.result)}
                      </Typography.Text>
                    </>
                  ) : null}
                  {tool.files?.length ? (
                    <>
                      <ThoughtChain.Item variant="solid" title="多媒体结果" icon={<InboxOutlined />} />
                      <FileCard.List
                        items={tool.files.map((file) => ({
                          name: file.name ?? "文件",
                          src: file.url,
                          type: file.type === "document" || file.type === "binary" ? "file" : resolveFileType(file.url),
                        }))}
                      />
                    </>
                  ) : null}
                </Flex>
              ),
              collapsible: true,
              status: tool.status,
            }));
            nodes.push(<ThoughtChain key={`tool-${index}`} items={thoughtItems} />);
          }
          index = nextIndex;
          continue;
        }
        index += 1;
      }
      return { nodes, copyText };
    };

    return messageInfos.map((info) => {
      const item = info.message;
      const { nodes, copyText } = renderContentItems(item.content, item.role);
      const actionsItems: ItemType[] = [{ key: "copy", actionRender: <Actions.Copy text={copyText} /> }];
      return {
        key: String(info.id),
        role: item.role,
        status: info.status,
        loading: info.status === "loading",
        content: (
          <MessageContent>
            {nodes}
            <Actions items={actionsItems} />
          </MessageContent>
        ),
        streaming: info.status === "updating",
        typing: item.role === "assistant" && info.status === "updating" ? defaultTypingConfig : false,
      };
    });
  }, [messageInfos]);

  const conversationItems = useMemo(
    () => conversations.map((item) => ({ key: item.key, label: item.label })),
    [conversations],
  );

  return (
    <ChatWrap>
      <ChatLayout>
        <Sidebar>
          <Conversations
            items={conversationItems}
            activeKey={activeConversationKey ?? undefined}
            onActiveChange={handleConversationSelect}
            menu={conversationMenu}
            creation={{
              label: "创建新会话",
              icon: <AppstoreAddOutlined />,
              onClick: createNewConversation,
            }}
          />
        </Sidebar>
        <Main>
          {error ? <Alert type="error" title={error.message} closable style={{ marginBottom: 8 }} /> : null}
          {isDefaultMessagesRequesting ? (
            <Alert type="info" title="历史记录加载中..." showIcon style={{ marginBottom: 8 }} />
          ) : null}

          <ChatContent>
            <Bubble.List
              ref={listRef}
              items={bubbleItems}
              autoScroll
              role={{
                user: { placement: "end", variant: "filled" },
                assistant: { placement: "start", variant: "outlined" },
              }}
            />
          </ChatContent>

          <Sender
            value={senderValue}
            onChange={(value) => setSenderValue(value)}
            onSubmit={handleSubmit}
            onCancel={handleCancel}
            loading={isRequesting}
            allowSpeech={{
              recording: speechRecording,
              onRecordingChange: handleSpeechRecordingChange,
            }}
            autoSize={{ minRows: 1, maxRows: 10 }}
            placeholder="请输入问题... (可直接粘贴文件)"
            submitType="enter"
            header={
              <SenderTop>
                <Sender.Header title="附件上传" open={attachmentVisible} onOpenChange={setAttachmentVisible}>
                  <AttachmentPanel>
                    <Attachments
                      items={attachments}
                      multiple
                      maxCount={8}
                      customRequest={handleAttachmentUpload}
                      onRemove={(file) => setAttachments((prev) => prev.filter((item) => item.uid !== file.uid))}
                      overflow="wrap"
                      placeholder={(type) =>
                        type === "drop"
                          ? { icon: <InboxOutlined />, title: "拖拽文件到此处上传", description: "单个文件不超过10MB" }
                          : {
                              icon: <CloudUploadOutlined />,
                              title: "在此处上传文件",
                              description: "单个文件不超过10MB",
                            }
                      }
                    />
                  </AttachmentPanel>
                </Sender.Header>

                <Sender.Header title="工具选择" open={toolVisible} onOpenChange={setToolVisible}>
                  <ToolSelector>
                    <Checkbox
                      indeterminate={selectedTools.length > 0 && selectedTools.length < availableTools.length}
                      checked={availableTools.length > 0 && selectedTools.length === availableTools.length}
                      disabled={isRequesting || availableTools.length === 0}
                      onChange={(e) => {
                        if (e.target.checked) setSelectedTools(availableTools.map((t) => t.value));
                        else setSelectedTools([]);
                      }}
                      style={{ marginBottom: 8 }}
                    >
                      全选/全不选
                    </Checkbox>
                    <Checkbox.Group
                      value={selectedTools}
                      onChange={(values) => handleToolsChange(values as ToolType[])}
                    >
                      <Flex wrap="wrap" gap="8px" style={{ width: "100%" }}>
                        {availableTools.map((tool) => {
                          const lockedBy = availableTools.filter(
                            (item) =>
                              item.value !== tool.value &&
                              selectedTools.includes(item.value) &&
                              item.requires.includes(tool.value),
                          );
                          const isLocked = lockedBy.length > 0;
                          return (
                            <ToolOptionRow key={tool.value}>
                              <Checkbox value={tool.value} disabled={isRequesting || isLocked}>
                                <ToolLabel>{tool.label}</ToolLabel>
                                <ToolDesc>
                                  {tool.description}
                                  {isLocked ? `（由 ${lockedBy.map((item) => item.label).join("、")} 依赖）` : ""}
                                </ToolDesc>
                              </Checkbox>
                            </ToolOptionRow>
                          );
                        })}
                      </Flex>
                    </Checkbox.Group>
                  </ToolSelector>
                </Sender.Header>
              </SenderTop>
            }
            prefix={
              <SenderPrefix>
                <Tooltip title="附件上传">
                  <Sender.Switch
                    icon={<PaperClipOutlined />}
                    value={attachmentVisible}
                    onChange={setAttachmentVisible}
                    disabled={isRequesting}
                  />
                </Tooltip>
                <Tooltip title={selectedTools.length > 0 ? `工具选择（已选 ${selectedTools.length} 个）` : "工具选择"}>
                  <Badge count={selectedTools.length} size="small" offset={[-2, 2]} color="var(--primary-color)">
                    <Sender.Switch
                      icon={<ToolOutlined />}
                      value={toolVisible}
                      onChange={setToolVisible}
                      disabled={isRequesting}
                    />
                  </Badge>
                </Tooltip>
                <Tooltip title="深度思考">
                  <Sender.Switch icon={<BulbOutlined />} value={isDeepThinking} onChange={setIsDeepThinking} />
                </Tooltip>
              </SenderPrefix>
            }
          />
        </Main>
      </ChatLayout>
    </ChatWrap>
  );
}

const ChatWrap = styled("div")({
  height: "calc(100vh - 160px)",
  padding: "0 16px 16px",
});

const ChatLayout = styled("div")({
  height: "100%",
  display: "flex",
  gap: "16px",
  overflow: "hidden",
});

const Sidebar = styled("aside")({
  flex: "0 0 280px",
  minWidth: "240px",
  display: "flex",
  flexDirection: "column",
});

const Main = styled("section")({
  flex: "1",
  display: "flex",
  flexDirection: "column",
  gap: "12px",
  overflow: "hidden",
});

const ChatContent = styled("div")({
  flex: "1",
  minHeight: "0",
  display: "flex",
  flexDirection: "column",
});

const MessageContent = styled("div")({
  display: "flex",
  flexDirection: "column",
  gap: "12px",
});

const SenderPrefix = styled("div")({
  display: "flex",
  alignItems: "center",
  gap: "8px",
});

const SenderTop = styled("div")({
  display: "flex",
});

const ToolSelector = styled("div")({
  display: "flex",
  flexDirection: "column",
  gap: "12px",
  width: "420px",
});

const ToolOptionRow = styled("div")({
  padding: "6px 8px",
  borderRadius: "6px",
  "&:hover": { background: "var(--bg-hover)" },
  width: "calc(50% - 4px)",
});

const ToolLabel = styled("div")({
  fontSize: "13px",
  fontWeight: "600",
});

const ToolDesc = styled("div")({
  fontSize: "12px",
  color: "var(--font-secondary)",
});

const AttachmentPanel = styled("div")({
  display: "flex",
  flexDirection: "column",
  gap: "12px",
  width: "360px",
});
