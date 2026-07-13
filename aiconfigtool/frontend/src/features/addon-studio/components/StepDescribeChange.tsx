import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Input, Space, Tag, Typography } from 'antd';
import { ClearOutlined, SearchOutlined } from '@ant-design/icons';
import { apiClient } from '@/core/services/apiClient';
import { addonStudioApi } from '../services/addonStudioApi';
import ChangeItemCard from './ChangeItemCard';
import type { AIProvider } from '@/core/types/domain';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Paragraph, Text } = Typography;

const quickTemplates = [
  {
    key: 'field',
    label: '插入字段模板',
    value: '为 [] 对象添加一个名为 [] 的字段，该字段[可选]',
  },
  {
    key: 'permission',
    label: '插入权限模板',
    value: '给 [] 角色添加创建 [] 的权限',
  },
];

type DemandKind = 'field' | 'permission' | 'mixed' | 'unknown' | 'empty';

const detectLineKind = (line: string): Exclude<DemandKind, 'mixed' | 'empty'> => {
  const text = line.trim();
  if (!text) return 'unknown';
  if (text.includes('权限') || text.includes('角色')) return 'permission';
  if (text.includes('字段')) return 'field';
  return 'unknown';
};

const analyzeDemandKind = (text: string): DemandKind => {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!lines.length) return 'empty';
  const kinds = new Set(lines.map(detectLineKind).filter((kind) => kind !== 'unknown'));
  if (kinds.has('field') && kinds.has('permission')) return 'mixed';
  if (kinds.has('field')) return 'field';
  if (kinds.has('permission')) return 'permission';
  return 'unknown';
};

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepDescribeChange({ state, dispatch }: Props) {
  const { message } = App.useApp();
  const spec = state.changeSpec;
  const [parsing, setParsing] = useState(false);
  const currentDemandKind = analyzeDemandKind(state.naturalLanguageInput);

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

  const appendTemplate = (text: string) => {
    const templateKind = detectLineKind(text);
    if (
      currentDemandKind !== 'empty' &&
      currentDemandKind !== 'unknown' &&
      currentDemandKind !== templateKind
    ) {
      message.warning('一个 Addon 只能是一类需求：字段或权限，不能混在一起');
      return;
    }
    const current = state.naturalLanguageInput.trim();
    dispatch({ type: 'SET_NL', text: current ? `${current}\n${text}` : text });
  };

  const handleParse = async () => {
    if (!state.naturalLanguageInput.trim()) {
      message.warning('请输入需求描述');
      return;
    }
    if (!state.siteCode) {
      message.warning('请先在步骤1选择摸底站点');
      return;
    }
    if (currentDemandKind === 'mixed') {
      message.warning('一个 Addon 不能同时包含字段和权限，请拆成两个 Addon');
      return;
    }
    setParsing(true);
    try {
      const result = await addonStudioApi.parseRequirement({
        siteCode: state.siteCode,
        inventoryRef: state.inventoryRef || `inv_${state.siteCode}`,
        text: state.naturalLanguageInput,
        aiProvider: state.aiProvider,
      });
      dispatch({ type: 'SET_CHANGE_SPEC', spec: result });
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      if (msg.includes('CHANGE_SPEC_INVALID')) {
        message.warning('AI 无法解析，请按模板稍微改一下再试');
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

        <Card size="small" title="快速开始">
          <Space wrap>
            {quickTemplates.map((item) => (
              <Button
                key={item.key}
                onClick={() => appendTemplate(item.value)}
                disabled={
                  (item.key === 'field' && currentDemandKind === 'permission') ||
                  (item.key === 'permission' && currentDemandKind === 'field')
                }
              >
                {item.label}
              </Button>
            ))}
            <Button
              icon={<ClearOutlined />}
              onClick={() => dispatch({ type: 'SET_NL', text: '' })}
              disabled={!state.naturalLanguageInput.trim()}
            >
              清空
            </Button>
          </Space>
          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            当前需求类型：
            <Tag
              color={
                currentDemandKind === 'field'
                  ? 'blue'
                  : currentDemandKind === 'permission'
                    ? 'gold'
                    : currentDemandKind === 'mixed'
                      ? 'red'
                      : 'default'
              }
              style={{ marginInlineStart: 8 }}
            >
              {currentDemandKind === 'field'
                ? '字段'
                : currentDemandKind === 'permission'
                  ? '权限'
                  : currentDemandKind === 'mixed'
                    ? '混合，需拆分'
                    : currentDemandKind === 'empty'
                      ? '未填写'
                      : '未识别'}
            </Tag>
          </Paragraph>
        </Card>

        <Input.TextArea
          rows={6}
          placeholder="为 [样品] 对象添加一个名为 [地域] 的字段，该字段[可选]"
          value={state.naturalLanguageInput}
          onChange={(e) => dispatch({ type: 'SET_NL', text: e.target.value })}
        />


        <Space size="middle">
          <Text type="secondary" style={{ fontSize: 12 }}>
            需求可写多行；后端会按行拆成多条变更
          </Text>
          <Button
            type="primary"
            icon={<SearchOutlined />}
            onClick={handleParse}
            loading={parsing}
          >
            {parsing ? '解析中…' : '解析需求'}
          </Button>
        </Space>

        <Alert
          type="info"
          showIcon
          message="对象名按当前站点摸底结果解析"
          description="你可以写业务名称，如“样品”“工作表”“供货商”。如果站点运行时的技术类型名与界面显示名不同，系统会优先按当前站点真实可安装对象生成，并在解析结果里显示对应说明。"
        />

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
