import { css, Global } from "@emotion/react";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Provider } from "react-redux";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import MainLayout from "./layouts/MainLayout";
import ChatPage from "./pages/ChatPage";
import CsvImportPage from "./pages/CsvImportPage";
import DashboardPage from "./pages/DashboardPage";
import DocumentUploadPage from "./pages/DocumentUploadPage";
import GraphPage from "./pages/GraphPage";
import LoginPage from "./pages/LoginPage";
import SpiderPage from "./pages/SpiderPage";
import { store } from "./store";

const globalStyles = css`
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  #root {
    width: 100%;
    max-width: 100%;
    margin: 0 auto;
  }

  ::-webkit-scrollbar {
    width: 6px;
    height: 6px;
  }

  ::-webkit-scrollbar-thumb {
    background: rgba(0, 0, 0, 0.2);
    border-radius: 3px;
  }

  ::-webkit-scrollbar-track {
    background: transparent;
  }
`;

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem("token");
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Root element not found");
createRoot(rootElement).render(
  <StrictMode>
    <Global styles={globalStyles} />
    <Provider store={store}>
      <ConfigProvider locale={zhCN}>
        <AntApp>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route
                element={
                  <ProtectedRoute>
                    <MainLayout />
                  </ProtectedRoute>
                }
              >
                <Route path="/" element={<DashboardPage />} />
                <Route path="/graph" element={<GraphPage />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/documents/upload" element={<DocumentUploadPage />} />
                <Route path="/documents/csv" element={<CsvImportPage />} />
                <Route path="/spider" element={<SpiderPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </AntApp>
      </ConfigProvider>
    </Provider>
  </StrictMode>,
);
