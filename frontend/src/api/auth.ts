import request from "@/utils/request";
import type { TokenResponse, UserCredentialsRequest, UserResponse } from "./types";

export const login = (data: FormData): Promise<TokenResponse> => {
  return fetch("/api/login", {
    method: "POST",
    body: data,
  }).then((res) => {
    if (!res.ok) throw new Error("登录失败，请检查用户名和密码");
    return res.json() as Promise<TokenResponse>;
  });
};

export const register = (data: UserCredentialsRequest): Promise<{ success: boolean }> => {
  return request.post("/register", data);
};

export const refreshToken = (): Promise<TokenResponse> => {
  return request.post("/refresh");
};

export const getCurrentUser = (): Promise<UserResponse> => {
  return request.get("/me");
};
