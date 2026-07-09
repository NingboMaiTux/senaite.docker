import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Input, Segmented, Space, Typography } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { apiClient } from '@/core/services/apiClient';
import { addonStudioApi } from '../services/addonStudioApi';
import ChangeItemCard from './ChangeItemCard';
import type { AIProvider } from '@/core/types/domain';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

const examples = [
  '为 AnalysisProfile 添加一个名为 maitux_sample_code 的字符串字段',
  '给 AnalysisProfile 添加一个必填的文本字段 remark',
  '为 Client 添加一个名为 maitux_note 的多行文本字段',
];

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepDescribeChange({ state, dispatch }: Props) {
  const { message } = App.useApp();
  const spec = state.changeSpec;
  const [parsing, setParsing] = useState(false);

  // 从设置页配置加载默认 AI 引擎
  useEffect(() => {
    apiClient.get<{ ai: { provider: string } }>('/config/workspace')
      .then(c => { if (c.ai?.provider) dispatch({ type: 'SET_PROVIDER', provider: c.ai.provider as AIProvider }); })
      .catch(() => {});
  }, []);

  // 接住「权限工具 → 带到工坊」预填的需求
  useEffect(() => {
    const prefill = localStorage.getItem('aiconfigtool.studioPrefill');
    if (prefill && !state.naturalLanguageInput) {
      dispatch({ type: 'SET_NL', text: prefill });
      localStorage.removeItem('aiconfigtool.studioPrefill');
    }
  }, []);

  const handleParse = async () => {
    if (!state.naturalLanguageInput.trim()) {
      message.warning('请输入需求描述');
      return;
    }
    if (!state.siteCode) {
      message.warning('请先在步骤1选择摸底站点');
      return;
    }
    setParsing(true);
    try {
      const result = await addonStudioApi.parseRequirement({
        siteCode: state.siteCode,
        inventoryRef: state.inventoryRef || `inv_${state.siteCode}`,
        text: state.naturalLanguageInput,
      });
      dispatch({ type: 'SET_CHANGE_SPEC', spec: result });
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      if (msg.includes('CHANGE_SPEC_INVALID')) {
        message.warning('AI 无法解析，请调整描述。示例：为 X 添加一个名为 Y 的 Z 字段');
      } else {
        message.error('需求解析失败：' + (msg || '请确认后端已启动'));
      }
    } finally {
      setParsing(false);
    }
  };

  return (
    <Card title="步骤 2 / 6 · 描述变更需求" variant="outlined">
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Input.TextArea
          rows={4}
          placeholder="用自然语言描述你想做的变更…"
          value={state.naturalLanguageInput}
          onChange={(e) => dispatch({ type: 'SET_NL', text: e.target.value })}
        />

        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Text type="secondary">示例（点击填入）：</Text>
          {examples.map((ex) => (
            <Typography.Link
              key={ex}
              onClick={() => dispatch({ type: 'SET_NL', text: ex })}
              style={{ fontSize: 13 }}
            >
              · {ex}
            </Typography.Link>
          ))}
        </Space>

        <Space size="middle">
          <Text>AI 引擎：</Text>
          <Segmented<AIProvider>
            value={state.aiProvider}
            onChange={(v) => dispatch({ type: 'SET_PROVIDER', provider: v })}
            options={[
              { label: '规则引擎', value: 'deterministic' },
              { label: 'Ollama', value: 'ollama' },
              { label: 'Cloud API', value: 'cloud' },
            ]}
          />
          <Text type="secondary" style={{ fontSize: 11 }}>（默认来自设置页，可临时切换）</Text>
          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={handleParse}
            loading={parsing}
          >
            {parsing ? '解析中…' : '解析需求'}
          </Button>
        </Space>

        {spec && (
          <>
            <Alert
              type="success"
              showIcon
              message="已解析出 Change Spec，可在下方预览并微调；下一步将与站点能力做冲突校验"
            />
            <div>
              {spec.changes.map((item, i) => (
                <ChangeItemCard key={i} item={item}
                  onEdit={(updated) => {
                    const changes = spec.changes.map((c, j) => j === i ? updated : c);
                    dispatch({ type: 'SET_CHANGE_SPEC', spec: { ...spec, changes } });
                  }}
                  onDelete={() => {
                    const changes = spec.changes.filter((_, j) => j !== i);
                    dispatch({ type: 'SET_CHANGE_SPEC', spec: { ...spec, changes } });
                  }}
                />
              ))}
            </div>
          </>
        )}
      </Space>
    </Card>
  );
}
