import { useEffect } from 'react';
import {
  Alert,
  Button,
  Card,
  Empty,
  List,
  Space,
  Tag,
  Typography,
} from 'antd';
import {
  CheckCircleTwoTone,
  CloseCircleTwoTone,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { mockConflictChecks, mockInventories } from '@/mocks/data';
import type { ConflictCheckItem } from '@/core/types/domain';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepConflictCheck({ state, dispatch }: Props) {
  const spec = state.changeSpec;

  // 进入本步：拿需求 vs 摸底能力做比对（mock）
  useEffect(() => {
    if (!spec) return;
    if (state.conflictChecks.length > 0) return;
    const checks: ConflictCheckItem[] = mockConflictChecks;
    const passed = checks.every((c) => c.status === 'ok');
    dispatch({ type: 'SET_CONFLICT', checks, passed });
  }, [spec, state.conflictChecks.length, dispatch]);

  const runCheck = () => {
    const checks = mockConflictChecks;
    const passed = checks.every((c) => c.status === 'ok');
    dispatch({ type: 'SET_CONFLICT', checks, passed });
  };

  // 用于展示"拿哪份摸底比对的"
  const usedInv = state.autoInventory
    ? mockInventories.find((s) => s.siteCode === state.siteCode)
    : mockInventories.find((s) => s.id === state.inventoryRef);

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
      extra={
        <Button
          size="small"
          icon={<SafetyCertificateOutlined />}
          onClick={runCheck}
        >
          重新校验
        </Button>
      }
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        {usedInv && (
          <Alert
            type="info"
            showIcon
            message={
              <Space size={4} wrap>
                <span>比对基准：</span>
                <Tag color="blue">{usedInv.companyName}</Tag>
                <Text strong>{usedInv.siteName}</Text>
                <Text type="secondary">{usedInv.siteUrl}</Text>
                <span>·</span>
                <span>{usedInv.createdAt}</span>
                {state.autoInventory && <Tag color="green">自动摸底</Tag>}
              </Space>
            }
          />
        )}

        <List
          bordered
          dataSource={state.conflictChecks}
          renderItem={(c) => (
            <List.Item>
              <Space align="start">
                {c.status === 'ok' ? (
                  <CheckCircleTwoTone twoToneColor="#52c41a" />
                ) : (
                  <CloseCircleTwoTone twoToneColor="#ff4d4f" />
                )}
                <Space direction="vertical" size={0}>
                  <Space size={4}>
                    <Tag>{c.changeType}</Tag>
                    <Text strong>{c.target}</Text>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    {c.message}
                  </Text>
                </Space>
              </Space>
            </List.Item>
          )}
        />

        {state.conflictPassed ? (
          <Alert
            type="success"
            showIcon
            message="校验通过：需求与站点当前能力无冲突，可继续生成 Addon"
          />
        ) : (
          <Alert
            type="error"
            showIcon
            message="存在冲突：请返回上一步调整需求，冲突解决前无法进入生成"
          />
        )}
      </Space>
    </Card>
  );
}
