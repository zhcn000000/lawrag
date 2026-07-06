import { getAuthHeaders } from "./chat";
import type { DocumentUploadResponse } from "./types";

export const uploadDocument = async (file: File): Promise<DocumentUploadResponse> => {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch("/api/rag/documents/upload", {
    method: "POST",
    headers: {
      Accept: "application/json",
      ...getAuthHeaders(),
    },
    body: formData,
  });

  if (!response.ok) {
    throw new Error("文档上传失败");
  }

  return (await response.json()) as DocumentUploadResponse;
};
