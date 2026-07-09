import { useEffect, useState } from 'react';
import { App, Button, Card, Popconfirm, Space, Table, Tag, Typography, Empty } from 'antd';
import { DownloadOutlined, DeleteOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { apiClient } from '@/core/services/apiClient';

const { Title, Paragraph, Text } = Typography;

interface DeliveryRecord {
  id: string;
  addonName: string;
  version: string;
  generatedAt: string;
  fileCount: number;
  packageSizeKb: number;
  companyCode: string;
  companyName: string;
  status: string;
}

export default function DeliveryPage() {
  const { message } = App.useApp();
  const [data, setData] = useState<DeliveryRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    apiClient.get<DeliveryRecord[]>('/deliveries')
      .then(setData).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const del = async (id: string) => {
    try { await apiClient.del('/deliveries/' + id); message.success('已删除'); load(); }
    catch { message.error('删除失败'); }
  };

  const columns: ColumnsType<DeliveryRecord> = [
    { title: 'Addon', dataIndex: 'addonName', render: (n, r) => <Space><Text strong>{n}</Text><Tag>v{r.version}</Tag></Space> },
    { title: '公司', dataIndex: 'companyName', width: 140, render: (n, r) => n || <Tag>{r.companyCode}</Tag> },
    { title: '生成时间', dataIndex: 'generatedAt', width: 160 },
    { title: '大小', dataIndex: 'packageSizeKb', width: 80, render: (kb: number) => `${kb} KB` },
    { title: '状态', dataIndex: 'status', width: 70, render: (s: string) => <Tag color={s === 'packaged' ? 'green' : 'blue'}>{s}</Tag> },
    {
      title: '操作', key: 'a', width: 150,
      render: (_, r) => (
        <Space size={0}>
          <Button size="small" icon={<DownloadOutlined />} href={`/api/addon-studio/download/${r.id}`}>下载</Button>
          <Popconfirm title="删除？" onConfirm={() => del(r.id)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>📦 交付管理</Title>
      <Paragraph type="secondary">历次生成的 Addon 交付包。</Paragraph>
      <Card title="交付历史">
        <Table rowKey="id" columns={columns} dataSource={data} loading={loading} pagination={false}
          locale={{ emptyText: <Empty description="暂无交付记录" /> }} />
      </Card>
    </div>
  );
}
