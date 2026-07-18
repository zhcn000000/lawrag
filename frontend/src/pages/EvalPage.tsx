import {
  CheckCircleFilled,
  CloseCircleFilled,
  DeleteOutlined,
  DownloadOutlined,
  ExperimentOutlined,
  LoadingOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { App, Button, Card, Empty, Input, Popconfirm, Space, Switch, Table, Tag, Typography } from "antd";
import type { ColumnType } from "antd/es/table";
import { useCallback, useRef, useState } from "react";
import { runEval } from "@/api/eval";
import type { EvalCase, EvalResultItem } from "@/api/types";
import { SuperMarkdown } from "@/components/SuperMarkdown";

const { Title, Text, Paragraph } = Typography;

type EvalCaseRow = EvalCase & { key: string };

let nextId = 0;
function makeKey(): string {
  nextId += 1;
  return `case-${nextId}`;
}

export default function EvalPage() {
  const { message } = App.useApp();
  const [dataSource, setDataSource] = useState<EvalCaseRow[]>([
    { key: makeKey(), name: "", question: "", expected_answer: "" },
    { key: makeKey(), name: "", question: "", expected_answer: "" },
  ]);
  const [offline, setOffline] = useState(false);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<EvalResultItem[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const isEmpty = dataSource.length === 0;

  const updateCell = useCallback((key: string, field: keyof EvalCase, value: string) => {
    setDataSource((prev) => prev.map((row) => (row.key === key ? { ...row, [field]: value } : row)));
  }, []);

  const addRow = useCallback(() => {
    setDataSource((prev) => [...prev, { key: makeKey(), name: "", question: "", expected_answer: "" }]);
  }, []);

  const deleteRow = useCallback((key: string) => {
    setDataSource((prev) => prev.filter((row) => row.key !== key));
  }, []);

  const getCases = useCallback((): EvalCase[] | null => {
    const cases = dataSource
      .filter((row) => row.name.trim() || row.question.trim() || row.expected_answer.trim())
      .map(({ key: _key, ...rest }) => rest);
    if (cases.length === 0) {
      message.warning("请至少填写一个用例");
      return null;
    }
    for (const [i, c] of cases.entries()) {
      if (!c.name.trim()) {
        message.warning(`第 ${i + 1} 行缺少名称`);
        return null;
      }
      if (!c.question.trim()) {
        message.warning(`第 ${i + 1} 行缺少问题`);
        return null;
      }
      if (!c.expected_answer.trim()) {
        message.warning(`第 ${i + 1} 行缺少预期答案`);
        return null;
      }
    }
    return cases;
  }, [dataSource, message]);

  const handleStart = useCallback(async () => {
    const cases = getCases();
    if (!cases) return;

    setRunning(true);
    setResults([]);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const reports = await runEval({ cases, offline }, controller.signal);
      setResults(reports);
      const passed = reports.filter((r) => r.success).length;
      message.success(`评估完成: ${passed}/${reports.length} 通过`);
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        message.info("评估已停止");
      } else {
        message.error(err instanceof Error ? err.message : "评估运行失败");
      }
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }, [getCases, offline, message]);

  const handleStop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleImport = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const parsed = JSON.parse(reader.result as string);
          if (!Array.isArray(parsed)) {
            message.error("JSON 必须是数组格式");
            return;
          }
          const rows: EvalCaseRow[] = parsed.map((item: Record<string, unknown>) => ({
            key: makeKey(),
            name: String(item.name ?? ""),
            question: String(item.question ?? ""),
            expected_answer: String(item.expected_answer ?? ""),
          }));
          if (rows.length === 0) {
            rows.push({ key: makeKey(), name: "", question: "", expected_answer: "" });
          }
          setDataSource(rows);
          message.success(`已导入 ${rows.length} 条用例`);
        } catch {
          message.error("JSON 格式错误");
        }
      };
      reader.readAsText(file);
    };
    input.click();
  }, [message]);

  const handleExport = useCallback(() => {
    const cases = getCases();
    if (!cases || cases.length === 0) {
      message.warning("没有可导出的用例");
      return;
    }
    const blob = new Blob([JSON.stringify(cases, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "eval_cases.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [getCases, message]);

  const handleExportResult = useCallback(() => {
    if (results.length === 0) {
      message.warning("没有可导出的评估结果");
      return;
    }
    const blob = new Blob([JSON.stringify(results, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "eval_results.json";
    a.click();
    URL.revokeObjectURL(url);
  }, [results, message]);

  const passed = results.filter((r) => r.success).length;
  const total = results.length;
  const percent = total > 0 ? Math.round((passed / total) * 100) : 0;

  const caseColumns: ColumnType<EvalCaseRow>[] = [
    {
      title: "序号",
      width: 64,
      render: (_: unknown, __: unknown, index: number) => index + 1,
    },
    {
      title: "名称",
      dataIndex: "name",
      width: 180,
      render: (v: string, record: EvalCaseRow) => (
        <Input
          value={v}
          placeholder="用例名称"
          variant="borderless"
          disabled={running}
          onChange={(e) => updateCell(record.key, "name", e.target.value)}
        />
      ),
    },
    {
      title: "问题",
      dataIndex: "question",
      render: (v: string, record: EvalCaseRow) => (
        <Input
          value={v}
          placeholder="法律提问"
          variant="borderless"
          disabled={running}
          onChange={(e) => updateCell(record.key, "question", e.target.value)}
        />
      ),
    },
    {
      title: "预期答案",
      dataIndex: "expected_answer",
      width: 300,
      render: (v: string, record: EvalCaseRow) => (
        <Input
          value={v}
          placeholder="预期参考答案"
          variant="borderless"
          disabled={running}
          onChange={(e) => updateCell(record.key, "expected_answer", e.target.value)}
        />
      ),
    },
    {
      title: "操作",
      width: 64,
      render: (_: unknown, record: EvalCaseRow) => (
        <Popconfirm title="确定删除此行？" onConfirm={() => deleteRow(record.key)}>
          <Button type="text" danger size="small" icon={<DeleteOutlined />} disabled={running} />
        </Popconfirm>
      ),
    },
  ];

  const resultColumns: ColumnType<EvalResultItem>[] = [
    {
      title: "状态",
      width: 64,
      render: (_, record) =>
        record.success ? (
          <CheckCircleFilled style={{ color: "#52c41a", fontSize: 16 }} />
        ) : (
          <CloseCircleFilled style={{ color: "#ff4d4f", fontSize: 16 }} />
        ),
    },
    { title: "名称", dataIndex: "name", width: 150, ellipsis: true },
    { title: "问题", dataIndex: "question", ellipsis: true },
    {
      title: "通过",
      width: 64,
      render: (_, record) => <Tag color={record.success ? "green" : "red"}>{record.success ? "通过" : "未通过"}</Tag>,
    },
  ];

  const expandedRowRender = (item: EvalResultItem) => {
    const isReport = item.type === "report";
    return (
      <div style={{ padding: "0 24px 12px" }}>
        <Paragraph>
          <Text strong>问题：</Text>
          {item.question}
        </Paragraph>
        <Paragraph>
          <Text strong>预期答案：</Text>
          <SuperMarkdown>{item.expected_answer}</SuperMarkdown>
        </Paragraph>
        {isReport ? (
          <>
            <Paragraph>
              <Text strong>模型输出：</Text>
              <SuperMarkdown>{item.model_output || ""}</SuperMarkdown>
            </Paragraph>
            <Paragraph>
              <Text strong>裁判意见：</Text>
              <SuperMarkdown>{item.evaluation_note || ""}</SuperMarkdown>
            </Paragraph>
          </>
        ) : (
          <Paragraph type="danger">
            <Text strong>错误信息：</Text>
            {item.error_message}
          </Paragraph>
        )}
      </div>
    );
  };

  return (
    <div>
      <Title level={3}>
        <ExperimentOutlined /> 模型评估
      </Title>
      <Paragraph type="secondary">
        在下方表格中填写评测用例，运行 Agent 并由 LLM 裁判评分，评估完成后一次性展示全部结果。结果不写入文件。
      </Paragraph>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size="small">
          <Space wrap>
            <Button icon={<UploadOutlined />} onClick={handleImport} disabled={running}>
              导入 JSON
            </Button>
            <Button icon={<DownloadOutlined />} onClick={handleExport} disabled={running || isEmpty}>
              导出 JSON
            </Button>
            <Space>
              <Text>离线模式</Text>
              <Switch checked={offline} onChange={setOffline} disabled={running} size="small" />
            </Space>
          </Space>
          <Table
            dataSource={dataSource}
            columns={caseColumns}
            pagination={false}
            size="small"
            bordered
            scroll={{ y: 360 }}
            footer={() => (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Button type="dashed" icon={<PlusOutlined />} onClick={addRow} disabled={running}>
                  添加用例
                </Button>
                <Space>
                  {running ? (
                    <Button type="primary" danger icon={<PauseCircleOutlined />} onClick={handleStop}>
                      停止评估
                    </Button>
                  ) : (
                    <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleStart}>
                      开始评估
                    </Button>
                  )}
                </Space>
              </div>
            )}
          />
        </Space>
      </Card>

      {running && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Text type="secondary">
            <LoadingOutlined /> 评估运行中，完成后将一次性展示全部结果...
          </Text>
        </Card>
      )}

      {total > 0 && (
        <Card
          title={
            <Space>
              <span>评估结果 ({total})</span>
              <Tag color={percent >= 80 ? "green" : percent >= 50 ? "orange" : "red"}>通过率 {percent}%</Tag>
            </Space>
          }
          extra={
            <Button size="small" icon={<DownloadOutlined />} onClick={handleExportResult}>
              导出结果
            </Button>
          }
        >
          <Table
            dataSource={results.map((r, i) => ({ ...r, key: `${r.name}-${i}` }) as EvalResultItem & { key: string })}
            columns={resultColumns}
            expandable={{ expandedRowRender, rowExpandable: () => true }}
            size="small"
            pagination={false}
            scroll={{ y: 480 }}
          />
        </Card>
      )}

      {!running && total === 0 && <Empty description="填写用例后点击“开始评估”" />}
    </div>
  );
}
