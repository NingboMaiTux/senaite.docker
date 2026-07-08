import { useEffect, useMemo, useState } from 'react';
import {
  Card,
  Form,
  Input,
  Radio,
  Space,
  Tag,
  Typography,
} from 'antd';
import { useWorkspace } from '@/core/context/WorkspaceContext';
import type { NamespaceMode } from '@/core/types/domain';
import type { WorkflowAction } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

interface Props {
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepConfigureAddon({ dispatch }: Props) {
  const { currentCompany } = useWorkspace();
  const companyNs = currentCompany?.shortName ?? 'client';

  const [mode, setMode] = useState<NamespaceMode>('custom');
  const [functionName, setFunctionName] = useState('samplefield');
  const [version, setVersion] = useState('1.0.0');
  const [description, setDescription] = useState(
    `为 ${currentCompany?.name ?? ''} 生成的 Senaite Addon`,
  );

  const namespace = mode === 'general' ? 'maitux' : companyNs;
  const fullName = useMemo(
    () => `${namespace}.${functionName}`,
    [namespace, functionName],
  );

  useEffect(() => {
    dispatch({
      type: 'SET_ADDON_META',
      meta: {
        namespaceMode: mode,
        namespace,
        functionName,
        version,
        description,
        dependencies: ['senaite.core >= 2.5.0'],
      },
    });
  }, [mode, namespace, functionName, version, description, dispatch]);

  return (
    <Card title="步骤 4 / 6 · 配置 Addon 元信息" variant="outlined">
      <Form layout="vertical" style={{ maxWidth: 560 }}>
        <Form.Item label="命名空间">
          <Radio.Group
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <Space direction="vertical">
              <Radio value="general">
                通用包 <Tag color="blue">maitux</Tag>
                <Text type="secondary"> 可复用于多个客户</Text>
              </Radio>
              <Radio value="custom">
                客户定制 <Tag color="green">{companyNs}</Tag>
                <Text type="secondary"> 仅用于 {currentCompany?.name}</Text>
              </Radio>
            </Space>
          </Radio.Group>
        </Form.Item>

        <Form.Item label="功能名称">
          <Space.Compact style={{ width: '100%' }}>
            <Input
              style={{ width: '40%' }}
              value={namespace}
              disabled
              addonBefore="命名空间"
            />
            <Input
              style={{ width: '60%' }}
              value={functionName}
              onChange={(e) => setFunctionName(e.target.value)}
            />
          </Space.Compact>
          <Text type="secondary" style={{ fontSize: 12 }}>
            完整包名：<Text code>{fullName}</Text>
          </Text>
        </Form.Item>

        <Form.Item label="版本号">
          <Input
            style={{ width: 160 }}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          />
        </Form.Item>

        <Form.Item label="描述">
          <Input.TextArea
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Form.Item>

        <Form.Item label="依赖">
          <Tag>senaite.core &gt;= 2.5.0</Tag>
        </Form.Item>
      </Form>
    </Card>
  );
}
