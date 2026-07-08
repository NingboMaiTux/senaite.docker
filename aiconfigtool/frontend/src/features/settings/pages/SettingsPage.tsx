import {
  Button,
  Card,
  Divider,
  Form,
  Input,
  InputNumber,
  Radio,
  Select,
  Slider,
  Space,
  Switch,
  Typography,
} from 'antd';

const { Title, Paragraph } = Typography;

export default function SettingsPage() {
  return (
    <div style={{ maxWidth: 720 }}>
      <Title level={4} style={{ marginTop: 0 }}>
        ⚙️ 设置
      </Title>
      <Paragraph type="secondary">
        全局工作空间配置。站点级 / 项目级配置可继承并覆盖这里的默认值。
      </Paragraph>

      <Card title="AI 提供商">
        <Form layout="vertical">
          <Form.Item label="默认引擎">
            <Radio.Group defaultValue="ollama">
              <Radio.Button value="deterministic">规则引擎</Radio.Button>
              <Radio.Button value="ollama">Ollama</Radio.Button>
              <Radio.Button value="cloud">Cloud API</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item label="Ollama 模型">
            <Select
              defaultValue="deepseek-r1:8b"
              style={{ width: 240 }}
              options={[
                { value: 'deepseek-r1:8b', label: 'deepseek-r1:8b' },
                { value: 'qwen2.5:14b', label: 'qwen2.5:14b' },
                { value: 'llama3.1:8b', label: 'llama3.1:8b' },
              ]}
            />
          </Form.Item>
          <Form.Item label="Ollama API 地址">
            <Input
              defaultValue="http://127.0.0.1:11434"
              style={{ width: 320 }}
            />
          </Form.Item>
          <Form.Item label="Temperature">
            <Slider
              min={0}
              max={1}
              step={0.1}
              defaultValue={0.1}
              style={{ width: 240 }}
            />
          </Form.Item>
          <Form.Item label="Max Tokens">
            <InputNumber defaultValue={4096} style={{ width: 160 }} />
          </Form.Item>
        </Form>
      </Card>

      <Divider />

      <Card title="交付偏好">
        <Form layout="vertical">
          <Form.Item label="默认交付模式">
            <Radio.Group defaultValue="package_export">
              <Radio value="manual_copy">manual_copy（输出到目录）</Radio>
              <Radio value="package_export">package_export（打包 ZIP）</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item label="自动生成部署文档">
            <Switch defaultChecked />
          </Form.Item>
          <Form.Item label="输出目录">
            <Input defaultValue="./output" style={{ width: 320 }} />
          </Form.Item>
        </Form>
      </Card>

      <Divider />

      <Card title="Inventory">
        <Form layout="vertical">
          <Form.Item label="快照有效期（小时）">
            <InputNumber defaultValue={24} style={{ width: 160 }} />
          </Form.Item>
          <Form.Item label="到期自动提醒">
            <Switch defaultChecked />
          </Form.Item>
        </Form>
      </Card>

      <div style={{ marginTop: 24 }}>
        <Space>
          <Button type="primary">保存配置</Button>
          <Button>恢复默认</Button>
        </Space>
      </div>
    </div>
  );
}
