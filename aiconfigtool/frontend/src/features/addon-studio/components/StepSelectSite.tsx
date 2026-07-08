import { useMemo } from 'react';
import {
  Alert,
  Card,
  Checkbox,
  Descriptions,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { LinkOutlined } from '@ant-design/icons';
import { mockSites, mockInventories } from '@/mocks/data';
import { useWorkspace } from '@/core/context/WorkspaceContext';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepSelectSite({ state, dispatch }: Props) {
  const { currentCompanyCode } = useWorkspace();
  // 只列出可摸底的站点（摸底站 / 摸底+测试）
  const sites = mockSites.filter(
    (s) =>
      s.companyCode === currentCompanyCode &&
      (s.usage === 'inventory' || s.usage === 'both'),
  );
  const site = mockSites.find((s) => s.code === state.siteCode);

  // 该站点的历史摸底文件（取消自动摸底时可选）
  const siteSnapshots = useMemo(
    () => mockInventories.filter((s) => s.siteCode === state.siteCode),
    [state.siteCode],
  );

  return (
    <Card title="步骤 1 / 6 · 选择摸底站点" variant="outlined">
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Space size="middle" wrap>
          <Text>摸底站点：</Text>
          <Select
            value={state.siteCode ?? undefined}
            style={{ width: 380 }}
            placeholder="选择要摸底的站点"
            onChange={(v) => {
              dispatch({ type: 'SET_SITE', siteCode: v });
              dispatch({ type: 'SET_INVENTORY_REF', ref: null });
            }}
            options={sites.map((s) => ({
              value: s.code,
              label: `${s.name}（${s.url}）`,
            }))}
          />
        </Space>

        {site && (
          <Descriptions
            bordered
            size="small"
            column={2}
            items={[
              {
                key: '1',
                label: '站点 URL',
                children: (
                  <Space size={4}>
                    <LinkOutlined />
                    {site.url}
                  </Space>
                ),
              },
              { key: '2', label: 'Senaite 版本', children: site.senaiteVersion },
              { key: '3', label: '上次摸底', children: site.lastInventoryAt ?? '从未' },
              {
                key: '4',
                label: '状态',
                children:
                  site.status === 'online' ? (
                    <Tag color="success">在线</Tag>
                  ) : (
                    <Tag>未知</Tag>
                  ),
              },
            ]}
          />
        )}

        {/* 自动摸底勾选 */}
        <div>
          <Checkbox
            checked={state.autoInventory}
            onChange={(e) =>
              dispatch({ type: 'SET_AUTO_INVENTORY', value: e.target.checked })
            }
          >
            自动摸底（推荐）
          </Checkbox>
          <div style={{ marginTop: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              勾选后进入下一步会自动对该站点摸一次最新能力；取消勾选可复用历史摸底文件。
            </Text>
          </div>
        </div>

        {/* 取消自动摸底 → 手动选摸底文件 */}
        {!state.autoInventory && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text>选择摸底文件：</Text>
            {siteSnapshots.length === 0 ? (
              <Alert
                type="warning"
                showIcon
                message="该站点还没有历史摸底文件，请勾选自动摸底，或先到「能力摸底」页扫描一次"
              />
            ) : (
              <Select
                style={{ width: '100%', maxWidth: 480 }}
                placeholder="选择该站点的历史摸底文件"
                value={state.inventoryRef ?? undefined}
                onChange={(v) => dispatch({ type: 'SET_INVENTORY_REF', ref: v })}
                options={siteSnapshots.map((s) => ({
                  value: s.id,
                  label: `${s.createdAt} · ${s.staleness === 'fresh' ? '新鲜' : '已过期'} · ${s.entityCount} 实体`,
                }))}
              />
            )}
          </Space>
        )}
      </Space>
    </Card>
  );
}
