const BASE_URL = "/api";

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (response.status === 401) {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    window.location.href = "/login";
    throw new Error("未登录或登录已过期");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = (body as Record<string, unknown>).detail;
    throw new Error(typeof detail === "string" ? detail : `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

const request = {
  async get<T>(url: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
    const searchParams = new URLSearchParams();
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        if (value !== undefined) {
          searchParams.set(key, String(value));
        }
      }
    }
    const query = searchParams.toString();
    const fullUrl = `${BASE_URL}${url}${query ? `?${query}` : ""}`;
    const response = await fetch(fullUrl, {
      headers: { ...getAuthHeaders() },
    });
    return handleResponse<T>(response);
  },

  async post<T>(url: string, data?: unknown): Promise<T> {
    const response = await fetch(`${BASE_URL}${url}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
      },
      body: data ? JSON.stringify(data) : undefined,
    });
    return handleResponse<T>(response);
  },

  async put<T>(url: string, data?: unknown): Promise<T> {
    const response = await fetch(`${BASE_URL}${url}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
      },
      body: data ? JSON.stringify(data) : undefined,
    });
    return handleResponse<T>(response);
  },

  async patch<T>(url: string, data?: unknown): Promise<T> {
    const response = await fetch(`${BASE_URL}${url}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...getAuthHeaders(),
      },
      body: data ? JSON.stringify(data) : undefined,
    });
    return handleResponse<T>(response);
  },

  async delete<T>(url: string): Promise<T> {
    const response = await fetch(`${BASE_URL}${url}`, {
      method: "DELETE",
      headers: { ...getAuthHeaders() },
    });
    return handleResponse<T>(response);
  },

  async upload<T>(url: string, formData: FormData): Promise<T> {
    const response = await fetch(`${BASE_URL}${url}`, {
      method: "POST",
      headers: { ...getAuthHeaders() },
      body: formData,
    });
    return handleResponse<T>(response);
  },
};

export default request;
