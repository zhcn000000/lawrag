import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Provider } from "react-redux";
import { store } from "@/store";
import MainLayout from "@/layouts/MainLayout";
import ChatPage from "@/pages/ChatPage";
import DocumentUploadPage from "@/pages/DocumentUploadPage";
import LoginPage from "@/pages/LoginPage";

export default function App() {
  return (
    <Provider store={store}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<MainLayout />}>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/documents/upload" element={<DocumentUploadPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </Provider>
  );
}
