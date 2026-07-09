import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Card,
  Checkbox,
  Descriptions,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { LinkOutlined } from '@ant-design/icons';
import { useWorkspace } from '@/core/context/WorkspaceContext';
import { workspaceApi } from '@/features/workspace/services/workspaceApi';
import type { Site, InventorySnapshot } from '@/core/types/domain';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepSelectSite({ state, dispatch }: Props) {
  const { currentCompanyCode } = useWorkspace();
  const [sites, setSites] = useState<Site[]>([]);
  const [loading, setLoading] = useState(false);
  const [snapshots, setSnapshots] = useState<InventorySnapshot[]>([]);
  const [connStatus, setConnStatus] = useState<'idle' | 'testing' | 'online' | 'offline'>('idle');

  useEffect(() => {
    if (!currentCompanyCode) return;
    setLoading(true);
    workspaceApi.getSites(currentCompanyCode).then(s => { setSites(s); setLoading(false); });
  }, [currentCompanyCode]);

  const scanSites = useMemo(
    () => sites.filter(s => s.usage === 'inventory' || s.usage === 'both'),
    [sites],
  );

  const site = sites.find(s => s.code === state.siteCode);

  // 选中站点后自动测连通 + 加载摸底文件
  useEffect(() => {
    if (!state.siteCode) { setSnapshots([]); setConnStatus('idle'); return; }
    // 测连通
    setConnStatus('testing');
    workspaceApi.testConnection(state.siteCode)
      .then(r => setConnStatus(r.reachable ? 'online' : 'offline'))
      .catch(() => setConnStatus('offline'));
    // 加载摸底文件
    workspaceApi.getInventories(state.siteCode).then(setSnapshots);
  }, [state.siteCode]);

  // 默认自动摸底：有摸底文件则选最新的
  useEffect(() => {
    if (state.autoInventory && snapshots.length > 0 && !state.inventoryRef) {
      dispatch({ type: 'SET_INVENTORY_REF', ref: snapshots[snapshots.length - 1].id });
    }
  }, [snapshots, state.autoInventory, state.inventoryRef, dispatch]);

  return (
    <Card title="步骤 1 / 6 · 选择摸底站点" variant="outlined">
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Space size="middle" wrap>
          <Text>摸底站点：</Text>
          <Select
            value={state.siteCode ?? undefined}
            style={{ width: 400 }}
            loading={loading}
            placeholder="选择要摸底的站点"
            notFoundContent={loading ? <Spin size="small" /> : '该公司下暂无站点'}
            onChange={(v) => {
              dispatch({ type: 'SET_SITE', siteCode: v });
              dispatch({ type: 'SET_INVENTORY_REF', ref: null });
            }}
            options={scanSites.map(s => ({ value: s.code, label: `${s.name}（${s.url}）` }))}
          />
        </Space>

        {site && (
          <Descriptions bordered size="small" column={2} items={[
            { key: '1', label: '站点 URL', children: <Space size={4}><LinkOutlined />{site.url}</Space> },
            { key: '2', label: '版本', children: site.senaiteVersion },
            { key: '3', label: '上次摸底', children: site.lastInventoryAt ?? '从未' },
            { key: '4', label: '连通', children:
              connStatus === 'idle' ? <Tag>—</Tag> :
              connStatus === 'testing' ? <Tag color="processing">测试中…</Tag> :
              connStatus === 'online' ? <Tag color="success">在线</Tag> :
              <Tag color="error">离线</Tag> },
          ]} />
        )}

        <div>
          <Checkbox checked={state.autoInventory} onChange={e => dispatch({ type: 'SET_AUTO_INVENTORY', value: e.target.checked })}>
            自动摸底（推荐）
          </Checkbox>
          <div style={{ marginTop: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>勾选后自动选择该站点最新的摸底文件；取消勾选可手动选择。</Text>
          </div>
        </div>

        {!state.autoInventory && (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text>选择摸底文件：</Text>
            {snapshots.length === 0 ? (
              <Alert type="warning" showIcon message="该站点还没有摸底文件，请勾选自动摸底，或先到「能力摸底」页扫描" />
            ) : (
              <Select style={{ width: '100%', maxWidth: 480 }} placeholder="选择摸底文件"
                value={state.inventoryRef ?? undefined}
                onChange={v => dispatch({ type: 'SET_INVENTORY_REF', ref: v })}
                options={snapshots.map(s => ({ value: s.id, label: `${s.createdAt} · ${s.staleness === 'fresh' ? '新鲜' : '已过期'} · ${s.entityCount} 实体` }))} />
            )}
          </Space>
        )}
      </Space>
    </Card>
  );
}
