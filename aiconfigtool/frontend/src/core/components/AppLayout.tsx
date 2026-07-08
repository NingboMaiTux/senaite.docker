import { useMemo } from 'react';
import { Layout, Menu, Select, Space, Typography, theme } from 'antd';
import {
  AppstoreOutlined,
  ExperimentOutlined,
  InboxOutlined,
  SafetyOutlined,
  SettingOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import ContextStatusBar from '@/core/components/ContextStatusBar';
import { useWorkspace } from '@/core/context/WorkspaceContext';

const { Header, Sider, Content, Footer } = Layout;
const { Title } = Typography;

const menuItems = [
  { key: '/workspace', icon: <AppstoreOutlined />, label: '工作台' },
  { key: '/inventory', icon: <SearchOutlined />, label: '能力摸底' },
  { key: '/studio', icon: <ExperimentOutlined />, label: 'Addon 工坊' },
  { key: '/delivery', icon: <InboxOutlined />, label: '交付管理' },
  { key: '/permissions', icon: <SafetyOutlined />, label: '权限工具（咨询）' },
  { key: '/settings', icon: <SettingOutlined />, label: '设置' },
];

export default function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { companies, currentCompanyCode, setCurrentCompanyCode } =
    useWorkspace();
  const {
    token: { colorBgContainer },
  } = theme.useToken();

  const selectedKey = useMemo(() => {
    const match = menuItems.find((m) => location.pathname.startsWith(m.key));
    return match?.key ?? '/studio';
  }, [location.pathname]);

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider theme="light" width={200} style={{ borderRight: '1px solid #f0f0f0' }}>
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <ExperimentOutlined style={{ fontSize: 20, color: '#1677ff' }} />
          <Title level={5} style={{ margin: 0 }}>
            AiConfigTool
          </Title>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          style={{ borderInlineEnd: 'none' }}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>

      <Layout>
        <Header
          style={{
            background: colorBgContainer,
            borderBottom: '1px solid #f0f0f0',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            height: 56,
          }}
        >
          <Typography.Text type="secondary">
            Senaite Addon AI 配置工具 · v2.0
          </Typography.Text>
          <Space>
            <Typography.Text type="secondary">当前公司</Typography.Text>
            <Select
              value={currentCompanyCode ?? undefined}
              style={{ width: 180 }}
              onChange={setCurrentCompanyCode}
              options={companies.map((c) => ({
                value: c.code,
                label: c.name,
              }))}
            />
          </Space>
        </Header>

        <Content
          style={{
            margin: 16,
            padding: 24,
            background: colorBgContainer,
            borderRadius: 8,
            overflow: 'auto',
          }}
        >
          <Outlet />
        </Content>

        <Footer style={{ padding: 0 }}>
          <ContextStatusBar />
        </Footer>
      </Layout>
    </Layout>
  );
}
