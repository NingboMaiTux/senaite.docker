import { useState } from 'react';
import { Button, Card, List, Result, Space, Spin, Tag, Typography } from 'antd';
import { CheckCircleTwoTone, RocketOutlined } from '@ant-design/icons';
import type { GateResult } from '@/core/types/domain';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

const gateSteps: GateResult[] = [
  { gate: 'Gate0', label: '输入验证（格式、路径穿越检查）', status: 'passed' },
  { gate: 'Gate1', label: '结构验证（字段名在目标类型中不存在）', status: 'passed' },
  { gate: 'Gate2', label: '生成产物验证（文件完整性）', status: 'passed' },
];

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepGenerate({ state, dispatch }: Props) {
  const [phase, setPhase] = useState<'idle' | 'running' | 'done'>(
    state.generationStatus === 'success' ? 'done' : 'idle',
  );
  const meta = state.addonMeta;
  const fullName = meta ? `${meta.namespace}.${meta.functionName}` : 'addon';
  const pkgName = `${fullName}-${meta?.version ?? '1.0.0'}.zip`;

  const run = () => {
    setPhase('running');
    dispatch({ type: 'SET_GENERATION_STATUS', status: 'running' });
    setTimeout(() => {
      setPhase('done');
      dispatch({ type: 'SET_GATE_RESULTS', results: gateSteps });
      dispatch({ type: 'SET_GENERATION_STATUS', status: 'success' });
    }, 1400);
  };

  return (
    <Card title="步骤 5 / 6 · 生成 Addon" variant="outlined">
      {phase === 'idle' && (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Text type="secondary">
            即将生成 <Text code>{pkgName}</Text>，执行 Gate0 → Gate1 → 代码生成 →
            Gate2 → 打包 → 文档生成。
          </Text>
          <Button
            type="primary"
            size="large"
            icon={<RocketOutlined />}
            onClick={run}
          >
            一键生成 Addon
          </Button>
        </Space>
      )}

      {phase === 'running' && (
        <Space
          direction="vertical"
          align="center"
          style={{ width: '100%', padding: 40 }}
        >
          <Spin size="large" />
          <Text type="secondary">正在生成代码并执行门控验证…</Text>
        </Space>
      )}

      {phase === 'done' && (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <List
            size="small"
            bordered
            dataSource={gateSteps}
            renderItem={(g) => (
              <List.Item>
                <Space>
                  <CheckCircleTwoTone twoToneColor="#52c41a" />
                  <Tag color="green">{g.gate}</Tag>
                  <Text>{g.label}</Text>
                </Space>
              </List.Item>
            )}
          />
          <Result
            status="success"
            title="Addon 生成成功"
            subTitle={`${pkgName} · 34 KB · 含实施部署指南`}
            style={{ paddingBottom: 0 }}
          />
          <Text type="secondary">
            下一步可选择：在测试站点安装验证，或直接下载交付。
          </Text>
        </Space>
      )}
    </Card>
  );
}
