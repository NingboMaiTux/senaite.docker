import { Button, Card, Space, Table, Tag, Typography } from 'antd';
import { DownloadOutlined, FileTextOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { mockDeliveries } from '@/mocks/data';
import type { DeliveryRecord } from '@/core/types/domain';

const { Title, Paragraph } = Typography;

const statusTag: Record<DeliveryRecord['status'], { color: string; text: string }> = {
  validated: { color: 'blue', text: '已验证' },
  packaged: { color: 'green', text: '已打包' },
  failed: { color: 'red', text: '失败' },
};

export default function DeliveryPage() {
  const columns: ColumnsType<DeliveryRecord> = [
    {
      title: 'Addon 包',
      dataIndex: 'addonName',
      render: (name, r) => (
        <Space>
          <Typography.Text strong>{name}</Typography.Text>
          <Tag>v{r.version}</Tag>
        </Space>
      ),
    },
    { title: '公司', dataIndex: 'companyCode' },
    { title: '站点', dataIndex: 'siteCode' },
    {
      title: '变更类型',
      dataIndex: 'changeTypes',
      render: (types: DeliveryRecord['changeTypes']) => (
        <Space size={4} wrap>
          {types.map((t) => (
            <Tag key={t} color="cyan">
              {t}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '大小',
      dataIndex: 'packageSizeKb',
      render: (kb: number) => (kb > 0 ? `${kb} KB` : '—'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (s: DeliveryRecord['status']) => (
        <Tag color={statusTag[s].color}>{statusTag[s].text}</Tag>
      ),
    },
    { title: '生成时间', dataIndex: 'createdAt' },
    {
      title: '操作',
      key: 'action',
      render: (_, r) =>
        r.status === 'failed' ? (
          <Button size="small" type="link">
            查看错误
          </Button>
        ) : (
          <Space>
            <Button size="small" icon={<DownloadOutlined />}>
              包
            </Button>
            <Button size="small" icon={<FileTextOutlined />}>
              部署指南
            </Button>
          </Space>
        ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        📦 交付管理
      </Title>
      <Paragraph type="secondary">
        查看历次生成的 Addon 交付包、部署文档和证据包。
      </Paragraph>

      <Card title="交付历史">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={mockDeliveries}
          pagination={false}
        />
      </Card>
    </div>
  );
}
