import { useEffect } from 'react';
import { Alert, Button, Card, Input, Segmented, Space, Typography } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { mockChangeSpec } from '@/mocks/data';
import ChangeItemCard from './ChangeItemCard';
import type { AIProvider } from '@/core/types/domain';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

const examples = [
  '为 AnalysisRequest 添加一个名为 maitux_sample_code 的字符串字段，并在 Sample 列表视图中显示该字段',
  '让 Analyst 角色可以在 Client 下添加 Department',
  '为 Supplier 添加一个必填的联系电话字段',
];

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepDescribeChange({ state, dispatch }: Props) {
  const spec = state.changeSpec;

  // 接住「权限工具 → 带到工坊」预填的需求
  useEffect(() => {
    const prefill = localStorage.getItem('aiconfigtool.studioPrefill');
    if (prefill && !state.naturalLanguageInput) {
      dispatch({ type: 'SET_NL', text: prefill });
      localStorage.removeItem('aiconfigtool.studioPrefill');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleParse = () => {
    // mock：产出预置 change_spec（真实为调用 AI 引擎解析）
    dispatch({ type: 'SET_CHANGE_SPEC', spec: mockChangeSpec });
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
          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={handleParse}
          >
            解析需求
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
                <ChangeItemCard key={i} item={item} />
              ))}
            </div>
          </>
        )}
      </Space>
    </Card>
  );
}
