import { FileSearchOutlined } from "@ant-design/icons";
import { App, Card, Empty, Input, InputNumber, List, Slider, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { ragSearch } from "@/api/rag";
import type { SearchItem } from "@/api/types";

const { Title, Text, Paragraph } = Typography;

export default function RagSearchPage() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<SearchItem[]>([]);
  const [searched, setSearched] = useState(false);
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [k, setK] = useState(4);
  const [vecweight, setVecweight] = useState(0.6);
  const [regex, setRegex] = useState("");

  const handleSearch = async (query: string) => {
    const q = query.trim();
    if (!q) {
      message.warning("请输入查询内容");
      return;
    }
    setLoading(true);
    const start = performance.now();
    try {
      const res = await ragSearch({ query: q, k, vecweight, regex: regex.trim() || undefined });
      setElapsed(performance.now() - start);
      setSearched(true);
      if (res.success) {
        setResults(res.results);
      } else {
        setResults([]);
        message.error(res.status);
      }
    } catch (e) {
      setResults([]);
      message.error(e instanceof Error ? e.message : "搜索失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <Title level={3}>
        <FileSearchOutlined /> 知识库搜索测试
      </Title>
      <Paragraph type="secondary">
        直接调用 /api/rag/search 混合检索接口 (向量 + BM25 + 重排)，用于验证知识库检索效果。
      </Paragraph>

      <Card style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Input.Search
            placeholder="输入查询内容，如：劳动合同解除的经济补偿标准"
            enterButton="搜索"
            size="large"
            loading={loading}
            onSearch={handleSearch}
            allowClear
          />
          <Space wrap size="large">
            <Space>
              <Text>返回条数 k:</Text>
              <InputNumber min={1} max={50} value={k} onChange={(v) => setK(v ?? 4)} />
            </Space>
            <Space>
              <Text>向量权重:</Text>
              <Slider min={0} max={1} step={0.05} value={vecweight} onChange={setVecweight} style={{ width: 160 }} />
              <Text type="secondary">{vecweight.toFixed(2)}</Text>
            </Space>
            <Space>
              <Text>来源过滤 (regex):</Text>
              <Input
                placeholder="如：劳动合同法"
                value={regex}
                onChange={(e) => setRegex(e.target.value)}
                allowClear
                style={{ width: 200 }}
              />
            </Space>
          </Space>
        </Space>
      </Card>

      {searched ? (
        <Card
          title={
            <Space>
              <span>搜索结果 ({results.length})</span>
              {elapsed !== null ? <Text type="secondary">耗时 {(elapsed / 1000).toFixed(2)} s</Text> : null}
            </Space>
          }
        >
          {results.length === 0 ? (
            <Empty description="无匹配结果" />
          ) : (
            <List
              itemLayout="vertical"
              dataSource={results}
              renderItem={(item, index) => (
                <List.Item key={`${item.source_name}-${item.page_index}-${index}`}>
                  <Space wrap style={{ marginBottom: 8 }}>
                    <Tag color="blue">#{index + 1}</Tag>
                    {item.source_name ? <Tag color="geekblue">{item.source_name}</Tag> : null}
                    {item.page_index ? <Tag>{item.page_index}</Tag> : null}
                    {item.score !== null && !Number.isNaN(item.score) ? (
                      <Tag color="green">score: {item.score.toFixed(4)}</Tag>
                    ) : null}
                  </Space>
                  <Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{item.content}</Paragraph>
                </List.Item>
              )}
            />
          )}
        </Card>
      ) : null}
    </div>
  );
}
