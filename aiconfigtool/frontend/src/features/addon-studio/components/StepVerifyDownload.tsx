import { useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Divider,
  Result,
  Select,
  Space,
  Steps,
  Tag,
  Typography,
} from 'antd';
import {
  DownloadOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  LinkOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { apiClient } from '@/core/services/apiClient';
import { useWorkspace } from '@/core/context/WorkspaceContext';
import { workspaceApi } from '@/features/workspace/services/workspaceApi';
import type { Site } from '@/core/types/domain';
import type { WorkflowAction, WorkflowState } from '../hooks/useAddonWorkflow';

const { Text } = Typography;

interface Props {
  state: WorkflowState;
  dispatch: React.Dispatch<WorkflowAction>;
}

export default function StepVerifyDownload({ state, dispatch }: Props) {
  const { message } = App.useApp();
  const { currentCompanyCode } = useWorkspace();
  const [verifying, setVerifying] = useState(false);
  const [cleaningUp, setCleaningUp] = useState(false);
  const [testSites, setTestSites] = useState<Site[]>([]);

  useEffect(() => {
    if (!currentCompanyCode) return;
    workspaceApi.getSites(currentCompanyCode).then((list) => {
      setTestSites(list.filter((s) => s.usage === 'test' || s.usage === 'both'));
    });
  }, [currentCompanyCode]);

  const meta = state.addonMeta;
  const fullName = meta ? `${meta.namespace}.${meta.functionName}` : 'addon';
  const pkgName = `${fullName}-${meta?.version ?? '1.0.0'}.zip`;

  const runVerify = async () => {
    if (!state.testSiteCode) { message.warning('请选择测试站点'); return; }
    if (!state.siteCode || !meta) { message.warning('前置信息不完整'); return; }
    setVerifying(true);
    dispatch({ type: 'SET_VERIFY_STATUS', status: 'running' });
    try {
      const r = await apiClient.post<{ verified: boolean; steps: { step: string; ok: boolean; message?: string }[] }>(
        '/addon-studio/install-verify', {
          fullName: `${meta.namespace}.${meta.functionName}`,
          version: meta.version,
          siteCode: state.siteCode,
          testSiteCode: state.testSiteCode,
        });
      if (r.verified) {
        dispatch({ type: 'SET_VERIFY_STATUS', status: 'passed' });
        message.success('安装验证通过！字段已在测试站点生效');
      } else {
        dispatch({ type: 'SET_VERIFY_STATUS', status: 'failed' });
        message.error('验证未通过，请查看详情');
      }
    } catch (err) {
      dispatch({ type: 'SET_VERIFY_STATUS', status: 'failed' });
      message.error('安装验证失败：' + ((err as Error).message || ''));
    } finally { setVerifying(false); }
  };

  return (
    <Card title="步骤 6 / 6 · 测试验证（可选）与下载" variant="outlined">
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* 测试验证 */}
        <div>
          <Space align="center">
            <ExperimentOutlined />
            <Text strong>在测试站点安装验证</Text>
            <Tag>可选</Tag>
          </Space>
          <Alert
            style={{ margin: '12px 0' }}
            type="info"
            showIcon
            message="测试站点与摸底站点分开选择。可先装到测试站验证通过，再下载交付；也可跳过直接下载。"
          />
          <Space wrap>
            <Text>测试站点：</Text>
            <Select
              style={{ width: 360 }}
              placeholder="选择测试站点"
              value={state.testSiteCode ?? undefined}
              onChange={(v) => dispatch({ type: 'SET_TEST_SITE', siteCode: v })}
              options={testSites.map((s) => ({
                value: s.code,
                label: `${s.name}（${s.url}）`,
              }))}
            />
            <Button
              type="primary"
              ghost
              icon={<ExperimentOutlined />}
              loading={verifying}
              disabled={!state.testSiteCode}
              onClick={runVerify}
            >
              安装并验证
            </Button>
          </Space>

          {state.verifyStatus === 'passed' && (
            <div style={{ marginTop: 12 }}>
              <Steps
                size="small"
                current={4}
                status="finish"
                items={[
                  { title: '上传' },
                  { title: '安装' },
                  { title: '重启' },
                  { title: '检查字段' },
                  { title: '验证通过' },
                ]}
              />
            </div>
          )}
        </div>

        <Divider style={{ margin: 0 }} />

        {/* 下载 */}
        <Result
          status="success"
          title="Addon 已就绪，可下载交付"
          subTitle={
            <Space direction="vertical" size={4}>
              <Space size={4}>
                <LinkOutlined />
                <Text code>{pkgName}</Text>
                {state.packageSizeKb > 0 && <Text type="secondary">· {state.packageSizeKb} KB</Text>}
                <Text type="secondary">· 含实施部署指南</Text>
              </Space>
              {state.verifyStatus === 'passed' ? (
                <Tag color="success">已通过测试站点验证</Tag>
              ) : (
                <Tag color="error">未验证——建议先安装验证再交付</Tag>
              )}
            </Space>
          }
          extra={[
            <Button
              type="primary"
              key="pkg"
              icon={<DownloadOutlined />}
              href={state.packageId ? `/api/addon-studio/download/${state.packageId}` : '#'}
              target="_blank"
              disabled={!state.packageId}
              title={state.packageId ? `下载 ${state.packageId}.zip (${state.packageSizeKb}KB)` : ''}
            >
              {state.packageId ? `下载 Addon 包 · ${state.packageSizeKb}KB` : '下载 Addon 包'}
            </Button>,
            <Button
              key="doc"
              icon={<FileTextOutlined />}
              href={state.packageId ? `/api/addon-studio/deploy-doc/${state.packageId}` : '#'}
              target="_blank"
              disabled={!state.packageId}
            >
              部署指南
            </Button>,
            state.verifyStatus === 'passed' && state.testSiteCode && meta && (
              <Button
                key="cleanup"
                danger
                icon={<DeleteOutlined />}
                loading={cleaningUp}
                onClick={async () => {
                  setCleaningUp(true);
                  try {
                    await apiClient.post('/addon-studio/cleanup', {
                      addonName: `${meta.namespace}.${meta.functionName}`,
                      siteCode: state.testSiteCode,
                    });
                    message.success('Addon 已从测试站点彻底移除');
                    dispatch({ type: 'SET_VERIFY_STATUS', status: 'idle' });
                  } catch { message.error('清理失败'); }
                  finally { setCleaningUp(false); }
                }}
              >
                清理 Addon
              </Button>
            ),
          ]}
        />
      </Space>
    </Card>
  );
}
