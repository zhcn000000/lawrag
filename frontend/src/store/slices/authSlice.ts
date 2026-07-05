import { createAsyncThunk, createSlice, type PayloadAction } from "@reduxjs/toolkit";
import { getCurrentUser, login, refreshToken } from "@/api/auth";
import type { UserResponse } from "@/api/types";

interface AuthState {
  token: string | null;
  user: UserResponse | null;
  loading: boolean;
  error: string | null;
}

const initialState: AuthState = {
  token: localStorage.getItem("token"),
  user: (() => {
    try {
      const stored = localStorage.getItem("user");
      return stored ? (JSON.parse(stored) as UserResponse) : null;
    } catch {
      return null;
    }
  })(),
  loading: false,
  error: null,
};

export const loginThunk = createAsyncThunk(
  "auth/login",
  async (credentials: { username: string; password: string }, { rejectWithValue }) => {
    try {
      const formData = new FormData();
      formData.append("username", credentials.username);
      formData.append("password", credentials.password);
      const res = await login(formData);
      localStorage.setItem("token", res.access_token);
      const user = await getCurrentUser();
      localStorage.setItem("user", JSON.stringify(user));
      return { token: res.access_token, user };
    } catch (err) {
      return rejectWithValue(err instanceof Error ? err.message : "登录失败");
    }
  },
);

export const refreshTokenThunk = createAsyncThunk("auth/refresh", async (_, { rejectWithValue }) => {
  try {
    const res = await refreshToken();
    localStorage.setItem("token", res.access_token);
    const user = await getCurrentUser();
    localStorage.setItem("user", JSON.stringify(user));
    return { token: res.access_token, user };
  } catch (err) {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    return rejectWithValue(err instanceof Error ? err.message : "刷新失败");
  }
});

export const fetchUserThunk = createAsyncThunk("auth/fetchUser", async (_, { rejectWithValue }) => {
  try {
    const user = await getCurrentUser();
    localStorage.setItem("user", JSON.stringify(user));
    return user;
  } catch (err) {
    return rejectWithValue(err instanceof Error ? err.message : "获取用户信息失败");
  }
});

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    logout(state) {
      state.token = null;
      state.user = null;
      state.error = null;
      localStorage.removeItem("token");
      localStorage.removeItem("user");
    },
    clearError(state) {
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loginThunk.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(loginThunk.fulfilled, (state, action: PayloadAction<{ token: string; user: UserResponse }>) => {
        state.loading = false;
        state.token = action.payload.token;
        state.user = action.payload.user;
        state.error = null;
      })
      .addCase(loginThunk.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload as string;
      })
      .addCase(refreshTokenThunk.fulfilled, (state, action) => {
        state.token = action.payload.token;
        state.user = action.payload.user;
      })
      .addCase(refreshTokenThunk.rejected, (state) => {
        state.token = null;
        state.user = null;
      })
      .addCase(fetchUserThunk.fulfilled, (state, action) => {
        state.user = action.payload;
      });
  },
});

export const { logout, clearError } = authSlice.actions;
export default authSlice.reducer;
