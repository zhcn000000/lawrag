import { GlobalOutlined, LockOutlined, UserOutlined } from "@ant-design/icons";
import { Button, Card, Form, Input, message, Space, Typography } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { register } from "@/api/auth";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { clearError, loginThunk } from "@/store/slices/authSlice";

const { Title, Text } = Typography;

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<"login" | "register">("login");
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  const { token, error } = useAppSelector((state) => state.auth);

  useEffect(() => {
    if (token) {
      navigate("/", { replace: true });
    }
  }, [token, navigate]);

  useEffect(() => {
    if (error) {
      message.error(error);
      dispatch(clearError());
    }
  }, [error, dispatch]);

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      if (mode === "register") {
        await register({ username: values.username, password: values.password });
        message.success("注册成功，已自动登录");
      }
      await dispatch(loginThunk({ username: values.username, password: values.password })).unwrap();
      if (mode === "login") {
        message.success("登录成功");
      }
      navigate("/", { replace: true });
    } catch (err) {
      if (mode === "register" && err instanceof Error) {
        message.error(err.message || "注册失败");
      }
      // login error handled in useEffect
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
      }}
    >
      <Card style={{ width: 400, boxShadow: "0 8px 24px rgba(0,0,0,0.15)" }}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <Space>
            <GlobalOutlined style={{ fontSize: 32, color: "#667eea" }} />
            <Title level={3} style={{ margin: 0 }}>
              LawRAG 法律智能问答
            </Title>
          </Space>
          <div style={{ marginTop: 8 }}>
            <Text type="secondary">{mode === "login" ? "请登录以继续" : "创建一个新账号"}</Text>
          </div>
        </div>

        <Form name={mode} onFinish={onFinish} size="large" autoComplete="off">
          <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" />
          </Form.Item>

          <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>

          {mode === "register" && (
            <Form.Item
              name="confirm"
              dependencies={["password"]}
              rules={[
                { required: true, message: "请再次输入密码" },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue("password") === value) {
                      return Promise.resolve();
                    }
                    return Promise.reject(new Error("两次输入的密码不一致"));
                  },
                }),
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="确认密码" />
            </Form.Item>
          )}

          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading} block>
              {mode === "login" ? "登录" : "注册"}
            </Button>
          </Form.Item>
        </Form>

        <div style={{ textAlign: "center" }}>
          <Button type="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
            {mode === "login" ? "没有账号？立即注册" : "已有账号？返回登录"}
          </Button>
        </div>
      </Card>
    </div>
  );
}
