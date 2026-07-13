import { App, Button, Steps, Typography } from 'antd';
import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { useAddonWorkflow } from '../hooks/useAddonWorkflow';
import StepSelectSite from '../components/StepSelectSite';
import StepDescribeChange from '../components/StepDescribeChange';
import StepConflictCheck from '../components/StepConflictCheck';
import StepConfigureAddon from '../components/StepConfigureAddon';
import StepGenerate from '../components/StepGenerate';
import StepVerifyDownload from '../components/StepVerifyDownload';

const { Title, Paragraph } = Typography;

const steps = [
  '选摸底站点',
  '描述需求',
  '冲突校验',
  '配置元信息',
  '生成',
  '验证/下载',
];

export default function AddonStudioPage() {
  const { message } = App.useApp();
  const { state, dispatch } = useAddonWorkflow();
  const step = state.currentStep;

  const stepNode = [
    <StepSelectSite key="0" state={state} dispatch={dispatch} />,
    <StepDescribeChange key="1" state={state} dispatch={dispatch} />,
    <StepConflictCheck key="2" state={state} dispatch={dispatch} />,
    <StepConfigureAddon key="3" state={state} dispatch={dispatch} />,
    <StepGenerate key="4" state={state} dispatch={dispatch} />,
    <StepVerifyDownload key="5" state={state} dispatch={dispatch} />,
  ][step];

  // 每一步的"下一步"前置条件校验
  const guardNext = (): string | null => {
    switch (step) {
      case 0:
        if (!state.siteCode) return '请先选择摸底站点';
        if (!state.autoInventory && !state.inventoryRef)
          return '取消自动摸底后，请选择一个摸底文件';
        return null;
      case 1:
        if (!state.changeSpec) return '请先点击「解析需求」生成 Change Spec';
        return null;
      case 2:
        if (!state.conflictPassed)
          return '存在冲突，请返回上一步调整需求，冲突解决前无法生成';
        return null;
      case 3:
        if (!state.addonMeta) return '请完善 Addon 元信息';
        return null;
      case 4:
        if (state.generationStatus !== 'success')
          return '请先点击「一键生成 Addon」完成生成';
        return null;
      default:
        return null;
    }
  };

  const handleNext = () => {
    const err = guardNext();
    if (err) {
      message.warning(err);
      return;
    }
    dispatch({ type: 'NEXT' });
  };

  return (
    <div style={{ maxWidth: 920, margin: '0 auto' }}>
      <Title level={4} style={{ marginTop: 0 }}>
        🤖 Addon 工坊
      </Title>
      <Paragraph type="secondary">
        选站点摸底 → 描述需求 → 冲突校验（无冲突才放行）→ 配置 → 生成 → 可选测试验证后下载。
      </Paragraph>

      <Steps
        current={step}
        items={steps.map((t) => ({ title: t }))}
        style={{ margin: '24px 0' }}
        size="small"
      />

      <div style={{ marginBottom: 24 }}>{stepNode}</div>

      <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
        <Button icon={<LeftOutlined />} disabled={step === 0} onClick={() => dispatch({ type: 'PREV' })}>
          上一步
        </Button>
        <Button
          onClick={() => {
            dispatch({ type: 'RESET' });
            localStorage.removeItem('aiconfigtool.workflow');
            message.success('已重置');
          }}
        >
          重新开始
        </Button>
        {step < 5 ? (
          <Button type="primary" onClick={handleNext}>
            下一步 <RightOutlined />
          </Button>
        ) : (
          <Button type="primary" onClick={() => {
            dispatch({ type: 'RESET' });
            localStorage.removeItem('aiconfigtool.workflow');
            message.success('已完成，可开始新任务');
          }}>
            完成，开始新任务
          </Button>
        )}
      </div>
    </div>
  );
}
