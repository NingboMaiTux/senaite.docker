import { useState } from 'react';
import {
  App,
  Button,
  Card,
  Col,
  Divider,
  Input,
  List,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import {
  BulbOutlined,
  SwapOutlined,
  ExperimentOutlined,
  CheckCircleTwoTone,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';

const { Title, Paragraph, Text } = Typography;

// 权限推荐结果（mock）：一个自然语言请求 → 拆出的权限组合
const mockBundle = [
  { perm: 'senaite.core: Access contents information', scope: 'Client 容器', why: '进入容器查看' },
  { perm: 'Add portal content', scope: 'Client 容器', why: '在容器内新增' },
  { perm: 'senaite.core: Add Department', scope: '内容类型 Department', why: '创建目标类型' },
];

const roles = ['Analyst', 'LabManager', 'LabClerk', 'Client', 'Owner'];

export default function PermissionsPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();

  // 权限推荐
  const [nl, setNl] = useState('让 Analyst 可以在 Client 下添加 Department');
  const [recommended, setRecommended] = useState(false);

  // 角色对比
  const [roleA, setRoleA] = useState('Analyst');
  const [roleB, setRoleB] = useState('LabManager');
  const [compared, setCompared] = useState(false);

  const toStudio = () => {
    // 把咨询结论作为需求带到 Addon 工坊，走正规流水线生成
    localStorage.setItem('aiconfigtool.studioPrefill', nl);
    message.success('已带到 Addon 工坊，请在工坊内选站点并生成');
    navigate('/studio');
  };

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>
        🔐 权限工具（咨询）
      </Title>
      <Paragraph type="secondary">
        帮你想清楚「要改哪些权限」。这里只做分析（权限推荐、角色对比），
        <Text strong>不直接生成 Addon</Text>；确认要改的内容后，一键带到 Addon 工坊，
        走摸底 → 冲突校验 → 生成的正规流水线产出权限 Addon。
      </Paragraph>

      <Row gutter={16}>
        {/* 权限推荐 */}
        <Col span={12}>
          <Card
            title={
              <Space>
                <BulbOutlined /> 权限推荐
              </Space>
            }
            style={{ height: '100%' }}
          >
            <Text type="secondary">
              描述目标角色和资源，推荐所需的权限组合。
            </Text>
            <Input.TextArea
              rows={3}
              value={nl}
              onChange={(e) => {
                setNl(e.target.value);
                setRecommended(false);
              }}
              style={{ margin: '12px 0' }}
            />
            <Button
              type="primary"
              icon={<BulbOutlined />}
              onClick={() => setRecommended(true)}
            >
              获取推荐
            </Button>

            {recommended && (
              <>
                <Divider style={{ margin: '16px 0' }} titlePlacement="start">
                  推荐的权限组合（permission bundle）
                </Divider>
                <List
                  size="small"
                  dataSource={mockBundle}
                  renderItem={(b) => (
                    <List.Item>
                      <Space align="start">
                        <CheckCircleTwoTone twoToneColor="#52c41a" />
                        <Space direction="vertical" size={0}>
                          <Text strong style={{ fontSize: 13 }}>
                            {b.perm}
                          </Text>
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            作用域：{b.scope} · {b.why}
                          </Text>
                        </Space>
                      </Space>
                    </List.Item>
                  )}
                />
                <Button
                  type="primary"
                  ghost
                  block
                  icon={<ExperimentOutlined />}
                  style={{ marginTop: 12 }}
                  onClick={toStudio}
                >
                  带到 Addon 工坊生成
                </Button>
              </>
            )}
          </Card>
        </Col>

        {/* 角色对比 */}
        <Col span={12}>
          <Card
            title={
              <Space>
                <SwapOutlined /> 角色对比
              </Space>
            }
            style={{ height: '100%' }}
          >
            <Text type="secondary">对比两个角色的权限差异，辅助判断该给谁加什么。</Text>
            <Space style={{ margin: '12px 0' }} wrap>
              <Select
                style={{ width: 140 }}
                value={roleA}
                onChange={(v) => {
                  setRoleA(v);
                  setCompared(false);
                }}
                options={roles.map((r) => ({ value: r, label: r }))}
              />
              <SwapOutlined />
              <Select
                style={{ width: 140 }}
                value={roleB}
                onChange={(v) => {
                  setRoleB(v);
                  setCompared(false);
                }}
                options={roles.map((r) => ({ value: r, label: r }))}
              />
              <Button onClick={() => setCompared(true)}>开始对比</Button>
            </Space>

            {compared && (
              <>
                <Divider style={{ margin: '16px 0' }} titlePlacement="start">
                  {roleA} vs {roleB}
                </Divider>
                <List
                  size="small"
                  dataSource={[
                    { perm: 'Add Department', a: false, b: true },
                    { perm: 'Modify portal content', a: false, b: true },
                    { perm: 'Access contents information', a: true, b: true },
                  ]}
                  renderItem={(d) => (
                    <List.Item>
                      <Text style={{ fontSize: 13 }}>{d.perm}</Text>
                      <Space>
                        <Tag color={d.a ? 'green' : 'default'}>
                          {roleA}: {d.a ? '有' : '无'}
                        </Tag>
                        <Tag color={d.b ? 'green' : 'default'}>
                          {roleB}: {d.b ? '有' : '无'}
                        </Tag>
                      </Space>
                    </List.Item>
                  )}
                />
              </>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
