export interface StatusResponse {
  success: boolean;
  status?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface UserCredentialsRequest {
  username: string;
  password: string;
}

export interface UserResponse {
  id: string;
  username: string;
}

export interface SearchRequest {
  query: string;
  regex?: string;
  vecweight?: number;
  k?: number;
}

export interface SearchItem {
  content: string;
  source_name: string | null;
  page_index: string | null;
  score: number | null;
}

export interface SearchResponse extends StatusResponse {
  results: SearchItem[];
}

export interface ChatRequest {
  text: string;
  files?: unknown[];
  model?: string;
  thinking?: boolean;
  select_toolset?: string[];
}

export interface ChatTitleRequest {
  text: string;
}

export interface ChatTitleResponse extends StatusResponse {
  title?: string;
}

export interface RenameRequest {
  name: string;
}

export interface SessionInfo {
  session_id: string;
  name: string;
}

export interface SessionCreateResponse extends StatusResponse {
  session_id?: string;
  name?: string;
}

export interface SessionListResponse extends StatusResponse {
  sessions: SessionInfo[];
}

export interface HistoryResponse extends StatusResponse {
  messages?: unknown[];
}

export interface TranscriptionResponse extends StatusResponse {
  text?: string;
}

export interface LawListResponse extends StatusResponse {
  laws?: Record<string, unknown>[];
}

// ── Knowledge Base Management ──

export interface KbLawOverviewItem {
  law_id: string;
  law_name: string;
  law_type: string;
  status: string;
  publish_date: string | null;
  has_raw: boolean;
  has_structured: boolean;
  in_nodes: boolean;
  article_count: number;
  chunk_count: number;
}

export interface KbOverviewResponse extends StatusResponse {
  laws: KbLawOverviewItem[];
  total: number;
}

export interface KbCrawlRequest {
  category: string;
}

export interface KbDownloadRequest {
  law_ids?: string[];
}

export interface KbImportRequest {
  law_names: string[];
}

export interface KbEmbedRequest {
  law_names: string[];
  chunk_size?: number;
  chunk_overlap?: number;
  batch_size?: number;
}
