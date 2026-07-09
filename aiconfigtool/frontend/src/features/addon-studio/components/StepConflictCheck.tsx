import { useEffect, useState } from 'react';
import {
  Alert, App, Button, Card, Empty, List, Space, Spin, Tag, Typography,
} from 'antd';
import { CheckCircleTwoTone, CloseCircleTwoTone, SafetyCertificateOutlined } from '@ant-design/icons';
import { workspaceApi } from '@/features/workspace/services/workspaceApi';
import { addonStudioApi } from '../services/addonStudioApi';
import type { ConflictCheckItem, InventorySnapshot } from '@/core/types/domain';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepConflictCheck({ state, dispatch }: Props) {
  const { message } = App.useApp();
  const spec = state.changeSpec;
  const [checking, setChecking] = useState(false);
  const [usedInv, setUsedInv] = useState<InventorySnapshot | null>(null);

  // 加载比对基准（摸底文件元信息）
  useEffect(() => {
    if (!state.siteCode) return;
    workspaceApi.getInventories(state.siteCode).then((list) => {
      if (state.autoInventory && list.length > 0) {
        setUsedInv(list[list.length - 1]);
      } else if (state.inventoryRef) {
        setUsedInv(list.find((i) => i.id === state.inventoryRef) ?? null);
      }
    });
  }, [state.siteCode, state.autoInventory, state.inventoryRef]);

  const runCheck = async () => {
    if (!spec) return;
    setChecking(true);
    try {
      const result = await addonStudioApi.conflictCheck({
        siteCode: state.siteCode!,
        inventoryRef: state.inventoryRef || `inv_${state.siteCode}`,
        changes: spec.changes,
      });
      dispatch({
        type: 'SET_CONFLICT',
        checks: result.checks as ConflictCheckItem[],
        passed: result.passed,
      });
    } catch (err) {
      message.error('冲突校验失败：' + ((err as Error).message || '请确认后端已启动'));
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    if (!spec) return;
    if (state.conflictChecks.length > 0) return;
    runCheck();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec]);

  if (!spec) {
    return (
      <Card title="步骤 3 / 6 · 冲突校验" variant="outlined">
        <Empty description="尚未生成 Change Spec，请返回上一步解析需求" />
      </Card>
    );
  }

  return (
    <Card
      title="步骤 3 / 6 · 冲突校验（需求 vs 站点能力）"
      variant="outlined"
      extra={<Button size="small" icon={<SafetyCertificateOutlined />} onClick={runCheck} loading={checking}>重新校验</Button>}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {usedInv && (
          <Alert type="info" showIcon
            message={
              <Space size={4} wrap>
                <span>比对基准：</span><Tag color="blue">{usedInv.companyName}</Tag>
                <Text strong>{usedInv.siteName}</Text>
                <Text type="secondary">{usedInv.siteUrl}</Text>
                <span>·</span><span>{usedInv.createdAt}</span>
                {state.autoInventory && <Tag color="green">自动摸底</Tag>}
              </Space>
            } />
        )}

        {checking && (
          <Space style={{ width: '100%', justifyContent: 'center', padding: 20 }}>
            <Spin /><Text type="secondary">正在与站点摸底数据逐项比对…</Text>
          </Space>
        )}

        {!checking && state.conflictChecks.length > 0 && (
          <>
            <List bordered dataSource={state.conflictChecks}
              renderItem={(c) => (
                <List.Item>
                  <Space align="start">
                    {c.status === 'ok' ? <CheckCircleTwoTone twoToneColor="#52c41a" /> : <CloseCircleTwoTone twoToneColor="#ff4d4f" />}
                    <Space direction="vertical" size={0}>
                      <Space size={4}><Tag>{c.changeType}</Tag><Text strong>{c.target}</Text></Space>
                      <Text type="secondary" style={{ fontSize: 13 }}>{c.message}</Text>
                    </Space>
                  </Space>
                </List.Item>
              )} />
            {state.conflictPassed
              ? <Alert type="success" showIcon message="校验通过：需求与站点当前能力无冲突，可继续生成 Addon" />
              : <Alert type="error" showIcon message="存在冲突：请返回上一步调整需求，冲突解决前无法进入生成" />}
          </>
        )}
      </Space>
    </Card>
  );
}
