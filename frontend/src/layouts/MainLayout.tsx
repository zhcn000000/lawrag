import {
  DashboardOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  RobotOutlined,
  UserOutlined,
} from "@ant-design/icons";
import type { MenuProps } from "antd";
import { Avatar, Button, Dropdown, Layout, Menu, Space, Typography, theme } from "antd";
import { useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { logout } from "@/store/slices/authSlice";

const { Header, Sider, Content } = Layout;
const { Title } = Typography;

const menuItems: MenuProps["items"] = [
  {
    key: "/",
    icon: <DashboardOutlined />,
    label: "仪表盘",
  },
  {
    key: "/chat",
    icon: <RobotOutlined />,
    label: "AI 法律问答",
  },
];

export default function MainLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const dispatch = useAppDispatch();
  const user = useAppSelector((state) => state.auth.user);
  const { token: themeToken } = theme.useToken();

  const selectedKeys = [location.pathname];

  const handleMenuClick: MenuProps["onClick"] = ({ key }) => {
    navigate(key);
  };

  const handleLogout = () => {
    dispatch(logout());
    navigate("/login");
  };

  const userMenuItems: MenuProps["items"] = [
    {
      key: "logout",
      label: "退出登录",
      icon: <LogoutOutlined />,
      danger: true,
      onClick: handleLogout,
    },
  ];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        style={{
          overflow: "auto",
          height: "100vh",
          position: "fixed",
          left: 0,
          top: 0,
          bottom: 0,
          zIndex: 100,
        }}
      >
        <div
          style={{
            height: 64,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 16,
          }}
        >
          <Space>
            <Avatar size={32} style={{ backgroundColor: themeToken.colorPrimary }}>
              LR
            </Avatar>
            {!collapsed && (
              <Title level={5} style={{ color: "#fff", margin: 0, whiteSpace: "nowrap" }}>
                LawRAG
              </Title>
            )}
          </Space>
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={selectedKeys} items={menuItems} onClick={handleMenuClick} />
      </Sider>

      <Layout
        style={{
          marginLeft: collapsed ? 80 : 220,
          transition: "margin-left 0.2s",
        }}
      >
        <Header
          style={{
            padding: "0 24px",
            background: themeToken.colorBgContainer,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            boxShadow: "0 1px 4px rgba(0,0,0,0.1)",
            position: "sticky",
            top: 0,
            zIndex: 99,
          }}
        >
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
            style={{ fontSize: 16 }}
          />
          <Space>
            {user ? (
              <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
                <Space style={{ cursor: "pointer" }}>
                  <Avatar style={{ backgroundColor: themeToken.colorPrimary }}>{user.username[0].toUpperCase()}</Avatar>
                  <span>{user.username}</span>
                </Space>
              </Dropdown>
            ) : (
              <Avatar icon={<UserOutlined />} />
            )}
          </Space>
        </Header>

        <Content
          style={{
            padding: 24,
            minHeight: "calc(100vh - 64px)",
            background: themeToken.colorBgLayout,
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
