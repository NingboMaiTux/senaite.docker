import { useMemo, useState } from 'react';
import {
  App,
  Button,
  Card,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Empty,
  Descriptions,
} from 'antd';
import {
  SearchOutlined,
  ThunderboltOutlined,
  SwapOutlined,
  LinkOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { mockSites, mockInventories } from '@/mocks/data';
import { useWorkspace } from '@/core/context/WorkspaceContext';
import type { InventorySnapshot } from '@/core/types/domain';

const { Title, Paragraph, Text } = Typography;

export default function InventoryPage() {
  const { message } = App.useApp();
  const { companies, currentCompanyCode } = useWorkspace();

  // ── 发起摸底：选公司 + 站点 ──
  const [scanCompany, setScanCompany] = useState<string | null>(
    currentCompanyCode,
  );
  const [scanSite, setScanSite] = useState<string | null>(null);
  const scanSites = useMemo(
    () => mockSites.filter((s) => s.companyCode === scanCompany),
    [scanCompany],
  );

  const [snapshots] = useState<InventorySnapshot[]>(mockInventories);

  // ── 差异对比：选两个摸底文件 ──
  const [baseId, setBaseId] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string | null>(null);

  const runScan = () => {
    if (!scanSite) {
      message.warning('请先选择要摸底的站点');
      return;
    }
    message.success('（演示）已发起摸底，稍后列表会出现新的摸底文件');
  };

  const runDiff = () => {
    if (!baseId || !targetId) {
      message.warning('请选择两个摸底文件进行对比');
      return;
    }
    if (baseId === targetId) {
      message.warning('请选择两个不同的摸底文件');
      return;
    }
    message.success('（演示）开始对比两个摸底文件');
  };

  const snapshotLabel = (s: InventorySnapshot) =>
    `${s.companyName} · ${s.siteName} · ${s.createdAt}`;

  const columns: ColumnsType<InventorySnapshot> = [
    {
      title: '归属',
      key: 'owner',
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Space size={4}>
            <Tag color="blue">{r.companyName}</Tag>
            <Text strong>{r.siteName}</Text>
          </Space>
          <Space size={4}>
            <LinkOutlined style={{ color: '#999' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {r.siteUrl}
            </Text>
          </Space>
        </Space>
      ),
    },
    { title: '摸底时间', dataIndex: 'createdAt', width: 150 },
    { title: 'Senaite 版本', dataIndex: 'senaiteVersion', width: 120 },
    { title: '实体数', dataIndex: 'entityCount', width: 90 },
    { title: 'Addon 数', dataIndex: 'addonCount', width: 90 },
    {
      title: '新鲜度',
      dataIndex: 'staleness',
      width: 90,
      render: (s: InventorySnapshot['staleness']) =>
        s === 'fresh' ? (
          <Tag color="success">新鲜</Tag>
        ) : (
          <Tag color="warning">已过期</Tag>
        ),
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      render: () => (
        <Button size="small" type="link">
          查看
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        🔍 能力摸底
      </Title>
      <Paragraph type="secondary">
        对选定站点扫描其当前实际能力，生成摸底文件。摸底文件自带公司、站点、时间标签，作为 Addon 生成时冲突校验的事实基础。
      </Paragraph>

      {/* 发起摸底 */}
      <Card title="发起摸底" style={{ marginBottom: 16 }}>
        <Space size="middle" wrap>
          <Space>
            <Text>公司：</Text>
            <Select
              style={{ width: 180 }}
              value={scanCompany ?? undefined}
              placeholder="选择公司"
              onChange={(v) => {
                setScanCompany(v);
                setScanSite(null);
              }}
              options={companies.map((c) => ({ value: c.code, label: c.name }))}
            />
          </Space>
          <Space>
            <Text>站点：</Text>
            <Select
              style={{ width: 320 }}
              value={scanSite ?? undefined}
              placeholder="选择站点（必选）"
              onChange={setScanSite}
              options={scanSites.map((s) => ({
                value: s.code,
                label: `${s.name}（${s.url}）`,
              }))}
            />
          </Space>
          <Button icon={<ThunderboltOutlined />} disabled={!scanSite}>
            连接测试
          </Button>
          <Button
            type="primary"
            icon={<SearchOutlined />}
            disabled={!scanSite}
            onClick={runScan}
          >
            开始摸底
          </Button>
        </Space>
        {!scanSite && (
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              未选择站点无法摸底。
            </Text>
          </div>
        )}
      </Card>

      {/* 摸底文件列表 */}
      <Card title="摸底文件" style={{ marginBottom: 16 }}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={snapshots}
          pagination={false}
          locale={{ emptyText: <Empty description="暂无摸底文件" /> }}
        />
      </Card>

      {/* 差异对比 */}
      <Card title="差异对比">
        <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
          <Descriptions.Item label="说明">
            选择两个摸底文件进行对比（可跨站点、跨公司，由你决定比什么）
          </Descriptions.Item>
        </Descriptions>
        <Space size="middle" wrap align="center">
          <Space>
            <Text>基准：</Text>
            <Select
              style={{ width: 320 }}
              value={baseId ?? undefined}
              placeholder="选择摸底文件 A"
              onChange={setBaseId}
              options={snapshots.map((s) => ({
                value: s.id,
                label: snapshotLabel(s),
              }))}
            />
          </Space>
          <SwapOutlined />
          <Space>
            <Text>对比：</Text>
            <Select
              style={{ width: 320 }}
              value={targetId ?? undefined}
              placeholder="选择摸底文件 B"
              onChange={setTargetId}
              options={snapshots.map((s) => ({
                value: s.id,
                label: snapshotLabel(s),
              }))}
            />
          </Space>
          <Button
            icon={<SwapOutlined />}
            disabled={!baseId || !targetId}
            onClick={runDiff}
          >
            开始对比
          </Button>
        </Space>
      </Card>
    </div>
  );
}
