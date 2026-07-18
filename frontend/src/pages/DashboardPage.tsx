import {
  BarChartOutlined,
  CloudOutlined,
  DashboardOutlined,
  FileTextOutlined,
  MessageOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { Card, Col, Row, Statistic, Typography } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getSessionList } from "@/api/session";
import type { LawListResponse } from "@/api/types";
import { useAppSelector } from "@/store/hooks";
import request from "@/utils/request";

const { Title } = Typography;

export default function DashboardPage() {
  const navigate = useNavigate();
  const user = useAppSelector((state) => state.auth.user);
  const isAdmin = user?.is_admin === true;
  const [sessionCount, setSessionCount] = useState(0);
  const [documentCount, setDocumentCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const [sessionData, lawData] = await Promise.all([
          getSessionList(),
          request.get<LawListResponse>("/rag/pageindex/laws"),
        ]);
        setSessionCount(sessionData.sessions?.length ?? 0);
        setDocumentCount(lawData.laws?.length ?? 0);
      } catch {
        // ignore errors, keep defaults
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, []);

  return (
    <div>
      <Title level={3}>
        <DashboardOutlined /> 仪表盘
      </Title>
      <p>欢迎回来，{user?.username ?? "用户"}！</p>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="会话总数" value={sessionCount} prefix={<MessageOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card loading={loading}>
            <Statistic title="已导入法律" value={documentCount} prefix={<FileTextOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic title="知识库状态" value="运行中" prefix={<BarChartOutlined />} />
          </Card>
        </Col>
      </Row>

      <Title level={4}>快捷操作</Title>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={8}>
          <Card hoverable onClick={() => navigate("/chat")} style={{ cursor: "pointer" }}>
            <Card.Meta
              avatar={<RobotOutlined style={{ fontSize: 32, color: "#1677ff" }} />}
              title="AI 法律问答"
              description="开始与法律AI助手对话，解答法律相关问题"
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card hoverable onClick={() => navigate("/chat")} style={{ cursor: "pointer" }}>
            <Card.Meta
              avatar={<CloudOutlined style={{ fontSize: 32, color: "#52c41a" }} />}
              title="法律知识库"
              description="浏览和管理已导入的法律条文"
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
