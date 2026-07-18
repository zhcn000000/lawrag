import request from "@/utils/request";
import type { SearchRequest, SearchResponse } from "./types";

export async function ragSearch(data: SearchRequest) {
  return request.post<SearchResponse>("/rag/search", data);
}
