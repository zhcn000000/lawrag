import { Provider } from "react-redux";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import MainLayout from "@/layouts/MainLayout";
import ChatPage from "@/pages/ChatPage";
import LoginPage from "@/pages/LoginPage";
import { store } from "@/store";

export default function App() {
  return (
    <Provider store={store}>
      <BrowserRouter basename="/webui">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<MainLayout />}>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </Provider>
  );
}
