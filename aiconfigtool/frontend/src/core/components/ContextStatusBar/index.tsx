import { Space, Tag, Typography } from 'antd';
import {
  CheckCircleFilled,
  CloudServerOutlined,
  RobotOutlined,
  DatabaseOutlined,
} from '@ant-design/icons';
import { useWorkspace } from '@/core/context/WorkspaceContext';

const { Text } = Typography;

/** 底部上下文状态栏：始终展示当前工作上下文 */
export default function ContextStatusBar() {
  const { currentCompany } = useWorkspace();

  return (
    <div
      style={{
        height: 32,
        lineHeight: '32px',
        padding: '0 16px',
        background: '#fff',
        borderTop: '1px solid #f0f0f0',
        display: 'flex',
        alignItems: 'center',
        fontSize: 12,
      }}
    >
      <Space size="large" split={<span style={{ color: '#d9d9d9' }}>|</span>}>
        <Space size={4}>
          <CheckCircleFilled style={{ color: '#52c41a' }} />
          <Text type="secondary">就绪</Text>
        </Space>
        <Space size={4}>
          <CloudServerOutlined />
          <Text type="secondary">
            公司：{currentCompany?.name ?? '未选择'}
          </Text>
        </Space>
        <Space size={4}>
          <DatabaseOutlined />
          <Text type="secondary">站点：shyjs-prod</Text>
          <Tag color="blue" style={{ marginInlineStart: 4 }}>
            Senaite 2.5.0
          </Tag>
        </Space>
        <Space size={4}>
          <RobotOutlined />
          <Text type="secondary">Ollama: deepseek-r1:8b</Text>
        </Space>
      </Space>
    </div>
  );
}
