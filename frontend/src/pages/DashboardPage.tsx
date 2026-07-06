import {
  BarChartOutlined,
  CloudUploadOutlined,
  DashboardOutlined,
  FileTextOutlined,
  MessageOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { Card, Col, Row, Statistic, Typography } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getSessionList } from "@/api/session";
import type { SourceListResponse } from "@/api/types";
import { useAppSelector } from "@/store/hooks";
import request from "@/utils/request";

const { Title } = Typography;

export default function DashboardPage() {
  const navigate = useNavigate();
  const user = useAppSelector((state) => state.auth.user);
  const [sessionCount, setSessionCount] = useState(0);
  const [documentCount, setDocumentCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const [sessionData, sourceData] = await Promise.all([
          getSessionList(),
          request.get<SourceListResponse>("/rag/sources"),
        ]);
        setSessionCount(sessionData.sessions?.length ?? 0);
        setDocumentCount(sourceData.sources?.length ?? 0);
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
            <Statistic title="文档来源" value={documentCount} prefix={<FileTextOutlined />} />
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
          <Card hoverable onClick={() => navigate("/documents/upload")} style={{ cursor: "pointer" }}>
            <Card.Meta
              avatar={<CloudUploadOutlined style={{ fontSize: 32, color: "#52c41a" }} />}
              title="文档管理"
              description="上传和管理法律文档，构建知识库"
            />
          </Card>
        </Col>
      </Row>
    </div>
  );
}
