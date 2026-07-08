import { useState } from 'react';
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
  CopyOutlined,
  DownloadOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  LinkOutlined,
} from '@ant-design/icons';
import { mockSites } from '@/mocks/data';
import { useWorkspace } from '@/core/context/WorkspaceContext';
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

  const meta = state.addonMeta;
  const fullName = meta ? `${meta.namespace}.${meta.functionName}` : 'addon';
  const pkgName = `${fullName}-${meta?.version ?? '1.0.0'}.zip`;

  // 测试站点 = 与摸底站点分开选（只列 test / both）
  const testSites = mockSites.filter(
    (s) =>
      s.companyCode === currentCompanyCode &&
      (s.usage === 'test' || s.usage === 'both'),
  );

  const runVerify = () => {
    if (!state.testSiteCode) {
      message.warning('请选择测试站点');
      return;
    }
    setVerifying(true);
    dispatch({ type: 'SET_VERIFY_STATUS', status: 'running' });
    setTimeout(() => {
      setVerifying(false);
      dispatch({ type: 'SET_VERIFY_STATUS', status: 'passed' });
      message.success('测试验证通过');
    }, 1600);
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
                <Text type="secondary">· 34 KB · 含实施部署指南</Text>
              </Space>
              {state.verifyStatus === 'passed' ? (
                <Tag color="success">已通过测试站点验证</Tag>
              ) : (
                <Tag color="default">未验证（可选步骤，不影响下载）</Tag>
              )}
            </Space>
          }
          extra={[
            <Button
              type="primary"
              key="pkg"
              icon={<DownloadOutlined />}
              onClick={() => message.success('（演示）下载 Addon 包')}
            >
              下载 Addon 包
            </Button>,
            <Button
              key="doc"
              icon={<FileTextOutlined />}
              onClick={() => message.success('（演示）下载部署指南')}
            >
              下载部署指南
            </Button>,
            <Button
              key="cmd"
              icon={<CopyOutlined />}
              onClick={() => message.success('（演示）已复制安装命令')}
            >
              复制安装命令
            </Button>,
          ]}
        />
      </Space>
    </Card>
  );
}
