import { useMemo, useState } from 'react';
import {
  App,
  Badge,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  PlusOutlined,
  ThunderboltOutlined,
  LinkOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { mockSites } from '@/mocks/data';
import { useWorkspace } from '@/core/context/WorkspaceContext';
import type { Company, Site, SiteUsage } from '@/core/types/domain';

const { Title, Paragraph, Text } = Typography;

const usageTag: Record<SiteUsage, { color: string; text: string }> = {
  inventory: { color: 'orange', text: '摸底站' },
  test: { color: 'green', text: '测试站' },
  both: { color: 'blue', text: '摸底+测试' },
};

const statusBadge: Record<
  Site['status'],
  { status: 'success' | 'error' | 'default'; text: string }
> = {
  online: { status: 'success', text: '在线' },
  offline: { status: 'error', text: '离线' },
  unknown: { status: 'default', text: '未知' },
};

export default function WorkspacePage() {
  const { message } = App.useApp();
  const {
    companies,
    currentCompany,
    currentCompanyCode,
    addCompany,
    updateCompany,
    deleteCompany,
  } = useWorkspace();

  // 站点这里用本地 state 演示（真实接后端后改为 API）
  const [sites, setSites] = useState<Site[]>(mockSites);
  const companySites = useMemo(
    () => sites.filter((s) => s.companyCode === currentCompanyCode),
    [sites, currentCompanyCode],
  );

  const [companyModal, setCompanyModal] = useState<{
    open: boolean;
    editing: Company | null;
  }>({ open: false, editing: null });
  const [siteModal, setSiteModal] = useState(false);
  const [companyForm] = Form.useForm();
  const [siteForm] = Form.useForm();

  // ── 公司 ──
  const openCompanyModal = (editing: Company | null) => {
    companyForm.resetFields();
    if (editing) companyForm.setFieldsValue(editing);
    setCompanyModal({ open: true, editing });
  };

  const submitCompany = async () => {
    const v = await companyForm.validateFields();
    if (companyModal.editing) {
      updateCompany(companyModal.editing.code, {
        ...companyModal.editing,
        ...v,
      });
      message.success('公司已更新');
    } else {
      addCompany({
        code: v.shortName,
        name: v.name,
        shortName: v.shortName,
        notes: v.notes ?? '',
        siteCount: 0,
        createdAt: new Date().toLocaleString('sv').slice(0, 16),
      });
      message.success('公司已创建');
    }
    setCompanyModal({ open: false, editing: null });
  };

  // ── 站点 ──
  const submitSite = async () => {
    const v = await siteForm.validateFields();
    const newSite: Site = {
      code: `${currentCompanyCode}-${v.code}`,
      name: v.name,
      companyCode: currentCompanyCode!,
      url: v.url,
      usage: v.usage,
      senaiteVersion: v.senaiteVersion,
      notes: v.notes ?? '',
      status: 'unknown',
    };
    setSites((prev) => [...prev, newSite]);
    message.success('站点已添加');
    siteForm.resetFields();
    setSiteModal(false);
  };

  const siteColumns: ColumnsType<Site> = [
    {
      title: '站点名称',
      dataIndex: 'name',
      render: (name, r) => (
        <Space direction="vertical" size={0}>
          <Text strong>{name}</Text>
          <Space size={4}>
            <LinkOutlined style={{ color: '#999' }} />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {r.url}
            </Text>
          </Space>
        </Space>
      ),
    },
    {
      title: '用途',
      dataIndex: 'usage',
      width: 110,
      render: (u: SiteUsage) => (
        <Tag color={usageTag[u].color}>{usageTag[u].text}</Tag>
      ),
    },
    { title: 'Senaite 版本', dataIndex: 'senaiteVersion', width: 120 },
    {
      title: '上次摸底',
      dataIndex: 'lastInventoryAt',
      width: 150,
      render: (v) => v ?? '—',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: Site['status']) => (
        <Badge status={statusBadge[s].status} text={statusBadge[s].text} />
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: () => (
        <Space>
          <Button size="small" icon={<ThunderboltOutlined />}>
            连接测试
          </Button>
          <Button size="small" type="link">
            编辑
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        🏠 工作台
      </Title>
      <Paragraph type="secondary">
        管理公司和站点。公司是管理分组；一个站点就是一个 URL，可标记为摸底站或测试站。
      </Paragraph>

      {/* 公司管理 */}
      <Card
        title="公司"
        style={{ marginBottom: 16 }}
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => openCompanyModal(null)}
          >
            新增公司
          </Button>
        }
      >
        <Space wrap size="middle">
          {companies.map((c) => (
            <Card
              key={c.code}
              size="small"
              style={{
                width: 240,
                borderColor:
                  c.code === currentCompanyCode ? '#1677ff' : undefined,
              }}
              title={
                <Space>
                  {c.name}
                  <Tag color="blue">{c.shortName}</Tag>
                </Space>
              }
              extra={
                <Space size={0}>
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => openCompanyModal(c)}
                  />
                  <Popconfirm
                    title="删除该公司？"
                    description="其下站点也将无法访问"
                    onConfirm={() => {
                      deleteCompany(c.code);
                      message.success('公司已删除');
                    }}
                  >
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                    />
                  </Popconfirm>
                </Space>
              }
            >
              <Text type="secondary" style={{ fontSize: 12 }}>
                {c.notes || '无备注'}
              </Text>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                站点数：
                {sites.filter((s) => s.companyCode === c.code).length}
              </Text>
            </Card>
          ))}
        </Space>
      </Card>

      {/* 站点管理 */}
      <Card
        title={
          <Space>
            <span>站点</span>
            <Text type="secondary" style={{ fontWeight: 400 }}>
              当前公司：{currentCompany?.name}
            </Text>
          </Space>
        }
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              siteForm.resetFields();
              setSiteModal(true);
            }}
          >
            新增站点
          </Button>
        }
      >
        <Table
          rowKey="code"
          columns={siteColumns}
          dataSource={companySites}
          pagination={false}
          locale={{ emptyText: '该公司下暂无站点，点击右上角新增' }}
        />
      </Card>

      {/* 公司弹窗 */}
      <Modal
        title={companyModal.editing ? '编辑公司' : '新增公司'}
        open={companyModal.open}
        onOk={submitCompany}
        onCancel={() => setCompanyModal({ open: false, editing: null })}
        destroyOnHidden
      >
        <Form form={companyForm} layout="vertical">
          <Form.Item
            label="公司全称"
            name="name"
            rules={[{ required: true, message: '请输入公司全称' }]}
          >
            <Input placeholder="如：上海医检所" />
          </Form.Item>
          <Form.Item
            label="简称（用于 Addon 命名空间）"
            name="shortName"
            rules={[
              { required: true, message: '请输入简称' },
              {
                pattern: /^[a-z][a-z0-9]*$/,
                message: '小写字母开头，仅小写字母和数字',
              },
            ]}
          >
            <Input placeholder="如：shyjs" disabled={!!companyModal.editing} />
          </Form.Item>
          <Form.Item label="备注" name="notes">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 站点弹窗 */}
      <Modal
        title="新增站点"
        open={siteModal}
        onOk={submitSite}
        onCancel={() => setSiteModal(false)}
        destroyOnHidden
      >
        <Form form={siteForm} layout="vertical" initialValues={{ usage: 'inventory', senaiteVersion: '2.5.0' }}>
          <Form.Item
            label="站点名称"
            name="name"
            rules={[{ required: true, message: '请输入站点名称' }]}
          >
            <Input placeholder="如：生产站点" />
          </Form.Item>
          <Form.Item
            label="站点标识"
            name="code"
            rules={[{ required: true, message: '请输入站点标识' }]}
          >
            <Input placeholder="如：maitux（用于内部标识）" />
          </Form.Item>
          <Form.Item
            label="站点 URL"
            name="url"
            rules={[
              { required: true, message: '请输入站点 URL' },
              { type: 'url', message: 'URL 格式不正确' },
            ]}
          >
            <Input placeholder="http://121.40.188.203/Maitux" />
          </Form.Item>
          <Form.Item label="用途" name="usage">
            <Select
              options={[
                { value: 'inventory', label: '摸底站（扫能力）' },
                { value: 'test', label: '测试站（装 Addon 验证）' },
                { value: 'both', label: '摸底 + 测试' },
              ]}
            />
          </Form.Item>
          <Form.Item label="Senaite 版本" name="senaiteVersion">
            <Input placeholder="2.5.0" />
          </Form.Item>
          <Form.Item label="备注" name="notes">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="提示">
            一个 URL 就是一个站点，不必关心它在哪台服务器
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    </div>
  );
}
