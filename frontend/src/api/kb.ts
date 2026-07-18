import request from "@/utils/request";
import type {
  KbCrawlRequest,
  KbDownloadRequest,
  KbEmbedRequest,
  KbImportRequest,
  KbOverviewResponse,
  StatusResponse,
} from "./types";

export async function getKbOverview(params?: {
  law_type?: string;
  status?: string;
  query?: string;
  limit?: number;
  offset?: number;
}) {
  return request.get<KbOverviewResponse>(
    "/kb/overview",
    params as Record<string, string | number | boolean | undefined>,
  );
}

export async function triggerCrawl(data: KbCrawlRequest) {
  return request.post<StatusResponse>("/kb/crawl", data);
}

export async function triggerDownload(data: KbDownloadRequest) {
  return request.post<StatusResponse>("/kb/download", data);
}

export async function triggerImport(data: KbImportRequest) {
  return request.post<StatusResponse>("/kb/import", data);
}

export async function triggerEmbed(data: KbEmbedRequest) {
  return request.post<StatusResponse>("/kb/embed", data);
}

export async function deleteLaw(lawName: string) {
  return request.delete<StatusResponse>(`/kb/laws/${encodeURIComponent(lawName)}`);
}
