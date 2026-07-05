import request from "@/utils/request";
import type { RenameRequest, SessionCreateResponse, SessionListResponse, StatusResponse } from "./types";

export const getSessionList = (): Promise<SessionListResponse> => {
  return request.get("/chat/list");
};

export const createSession = (data: RenameRequest): Promise<SessionCreateResponse> => {
  return request.post("/chat/", data);
};

export const deleteSession = (sessionId: string): Promise<StatusResponse> => {
  return request.delete(`/chat/${sessionId}`);
};

export const renameSession = (sessionId: string, data: RenameRequest): Promise<StatusResponse> => {
  return request.patch(`/chat/${sessionId}`, data);
};
