import { useState } from 'react';
import { Card, Descriptions, Space, Tag, Button, Modal, Form, Input, Select, Switch, App } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';
import type { ChangeItem } from '@/core/types/domain';

const typeColor: Record<string, string> = {
  AddField: 'blue', UpdateListing: 'cyan', UpdatePermission: 'gold',
  UpdateWorkflow: 'purple', CreateReportTemplateFromDocx: 'magenta',
};

interface Props {
  item: ChangeItem;
  onEdit?: (item: ChangeItem) => void;
  onDelete?: () => void;
}

export default function ChangeItemCard({ item, onEdit, onDelete }: Props) {
  const { message } = App.useApp();
  const [editing, setEditing] = useState(false);
  const [form] = Form.useForm();

  const save = async () => {
    const v = await form.validateFields();
    onEdit?.({ ...item, ...v });
    message.success('已更新');
    setEditing(false);
  };

  return (
    <>
      <Card size="small" style={{ marginBottom: 12 }}
        title={<Space><Tag color={typeColor[item.changeType] ?? 'default'}>{item.changeType}</Tag>{item.framework && <Tag>{item.framework}</Tag>}</Space>}
        extra={
          <Space size={0}>
            <Button type="text" size="small" icon={<EditOutlined />}
              onClick={() => { form.setFieldsValue(item); setEditing(true); }} />
            {onDelete && (
              <Button type="text" size="small" danger icon={<DeleteOutlined />}
                onClick={() => { onDelete(); message.success('已移除'); }} />
            )}
          </Space>
        }
      >
        <Descriptions size="small" column={1} colon>
          {item.typeId && <Descriptions.Item label="目标类型">{item.typeId}</Descriptions.Item>}
          {item.fieldName && <Descriptions.Item label="字段名">{item.fieldName}</Descriptions.Item>}
          {item.fieldType && <Descriptions.Item label="字段类型">{item.fieldType}</Descriptions.Item>}
          {typeof item.required === 'boolean' && <Descriptions.Item label="必填">{item.required ? '是' : '否'}</Descriptions.Item>}
          {item.addColumns && item.addColumns.length > 0 && <Descriptions.Item label="新增列">{item.addColumns.join(', ')}</Descriptions.Item>}
          <Descriptions.Item label="说明">{item.description}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Modal title="编辑变更项" open={editing} onOk={save} onCancel={() => setEditing(false)} destroyOnHidden>
        <Form form={form} layout="vertical">
          <Form.Item label="目标类型" name="typeId"><Input /></Form.Item>
          <Form.Item label="字段名" name="fieldName"><Input /></Form.Item>
          <Form.Item label="字段类型" name="fieldType">
            <Select options={[
              { value: 'StringField', label: 'StringField (文本行)' },
              { value: 'TextField', label: 'TextField (多行文本)' },
              { value: 'IntegerField', label: 'IntegerField (整数)' },
              { value: 'FloatField', label: 'FloatField (小数)' },
              { value: 'BooleanField', label: 'BooleanField (布尔)' },
            ]} />
          </Form.Item>
          <Form.Item label="必填" name="required" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item label="说明" name="description"><Input /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}
