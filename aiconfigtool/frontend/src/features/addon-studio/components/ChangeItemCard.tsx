import { Card, Descriptions, Space, Tag, Button } from 'antd';
import { EditOutlined, DeleteOutlined } from '@ant-design/icons';
import type { ChangeItem } from '@/core/types/domain';

const typeColor: Record<string, string> = {
  AddField: 'blue',
  UpdateListing: 'cyan',
  UpdatePermission: 'gold',
  UpdateWorkflow: 'purple',
  CreateReportTemplateFromDocx: 'magenta',
};

export default function ChangeItemCard({ item }: { item: ChangeItem }) {
  return (
    <Card
      size="small"
      title={
        <Space>
          <Tag color={typeColor[item.changeType] ?? 'default'}>
            {item.changeType}
          </Tag>
          {item.framework && <Tag>{item.framework}</Tag>}
        </Space>
      }
      extra={
        <Space>
          <Button type="text" size="small" icon={<EditOutlined />} />
          <Button type="text" size="small" danger icon={<DeleteOutlined />} />
        </Space>
      }
      style={{ marginBottom: 12 }}
    >
      <Descriptions size="small" column={1} colon>
        {item.typeId && (
          <Descriptions.Item label="目标类型">{item.typeId}</Descriptions.Item>
        )}
        {item.fieldName && (
          <Descriptions.Item label="字段名">{item.fieldName}</Descriptions.Item>
        )}
        {item.fieldType && (
          <Descriptions.Item label="字段类型">{item.fieldType}</Descriptions.Item>
        )}
        {typeof item.required === 'boolean' && (
          <Descriptions.Item label="必填">
            {item.required ? '是' : '否'}
          </Descriptions.Item>
        )}
        {item.addColumns && item.addColumns.length > 0 && (
          <Descriptions.Item label="新增列">
            {item.addColumns.join(', ')}
          </Descriptions.Item>
        )}
        <Descriptions.Item label="说明">{item.description}</Descriptions.Item>
      </Descriptions>
    </Card>
  );
}
