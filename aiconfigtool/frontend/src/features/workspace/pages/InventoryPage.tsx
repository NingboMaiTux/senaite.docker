import { useEffect, useState } from 'react';
import {
  App,
  Button,
  Card,
  Popconfirm,
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
  DeleteOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useWorkspace } from '@/core/context/WorkspaceContext';
import { workspaceApi } from '@/features/workspace/services/workspaceApi';
import type { InventorySnapshot, Site } from '@/core/types/domain';
import { type DiffResult } from '@/features/workspace/services/workspaceApi';

const { Title, Paragraph, Text } = Typography;

export default function InventoryPage() {
  const { message } = App.useApp();
  const { companies, currentCompanyCode } = useWorkspace();

  // ── 发起摸底：选公司 + 站点 ──
  const [scanCompany, setScanCompany] = useState<string | null>(
    currentCompanyCode,
  );
  const [scanSite, setScanSite] = useState<string | null>(null);
  const [scanSites, setScanSites] = useState<Site[]>([]);

  // 选公司后从后端加载其站点
  useEffect(() => {
    if (!scanCompany) {
      setScanSites([]);
      return;
    }
    let alive = true;
    workspaceApi.getSites(scanCompany).then((list) => {
      if (alive) setScanSites(list);
    });
    return () => {
      alive = false;
    };
  }, [scanCompany]);

  // 摸底文件列表：从后端加载，按时间倒序
  const [snapshots, setSnapshots] = useState<InventorySnapshot[]>([]);
  const loadSnapshots = () => {
    workspaceApi.getInventories().then((list) => {
      list.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
      setSnapshots(list);
    });
  };
  useEffect(() => { loadSnapshots(); }, []);

  // ── 差异对比：选两个摸底文件 ──
  const [baseId, setBaseId] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string | null>(null);
  const [diffResult, setDiffResult] = useState<DiffResult | null>(null);
  const [diffRunning, setDiffRunning] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [testing, setTesting] = useState(false);

  const runScan = async () => {
    if (!scanSite) { message.warning('请先选择要摸底的站点'); return; }
    setScanning(true);
    try {
      await workspaceApi.runInventory(scanSite);
      message.success('摸底完成，列表已刷新');
      loadSnapshots();
    } catch (err) {
      message.error('摸底失败：' + ((err as Error).message || '请确认后端和 Senaite 均可访问'));
    } finally { setScanning(false); }
  };

  const runTestConnection = async () => {
    if (!scanSite) { message.warning('请先选择站点'); return; }
    setTesting(true);
    try {
      const r = await workspaceApi.testConnection(scanSite);
      message.info(r.reachable ? '连接成功' : `无法连接: ${r.reason || '未知'}`);
    } catch { message.warning('连接测试暂不可用'); }
    finally { setTesting(false); }
  };

  const runDiff = async () => {
    if (!baseId || !targetId) { message.warning('请选择两个摸底文件'); return; }
    const baseSnap = snapshots.find(s => s.id === baseId);
    const targetSnap = snapshots.find(s => s.id === targetId);
    if (!baseSnap || !targetSnap) { message.warning('文件信息不完整'); return; }
    setDiffRunning(true);
    setDiffResult(null);
    try {
      const r = await workspaceApi.diffInventories(
        baseSnap.siteCode, baseId, targetSnap.siteCode, targetId);
      setDiffResult(r);
    } catch (err) {
      message.error('比对失败：' + ((err as Error).message || ''));
    } finally { setDiffRunning(false); }
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
    { title: '版本', dataIndex: 'senaiteVersion', width: 100 },
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
      width: 120,
      render: (_, r) => (
        <Space size={0}>
          <Button size="small" type="link">查看</Button>
          <Popconfirm title="删除该摸底文件？" onConfirm={async () => {
            try { await workspaceApi.deleteInventory(r.siteCode, r.id); message.success('已删除'); loadSnapshots(); }
            catch { message.error('删除失败'); }
          }}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
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
          <Button icon={<ThunderboltOutlined />} disabled={!scanSite} loading={testing} onClick={runTestConnection}>
            连接测试
          </Button>
          <Button
            type="primary"
            icon={<SearchOutlined />}
            disabled={!scanSite}
            loading={scanning}
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
          pagination={{ pageSize: 10, showSizeChanger: false }}
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
              onChange={(v) => { setBaseId(v); if (v === targetId) setTargetId(null); }}
              options={snapshots.filter(s => s.id !== targetId).map((s) => ({
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
              onChange={(v) => { setTargetId(v); if (v === baseId) setBaseId(null); }}
              options={snapshots.filter(s => s.id !== baseId).map((s) => ({
                value: s.id,
                label: snapshotLabel(s),
              }))}
            />
          </Space>
          <Button
            icon={<SwapOutlined />}
            disabled={!baseId || !targetId}
            loading={diffRunning}
            onClick={runDiff}
          >
            开始对比
          </Button>
        </Space>

        {/* 比对结果 */}
        {diffResult && (
          <Card title="比对结果" size="small" style={{ marginTop: 16, background: '#fafafa' }}>
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <Descriptions size="small" column={2}>
                <Descriptions.Item label="基准">{diffResult.base.createdAt}（{diffResult.typeCountA} 类型）</Descriptions.Item>
                <Descriptions.Item label="对比">{diffResult.target.createdAt}（{diffResult.typeCountB} 类型）</Descriptions.Item>
              </Descriptions>
              {diffResult.typeDiffs.length === 0 ? (
                <Text type="secondary">两份摸底文件完全一致，无差异。</Text>
              ) : (
                diffResult.typeDiffs.map((td, i) => (
                  <Card key={i} size="small" type="inner"
                    title={<Space><Tag color={td.change === 'added' ? 'green' : td.change === 'removed' ? 'red' : 'orange'}>{td.change === 'added' ? '新增' : td.change === 'removed' ? '移除' : '变更'}</Tag><Text strong>{td.typeId}</Text></Space>}>
                    {td.title && <Text type="secondary">{td.title}  </Text>}
                    {td.addedFields && td.addedFields.length > 0 && (
                      <div>新增字段：{td.addedFields.map(f => <Tag key={f} color="green">{f}</Tag>)}</div>
                    )}
                    {td.removedFields && td.removedFields.length > 0 && (
                      <div>移除字段：{td.removedFields.map(f => <Tag key={f} color="red">{f}</Tag>)}</div>
                    )}
                    {td.frameworkA && td.frameworkA !== td.frameworkB && (
                      <div>框架变更：<Tag>{td.frameworkA}</Tag> → <Tag color="orange">{td.frameworkB}</Tag></div>
                    )}
                  </Card>
                ))
              )}
            </Space>
          </Card>
        )}
      </Card>
    </div>
  );
}
