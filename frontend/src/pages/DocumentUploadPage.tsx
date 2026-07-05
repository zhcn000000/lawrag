import { CloudUploadOutlined, FileTextOutlined, InboxOutlined } from "@ant-design/icons";
import type { UploadProps } from "antd";
import { Alert, Card, message, Progress, Space, Table, Tag, Typography, Upload } from "antd";
import { useState } from "react";
import { uploadDocument } from "@/api/documents";

const { Title, Text } = Typography;
const { Dragger } = Upload;

interface UploadRecord {
  key: string;
  name: string;
  size: string;
  status: "uploading" | "success" | "error";
  documentCount?: number;
  fileId?: string;
  error?: string;
}

export default function DocumentUploadPage() {
  const [records, setRecords] = useState<UploadRecord[]>([]);
  const [uploading, setUploading] = useState(false);

  const handleUpload: UploadProps["customRequest"] = async (options) => {
    const { file, onSuccess, onError } = options;
    if (!(file instanceof File)) {
      onError?.(new Error("文件格式错误"));
      return;
    }

    const record: UploadRecord = {
      key: file.name + Date.now(),
      name: file.name,
      size: formatFileSize(file.size),
      status: "uploading",
    };

    setRecords((prev) => [record, ...prev]);
    setUploading(true);

    try {
      const response = await uploadDocument(file);
      if (response.success) {
        setRecords((prev) =>
          prev.map((r) =>
            r.key === record.key
              ? {
                  ...r,
                  status: "success",
                  documentCount: response.doc_ids?.length ?? 0,
                  fileId: response.doc_ids?.[0],
                }
              : r,
          ),
        );
        onSuccess?.(response, file);
        message.success(`"${file.name}" 上传成功，已创建 ${response.doc_ids?.length ?? 0} 个文档分块`);
      } else {
        throw new Error(response.status || "上传失败");
      }
    } catch (error) {
      const errMsg = error instanceof Error ? error.message : "上传失败";
      setRecords((prev) => prev.map((r) => (r.key === record.key ? { ...r, status: "error", error: errMsg } : r)));
      onError?.(new Error(errMsg));
      message.error(errMsg);
    } finally {
      setUploading(false);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${Number.parseFloat((bytes / k ** i).toFixed(1))} ${sizes[i]}`;
  };

  const columns = [
    {
      title: "文件名",
      dataIndex: "name",
      key: "name",
      render: (text: string) => (
        <Space>
          <FileTextOutlined />
          <Text>{text}</Text>
        </Space>
      ),
    },
    {
      title: "大小",
      dataIndex: "size",
      key: "size",
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (status: string) => {
        if (status === "uploading") return <Tag color="processing">上传中</Tag>;
        if (status === "success") return <Tag color="success">上传成功</Tag>;
        if (status === "error") return <Tag color="error">上传失败</Tag>;
        return <Tag>{status}</Tag>;
      },
    },
    {
      title: "文档分块",
      dataIndex: "documentCount",
      key: "documentCount",
      render: (count: number | undefined) => (count !== undefined ? <Text>{count}</Text> : <Text type="secondary">-</Text>),
    },
  ];

  const totalUploaded = records.filter((r) => r.status === "success").length;
  const totalError = records.filter((r) => r.status === "error").length;
  const uploadProgress = records.length > 0 ? Math.round((totalUploaded / records.length) * 100) : 0;

  return (
    <div>
      <Title level={4}>
        <Space>
          <CloudUploadOutlined />
          文档管理
        </Space>
      </Title>

      <Card style={{ marginBottom: 24 }}>
        <Dragger
          multiple
          customRequest={handleUpload}
          accept=".md,.txt,.pdf,.docx,.csv,.json"
          showUploadList={false}
          disabled={uploading}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽法律文档到此处上传</p>
          <p className="ant-upload-hint">支持 Markdown (.md), 纯文本 (.txt), PDF (.pdf), Word (.docx) 格式</p>
        </Dragger>
      </Card>

      {uploading && <Progress percent={uploadProgress} status="active" style={{ marginBottom: 16 }} />}

      {totalError > 0 && (
        <Alert
          type="warning"
          message={`${totalError} 个文件上传失败`}
          showIcon
          closable
          style={{ marginBottom: 16 }}
        />
      )}

      <Card title="上传记录">
        <Table columns={columns} dataSource={records} pagination={{ pageSize: 10 }} size="small" locale={{ emptyText: "暂无上传记录" }} />
      </Card>
    </div>
  );
}
