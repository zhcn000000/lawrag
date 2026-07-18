import {
  CloudDownloadOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ImportOutlined,
  ReloadOutlined,
  RobotOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { App, Button, Cascader, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useRef, useState } from "react";
import { deleteLaw, getKbOverview, triggerCrawl, triggerDownload, triggerEmbed, triggerImport } from "@/api/kb";
import type { KbLawOverviewItem } from "@/api/types";

const { Title } = Typography;

const LAW_TYPES = ["宪法", "法律", "行政法规", "监察法规", "司法解释", "地方性法规", "未知"];
const STATUS_LIST = ["有效", "尚未生效", "已修改", "已废止", "未知"];

const CRAWL_CATEGORIES = [
  { value: "xf", label: "宪法" },
  { value: "flfg", label: "法律" },
  { value: "xzfg", label: "行政法规" },
  { value: "jcfg", label: "监察法规" },
  { value: "sfjs", label: "司法解释" },
  { value: "dfxfg", label: "地方性法规" },
  { value: "all", label: "全部 (不含地方性法规)" },
];

const STAGE_FILTERS = [
  { value: "not_downloaded", label: "未下载" },
  { value: "has_raw", label: "已下载" },
  { value: "has_structured", label: "已解析" },
  { value: "in_nodes", label: "已导入节点" },
  { value: "has_chunks", label: "已嵌入" },
  { value: "not_imported", label: "未导入" },
  { value: "not_embedded", label: "未嵌入" },
];

const TAG_COLORS: Record<string, string> = {
  有效: "green",
  尚未生效: "blue",
  已修改: "orange",
  已废止: "red",
  未知: "default",
};

export default function KnowledgeBasePage() {
  const { message, modal } = App.useApp();
  const [data, setData] = useState<KbLawOverviewItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [lawTypeFilter, setLawTypeFilter] = useState<string>("法律");
  const [statusFilter, setStatusFilter] = useState<string>("有效");
  const [stageFilter, setStageFilter] = useState<string[][]>([]);
  const [query, setQuery] = useState("");
  const queryRef = useRef("");
  const [crawlOpen, setCrawlOpen] = useState(false);
  const crawlCategoryRef = useRef("all");

  const fetchData = useCallback(
    async (searchQ?: string) => {
      const queryVal = searchQ ?? queryRef.current;
      setLoading(true);
      try {
        const res = await getKbOverview({
          law_type: lawTypeFilter,
          status: statusFilter,
          query: queryVal || undefined,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        });
        if (res.success) {
          setData(res.laws);
          setTotal(res.total);
        } else {
          message.error(res.status);
        }
      } catch {
        message.error("获取知识库概览失败");
      } finally {
        setLoading(false);
      }
    },
    [lawTypeFilter, statusFilter, page, pageSize, message],
  );

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const handleSearch = (value: string) => {
    setQuery(value);
    queryRef.current = value;
    setSelectedRowKeys([]);
    setPage(1);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchData(value), 300);
  };

  const getSelected = () => data.filter((d) => selectedRowKeys.includes(d.law_name));

  const handleBatchImport = async () => {
    const selected = getSelected();
    const ids = selected.filter((s) => s.has_structured && !s.in_nodes).map((s) => s.law_id);
    if (ids.length === 0) {
      message.warning("所选法律无可导入项 (需已解析且未导入)");
      return;
    }
    try {
      const res = await triggerImport({ law_ids: ids });
      message.success(res.status);
      await fetchData();
    } catch {
      message.error("导入失败");
    }
  };

  const handleBatchEmbed = async () => {
    const selected = getSelected();
    const ids = selected.filter((s) => s.in_nodes && s.chunk_count === 0).map((s) => s.law_id);
    if (ids.length === 0) {
      message.warning("所选法律无可嵌入项 (需已导入且未嵌入)");
      return;
    }
    try {
      const res = await triggerEmbed({ law_ids: ids });
      message.success(res.status);
      setTimeout(() => fetchData(), 2000);
    } catch {
      message.error("嵌入失败");
    }
  };

  const handleBatchImportAndEmbed = async () => {
    const selected = getSelected();
    const notDownloaded = selected.filter((s) => !s.has_raw).map((s) => s.law_id);
    const toImport = selected.filter((s) => s.has_structured && !s.in_nodes).map((s) => s.law_id);
    const toEmbed = selected.filter((s) => s.in_nodes && s.chunk_count === 0).map((s) => s.law_id);
    const allEmbed = [...toImport, ...toEmbed];
    if (toImport.length === 0 && toEmbed.length === 0) {
      message.warning("所选法律无可处理项");
      return;
    }
    try {
      if (notDownloaded.length > 0) {
        const dlRes = await triggerDownload({ law_ids: notDownloaded });
        message.success(dlRes.status);
        await new Promise((resolve) => setTimeout(resolve, 5000));
        await fetchData();
      }
      if (toImport.length > 0) {
        const importRes = await triggerImport({ law_ids: toImport });
        message.success(importRes.status);
      }
      if (allEmbed.length > 0) {
        const embedRes = await triggerEmbed({ law_ids: allEmbed });
        message.success(embedRes.status);
      }
      setTimeout(() => fetchData(), 2000);
    } catch {
      message.error("一键处理失败");
    }
  };

  const handleBatchDelete = () => {
    const selected = getSelected();
    const names = selected.filter((s) => s.in_nodes).map((s) => s.law_name);
    if (names.length === 0) {
      message.warning("所选法律无已导入节点可删除");
      return;
    }
    modal.confirm({
      title: "确认删除",
      content: `将删除 ${names.length} 部法律的法条节点及关联文档块 (保留爬虫索引记录)。\n\n法律: ${names.slice(0, 5).join("、")}${names.length > 5 ? ` 等共 ${names.length} 部` : ""}`,
      okText: "确认删除",
      okType: "danger",
      onOk: async () => {
        for (const name of names) {
          try {
            await deleteLaw(name);
          } catch {
            message.error(`删除 ${name} 失败`);
          }
        }
        message.success("删除完成");
        setSelectedRowKeys([]);
        await fetchData();
      },
    });
  };

  const handleSingleDelete = (lawName: string) => {
    modal.confirm({
      title: "确认删除",
      content: `将删除法律 "${lawName}" 的法条节点及关联文档块 (保留爬虫索引记录)。`,
      okText: "确认删除",
      okType: "danger",
      onOk: async () => {
        try {
          const res = await deleteLaw(lawName);
          message.success(res.status);
          await fetchData();
        } catch {
          message.error("删除失败");
        }
      },
    });
  };

  const handleCrawlConfirm = async () => {
    try {
      const res = await triggerCrawl({ category: crawlCategoryRef.current });
      message.success(res.status);
      setCrawlOpen(false);
    } catch {
      message.error("启动爬取失败");
    }
  };

  const handleDownload = async () => {
    const selected = getSelected();
    const lawIds = selected.filter((s) => !s.has_raw).map((s) => s.law_id);
    try {
      const res = await triggerDownload(lawIds.length > 0 ? { law_ids: lawIds } : {});
      message.success(res.status);
      setTimeout(() => fetchData(), 3000);
    } catch {
      message.error("启动下载失败");
    }
  };

  const columns: ColumnsType<KbLawOverviewItem> = [
    {
      title: "法律名称",
      dataIndex: "law_name",
      key: "law_name",
      width: 280,
      ellipsis: true,
      sorter: (a, b) => a.law_name.localeCompare(b.law_name, "zh"),
    },
    {
      title: "类型",
      dataIndex: "law_type",
      key: "law_type",
      width: 100,
      filters: LAW_TYPES.map((t) => ({ text: t, value: t })),
      onFilter: (value, record) => record.law_type === value,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (s: string) => <Tag color={TAG_COLORS[s] || "default"}>{s}</Tag>,
      filters: STATUS_LIST.map((s) => ({ text: s, value: s })),
      onFilter: (value, record) => record.status === value,
    },
    {
      title: "发布日期",
      dataIndex: "publish_date",
      key: "publish_date",
      width: 110,
      render: (d: string | null) => d || "-",
    },
    {
      title: "已下载",
      dataIndex: "has_raw",
      key: "has_raw",
      width: 80,
      align: "center",
      render: (v: boolean) => <Tag color={v ? "green" : "default"}>{v ? "是" : "否"}</Tag>,
    },
    {
      title: "已解析",
      dataIndex: "has_structured",
      key: "has_structured",
      width: 80,
      align: "center",
      render: (v: boolean) => <Tag color={v ? "green" : "default"}>{v ? "是" : "否"}</Tag>,
    },
    {
      title: "已导入",
      dataIndex: "in_nodes",
      key: "in_nodes",
      width: 80,
      align: "center",
      render: (v: boolean) => <Tag color={v ? "green" : "default"}>{v ? "是" : "否"}</Tag>,
    },
    {
      title: "法条数",
      dataIndex: "article_count",
      key: "article_count",
      width: 80,
      align: "right",
      sorter: (a, b) => a.article_count - b.article_count,
    },
    {
      title: "块数",
      dataIndex: "chunk_count",
      key: "chunk_count",
      width: 80,
      align: "right",
      sorter: (a, b) => a.chunk_count - b.chunk_count,
    },
    {
      title: "操作",
      key: "actions",
      width: 120,
      render: (_, record) => (
        <Space size="small">
          {!record.has_raw ? (
            <Tooltip title="下载原始文件">
              <Button
                type="link"
                size="small"
                icon={<CloudDownloadOutlined />}
                onClick={() => triggerDownload({ law_ids: [record.law_id] }).then(() => fetchData())}
              />
            </Tooltip>
          ) : null}
          {record.has_structured && (!record.in_nodes || record.chunk_count === 0) ? (
            <Tooltip title="导入并嵌入">
              <Button
                type="link"
                size="small"
                icon={<ThunderboltOutlined />}
                onClick={async () => {
                  try {
                    if (!record.in_nodes) {
                      await triggerImport({ law_ids: [record.law_id] });
                    }
                    await triggerEmbed({ law_ids: [record.law_id] });
                    await fetchData();
                  } catch {
                    // errors surfaced by individual API calls
                  }
                }}
              />
            </Tooltip>
          ) : null}
          {record.in_nodes ? (
            <Tooltip title="删除节点和文档">
              <Button
                type="link"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => handleSingleDelete(record.law_name)}
              />
            </Tooltip>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>
        <DatabaseOutlined /> 法律知识库管理
      </Title>

      <Space style={{ marginBottom: 16 }} wrap>
        <Input
          placeholder="搜索法律名称..."
          prefix={<SearchOutlined />}
          style={{ width: 220 }}
          allowClear
          value={query}
          onChange={(e) => handleSearch(e.target.value)}
        />
        <span>类型:</span>
        <Select
          allowClear
          placeholder="全部类型"
          style={{ width: 120 }}
          value={lawTypeFilter}
          onChange={(v) => {
            setLawTypeFilter(v);
            setSelectedRowKeys([]);
            setPage(1);
          }}
          options={LAW_TYPES.map((t) => ({ value: t, label: t }))}
        />
        <span>状态:</span>
        <Select
          allowClear
          placeholder="全部状态"
          style={{ width: 120 }}
          value={statusFilter}
          onChange={(v) => {
            setStatusFilter(v);
            setSelectedRowKeys([]);
            setPage(1);
          }}
          options={STATUS_LIST.map((s) => ({ value: s, label: s }))}
        />
        <span>阶段:</span>
        <Cascader
          allowClear
          placeholder="全部阶段"
          style={{ width: 200 }}
          value={stageFilter}
          onChange={(v) => setStageFilter(v ?? [])}
          options={STAGE_FILTERS.map((f) => ({
            value: f.value,
            label: f.label,
          }))}
          multiple
          maxTagCount={2}
        />
        <Tooltip title="刷新">
          <Button icon={<ReloadOutlined />} onClick={() => fetchData()} loading={loading} />
        </Tooltip>
      </Space>

      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" icon={<DownloadOutlined />} onClick={() => setCrawlOpen(true)}>
          爬取索引
        </Button>
        <Button icon={<CloudDownloadOutlined />} onClick={handleDownload}>
          下载 ({selectedRowKeys.length > 0 ? getSelected().filter((s) => !s.has_raw).length : "全部"})
        </Button>
        <Button
          icon={<ImportOutlined />}
          onClick={handleBatchImport}
          disabled={
            selectedRowKeys.length === 0 || getSelected().filter((s) => s.has_structured && !s.in_nodes).length === 0
          }
        >
          导入到节点
          {selectedRowKeys.length > 0
            ? ` (${getSelected().filter((s) => s.has_structured && !s.in_nodes).length})`
            : ""}
        </Button>
        <Button
          icon={<RobotOutlined />}
          onClick={handleBatchEmbed}
          disabled={
            selectedRowKeys.length === 0 || getSelected().filter((s) => s.in_nodes && s.chunk_count === 0).length === 0
          }
        >
          嵌入向量
          {selectedRowKeys.length > 0
            ? ` (${getSelected().filter((s) => s.in_nodes && s.chunk_count === 0).length})`
            : ""}
        </Button>
        <Button
          icon={<ThunderboltOutlined />}
          type="dashed"
          onClick={handleBatchImportAndEmbed}
          disabled={
            selectedRowKeys.length === 0 ||
            (getSelected().filter((s) => s.has_structured && !s.in_nodes).length === 0 &&
              getSelected().filter((s) => s.in_nodes && s.chunk_count === 0).length === 0)
          }
        >
          一键导入+嵌入
          {selectedRowKeys.length > 0
            ? ` (${
                getSelected().filter((s) => s.has_structured && !s.in_nodes).length +
                getSelected().filter((s) => s.in_nodes && s.chunk_count === 0).length
              })`
            : ""}
        </Button>
        <Button
          danger
          icon={<DeleteOutlined />}
          onClick={handleBatchDelete}
          disabled={selectedRowKeys.length === 0 || getSelected().filter((s) => s.in_nodes).length === 0}
        >
          删除节点
          {selectedRowKeys.length > 0 ? ` (${getSelected().filter((s) => s.in_nodes).length})` : ""}
        </Button>
        <span style={{ color: "#888", fontSize: 13 }}>
          已选 {selectedRowKeys.length} / 共 {total} 项
        </span>
      </Space>

      <Table
        rowKey="law_name"
        dataSource={data}
        columns={columns}
        loading={loading}
        size="middle"
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showTotal: (t) => `共 ${t} 部法律`,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
            setSelectedRowKeys([]);
          },
        }}
        scroll={{ x: 1100 }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
        }}
      />

      <Modal
        title="启动爬取"
        open={crawlOpen}
        onCancel={() => setCrawlOpen(false)}
        onOk={handleCrawlConfirm}
        okText="开始爬取"
      >
        <div style={{ marginBottom: 16 }}>
          <p>选择要爬取的法律分类。爬取将在后台执行，完成后刷新页面查看结果。</p>
        </div>
        <Select
          style={{ width: "100%" }}
          defaultValue="all"
          onChange={(v) => {
            crawlCategoryRef.current = v;
          }}
          options={CRAWL_CATEGORIES}
        />
      </Modal>
    </div>
  );
}
