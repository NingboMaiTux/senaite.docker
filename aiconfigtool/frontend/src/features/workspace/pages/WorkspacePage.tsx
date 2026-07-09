import { useEffect, useMemo, useState } from 'react';
import {
  App, Badge, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag, Typography,
} from 'antd';
import { PlusOutlined, ThunderboltOutlined, LinkOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useWorkspace } from '@/core/context/WorkspaceContext';
import { apiClient } from '@/core/services/apiClient';
import { workspaceApi } from '@/features/workspace/services/workspaceApi';
import type { Company, Site, SiteUsage } from '@/core/types/domain';

const { Title, Paragraph, Text } = Typography;

const usageOpts = [
  { value: 'inventory', label: '摸底站' },
  { value: 'test', label: '测试站' },
  { value: 'both', label: '摸底+测试' },
];

export default function WorkspacePage() {
  const { message } = App.useApp();
  const { companies, currentCompany, currentCompanyCode, setCurrentCompanyCode, addCompany, updateCompany, deleteCompany } = useWorkspace();

  // ── 站点（从后端加载）──
  const [sites, setSites] = useState<Site[]>([]);
  const [sitesLoading, setSitesLoading] = useState(false);
  const loadSites = async () => {
    if (!currentCompanyCode) { setSites([]); return; }
    setSitesLoading(true);
    try { setSites(await workspaceApi.getSites(currentCompanyCode)); } catch { message.error('加载站点失败'); }
    finally { setSitesLoading(false); }
  };
  useEffect(() => { loadSites(); }, [currentCompanyCode]);

  const companySites = useMemo(() => sites, [sites]);

  // ── 公司弹窗 ──
  const [coOpen, setCoOpen] = useState(false);
  const [coEdit, setCoEdit] = useState<Company | null>(null);
  const [coForm] = Form.useForm();
  const genId = () => Math.random().toString(36).slice(2, 8);
  const openCo = (c: Company | null) => {
    coForm.resetFields();
    if (c) { coForm.setFieldsValue({ ...c, id: c.shortName }); }
    else { coForm.setFieldsValue({ id: 'co_' + genId() }); }
    setCoEdit(c); setCoOpen(true);
  };
  const submitCo = async () => {
    const v = await coForm.validateFields();
    if (coEdit) {
      const updated = { ...coEdit, ...v };
      await updateCompany(coEdit.code, updated);
      message.success('已更新');
    } else {
      const c: Company = { code: v.id, name: v.name, shortName: v.id, notes: v.notes ?? '', siteCount: 0, createdAt: new Date().toLocaleString('sv').slice(0, 16) };
      await addCompany(c);
      message.success('已创建');
    }
    setCoOpen(false);
  };

  // ── 站点弹窗 ──
  const [siOpen, setSiOpen] = useState(false);
  const [siEdit, setSiEdit] = useState<Site | null>(null);
  const [siForm] = Form.useForm();
  const [siSaving, setSiSaving] = useState(false);
  const openSi = (s: Site | null) => {
    siForm.resetFields();
    if (s) { siForm.setFieldsValue(s); }
    else { siForm.setFieldsValue({ code: 'si_' + genId() }); }
    setSiEdit(s); setSiOpen(true);
  };
  const submitSi = async () => {
    const v = await siForm.validateFields();
    setSiSaving(true);
    try {
      if (siEdit) {
        const updated: Site = { ...siEdit, ...v };
        await workspaceApi.updateSite(siEdit.code, updated);
        setSites(prev => prev.map(s => s.code === siEdit.code ? updated : s));
        message.success('已更新');
      } else {
        const s: Site = { code: v.code, name: v.name, companyCode: currentCompanyCode!, url: v.url, usage: v.usage, senaiteVersion: v.senaiteVersion, notes: v.notes ?? '', status: 'unknown' };
        await workspaceApi.createSite(s);
        setSites(prev => [...prev, s]);
        message.success('已添加');
      }
      setSiOpen(false);
    } catch { message.error('保存失败，请确认后端已启动'); }
    finally { setSiSaving(false); }
  };

  // ── 连接测试 ──
  const [testing, setTesting] = useState<string | null>(null);
  const runTest = async (code: string) => {
    setTesting(code);
    try { const r = await workspaceApi.testConnection(code); message.info(r.reachable ? '连接成功' : `无法连接: ${r.reason || '未知'}`); }
    catch { message.warning('连接测试暂不可用'); }
    finally { setTesting(null); }
  };

  const columns: ColumnsType<Site> = [
    { title: '名称', dataIndex: 'name', render: (n, r) => <Space direction="vertical" size={0}><Text strong>{n}</Text><Text type="secondary" style={{ fontSize: 12 }}><LinkOutlined /> {r.url}</Text></Space> },
    { title: '用途', dataIndex: 'usage', width: 100, render: (u: SiteUsage) => <Tag color={u === 'both' ? 'blue' : u === 'test' ? 'green' : 'orange'}>{usageOpts.find(o => o.value === u)?.label ?? u}</Tag> },
    { title: '版本', dataIndex: 'senaiteVersion', width: 80 },
    { title: '状态', dataIndex: 'status', width: 80, render: (s: Site['status']) => <Badge status={s === 'online' ? 'success' : s === 'offline' ? 'error' : 'default'} text={s === 'online' ? '在线' : s === 'offline' ? '离线' : '未知'} /> },
    {
      title: '操作', key: 'a', width: 250,
      render: (_, r) => (
        <Space>
          <Button size="small" icon={<ThunderboltOutlined />} loading={testing === r.code} onClick={() => runTest(r.code)}>连接测试</Button>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openSi(r)} />
          <Popconfirm title="删除站点？" onConfirm={async () => { try { await workspaceApi.deleteSite(r.code); setSites(prev => prev.filter(s => s.code !== r.code)); message.success('已删除'); } catch { message.error('删除失败'); } }}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // 没有公司时仍显示公司管理区（让用户可以新增）；站点区提示先创建公司
  const hasCompany = !!currentCompany;

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>🏠 工作台</Title>
      <Paragraph type="secondary">管理客户公司和站点。公司是管理分组；一个站点就是一个 URL。</Paragraph>

      <Card title="公司/客户" style={{ marginBottom: 16 }}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => openCo(null)}>新增</Button>}>
        <Space wrap size="middle">
          {companies.map(c => (
            <Card key={c.code} size="small" hoverable
              style={{ width: 240, borderColor: c.code === currentCompanyCode ? '#1677ff' : undefined, cursor: 'pointer' }}
              onClick={() => setCurrentCompanyCode(c.code)}
              title={<Space>{c.name}<Tag color="blue">{c.shortName}</Tag></Space>}
              extra={<Space size={0}>
                <Button type="text" size="small" icon={<EditOutlined />} onClick={(e) => { e.stopPropagation(); openCo(c); }} />
                <Popconfirm title="删除？" onConfirm={async () => { try { await deleteCompany(c.code); message.success('已删除'); } catch { message.error('删除失败'); } }}
                  onPopupClick={(e) => e.stopPropagation()}>
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                </Popconfirm>
              </Space>}>
              <Text type="secondary" style={{ fontSize: 12 }}>{c.notes || '无备注'}</Text>
            </Card>
          ))}
        </Space>
      </Card>

      <Card title={<Space><span>站点</span>{hasCompany && <Text type="secondary">当前：{currentCompany!.name}</Text>}</Space>}
        extra={hasCompany && <Button type="primary" icon={<PlusOutlined />} onClick={() => openSi(null)}>新增站点</Button>}>
        {hasCompany ? (
          <Table rowKey="code" columns={columns} dataSource={companySites} loading={sitesLoading} pagination={false} locale={{ emptyText: '暂无站点，点击右上角新增' }} />
        ) : (
          <Text type="secondary">请先创建或选择一个公司。</Text>
        )}
      </Card>

      {/* 公司弹窗 */}
      <Modal title={coEdit ? '编辑' : '新增'} open={coOpen} onOk={submitCo} onCancel={() => setCoOpen(false)} destroyOnHidden>
        <Form form={coForm} layout="vertical">
          <Form.Item label="全称" name="name" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item
            label="命名空间"
            help="Addon 包名前缀，如命名空间为 shyjs 则包名为 shyjs.samplefield。创建后不可修改。"
          >
            <Space.Compact style={{ width: '100%' }}>
              <Form.Item
                name="id"
                noStyle
                rules={[{ required: true }, { pattern: /^[a-z][a-z0-9_-]*$/, message: '小写字母开头，创建后不可修改' }]}
              >
                <Input disabled={!!coEdit} />
              </Form.Item>
              {!coEdit && (
                <Button
                  type="primary"
                  onClick={async () => {
                    const name = coForm.getFieldValue('name');
                    if (!name?.trim()) { message.warning('请先输入公司全称'); return; }
                    try {
                      const r = await apiClient.post<{ namespace: string }>('/config/generate-namespace', { name });
                      coForm.setFieldsValue({ id: r.namespace });
                      message.success('已生成: ' + r.namespace);
                    } catch { message.error('生成失败，请手动输入'); }
                  }}
                >
                  AI生成
                </Button>
              )}
            </Space.Compact>
          </Form.Item>
          <Form.Item label="备注" name="notes"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      {/* 站点弹窗 */}
      <Modal title={siEdit ? '编辑站点' : '新增站点'} open={siOpen} onOk={submitSi} onCancel={() => setSiOpen(false)} confirmLoading={siSaving} destroyOnHidden>
        <Form form={siForm} layout="vertical" initialValues={{ usage: 'inventory', senaiteVersion: '2.7.0' }}>
          <Form.Item label="名称" name="name" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item label="ID" name="code" rules={[{ required: true }, { pattern: /^[a-z0-9][a-z0-9_-]*$/, message: '小写字母/数字开头' }]} help="创建后不可修改，唯一即可">
            <Input disabled={!!siEdit} /></Form.Item>
          <Form.Item label="URL" name="url" rules={[{ required: true }]}><Input placeholder="http://127.0.0.1:8083/senaite" /></Form.Item>
          <Form.Item label="用途" name="usage"><Select options={usageOpts} /></Form.Item>
          <Form.Item label="版本" name="senaiteVersion"><Input /></Form.Item>
          <Form.Item label="备注" name="notes"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
