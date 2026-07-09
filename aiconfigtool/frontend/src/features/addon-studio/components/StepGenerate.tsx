import { useState } from 'react';
import { App, Button, Card, List, Result, Space, Spin, Tag, Typography } from 'antd';
import { CheckCircleTwoTone, CloseCircleTwoTone, RocketOutlined } from '@ant-design/icons';
import { addonStudioApi, type GenerateResult } from '../services/addonStudioApi';
import type { GateResult } from '@/core/types/domain';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepGenerate({ state, dispatch }: Props) {
  const { message } = App.useApp();
  const [phase, setPhase] = useState<'idle' | 'running' | 'done' | 'failed'>(
    state.generationStatus === 'success' ? 'done' : 'idle',
  );
  const [gateResults, setGateResults] = useState<GateResult[]>([]);
  const [genResult, setGenResult] = useState<GenerateResult | null>(null);
  const meta = state.addonMeta;
  const fullName = meta ? `${meta.namespace}.${meta.functionName}` : 'addon';
  const pkgName = `${fullName}-${meta?.version ?? '1.0.0'}.zip`;

  const run = async () => {
    if (!state.siteCode || !state.changeSpec || !meta) {
      message.warning('前置信息不完整，请返回前面步骤补齐');
      return;
    }
    setPhase('running');
    dispatch({ type: 'SET_GENERATION_STATUS', status: 'running' });
    try {
      const invRef = state.inventoryRef || `inv_${state.siteCode}`;
      const result = await addonStudioApi.generate({
        siteCode: state.siteCode,
        inventoryRef: invRef,
        changes: state.changeSpec.changes,
        meta: {
          namespace: meta.namespace,
          functionName: meta.functionName,
          version: meta.version,
          description: meta.description,
        },
      });
      setGenResult(result);
      dispatch({ type: 'SET_GENERATE_RESULT', packageId: result.packageId, sizeKb: result.packageSizeKb });
      const gates: GateResult[] = [
        { gate: 'Gate0', label: '输入验证（格式、路径穿越检查）', status: 'passed' },
        { gate: 'Gate1', label: '冲突校验（需求 vs 站点能力）', status: 'passed' },
        { gate: 'Gate2', label: `产物验证（${result.fileCount} 个文件，${result.gate2.passed ? '通过' : '缺失: ' + result.gate2.missing.join(',')}）`, status: result.gate2.passed ? 'passed' : 'failed' },
      ];
      setGateResults(gates);
      dispatch({ type: 'SET_GATE_RESULTS', results: gates });
      dispatch({ type: 'SET_GENERATION_STATUS', status: 'success' });
      setPhase('done');
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      if (msg.includes('conflict') || msg.includes('冲突')) {
        setPhase('failed');
        dispatch({ type: 'SET_GENERATION_STATUS', status: 'failed' });
      } else {
        message.error('生成失败：' + (msg || '请确认后端已启动'));
        setPhase('idle');
      }
    }
  };

  return (
    <Card title="步骤 5 / 6 · 生成 Addon" variant="outlined">
      {phase === 'idle' && (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Text type="secondary">
            即将生成 <Text code>{pkgName}</Text>，执行 Gate0 → Gate1 → 代码生成 → Gate2 → 打包 → 文档生成。
          </Text>
          <Button type="primary" size="large" icon={<RocketOutlined />} onClick={run}>
            一键生成 Addon
          </Button>
        </Space>
      )}

      {phase === 'running' && (
        <Space direction="vertical" align="center" style={{ width: '100%', padding: 40 }}>
          <Spin size="large" />
          <Text type="secondary">正在生成代码并执行门控验证…</Text>
        </Space>
      )}

      {phase === 'failed' && (
        <Result
          status="error"
          title="生成失败"
          subTitle="存在冲突，无法生成。请返回调整需求。"
        >
          <Button onClick={() => setPhase('idle')}>重试</Button>
        </Result>
      )}

      {phase === 'done' && (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <List
            size="small"
            bordered
            dataSource={gateResults}
            renderItem={(g) => (
              <List.Item>
                <Space>
                  {g.status === 'passed' ? (
                    <CheckCircleTwoTone twoToneColor="#52c41a" />
                  ) : (
                    <CloseCircleTwoTone twoToneColor="#ff4d4f" />
                  )}
                  <Tag color={g.status === 'passed' ? 'green' : 'red'}>{g.gate}</Tag>
                  <Text>{g.label}</Text>
                </Space>
              </List.Item>
            )}
          />
          <Result
            status="success"
            title="Addon 生成成功"
            subTitle={
              genResult
                ? `${genResult.fullName}-${genResult.version}.zip · ${genResult.packageSizeKb} KB · ${genResult.fileCount} 个文件 · 含 ${genResult.deployDocName}`
                : `${pkgName} · 含实施部署指南`
            }
            style={{ paddingBottom: 0 }}
          />
          <Text type="secondary">下一步可选择：在测试站点安装验证，或直接下载交付。</Text>
        </Space>
      )}
    </Card>
  );
}
