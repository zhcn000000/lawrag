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
	offset?: number;
	k?: number;
}

export interface SearchResponse extends StatusResponse {
	results: Record<string, unknown>[];
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
