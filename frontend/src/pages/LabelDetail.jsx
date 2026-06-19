import React, { useState, useEffect } from 'react'
import {
  Descriptions, Tag, Space, Card, Button, App as AntApp, Typography,
  Modal, Form, Select, Input, Table, Timeline, Divider, Row, Col,
} from 'antd'
import {
  ArrowLeftOutlined, UndoOutlined, CheckCircleOutlined, EyeOutlined,
  ClockCircleOutlined, SendOutlined, PrinterOutlined, RollbackOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Text } = Typography
const { TextArea } = Input

const STATUS_MAP = {
  draft: { label: '草稿', color: 'default' },
  pending_approval: { label: '待审', color: 'processing' },
  published: { label: '已发布', color: 'success' },
  rolled_back: { label: '已回滚', color: 'warning' },
}

export default function LabelDetail({ user }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [rollbackOpen, setRollbackOpen] = useState(false)
  const [form] = Form.useForm()

  const canRollback = user?.role === 'admin'

  useEffect(() => { loadDetail() }, [id])

  const loadDetail = async () => {
    setLoading(true)
    try {
      const res = await api.get(`/labels/${id}`)
      setData(res.data)
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleRollback = async (values) => {
    try {
      const payload = { reason: values.reason }
      if (values.target_version && values.target_version !== 'direct') {
        payload.target_version = parseInt(values.target_version)
      }
      await api.post(`/labels/${id}/rollback`, payload)
      message.success('回滚成功')
      setRollbackOpen(false)
      form.resetFields()
      loadDetail()
    } catch (err) {
      message.error(err.message)
    }
  }

  if (!data) return <div style={{ padding: 40 }}>加载中...</div>

  const { label, rollback_history: rh, versions } = data
  const statusInfo = STATUS_MAP[label.status] || { label: label.status, color: 'default' }
  const discount = label.original_price > 0 ? (label.promotion_price / label.original_price * 100).toFixed(1) : '-'

  const versionOptions = [
    { value: 'direct', label: '直接标记回滚（不生成新版本）' },
    ...versions
      .filter(v => v.id !== label.id)
      .map(v => ({
        value: String(v.version),
        label: `v${v.version} (${STATUS_MAP[v.status]?.label || v.status}) ¥${v.promotion_price} [${dayjs(v.effective_from).format('MM-DD')} ~ ${dayjs(v.effective_to).format('MM-DD')}]`,
      })),
  ]

  return (
    <div>
      <div className="action-bar">
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ paddingLeft: 0 }}>
            返回列表
          </Button>
          <Space size={12} align="center" style={{ marginTop: 4 }}>
            <Title level={4} style={{ margin: 0 }}>价签详情</Title>
            <Tag color={statusInfo.color} style={{ fontSize: 14, padding: '4px 12px' }}>
              {statusInfo.label}
            </Tag>
            <Tag>v{label.version}</Tag>
            <Tag color="blue">#{label.id}</Tag>
          </Space>
        </div>
        <Space>
          {label.status === 'published' && canRollback && (
            <Button danger icon={<RollbackOutlined />} onClick={() => setRollbackOpen(true)}>
              回滚此价签
            </Button>
          )}
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card title="价格信息" size="small">
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="SKU">
                <Text code copyable>{label.sku}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="门店">{label.store}</Descriptions.Item>
              <Descriptions.Item label="原价">
                <span style={{ textDecoration: 'line-through', color: '#8c8c8c' }}>¥{label.original_price.toFixed(2)}</span>
              </Descriptions.Item>
              <Descriptions.Item label="促销价">
                <span style={{ fontSize: 20, fontWeight: 600, color: '#ff4d4f' }}>¥{label.promotion_price.toFixed(2)}</span>
                <Tag color="red" style={{ marginLeft: 8 }}>{discount}% OFF</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="生效开始时间" span={1}>
                <Tag color="green">{dayjs(label.effective_from).format('YYYY-MM-DD HH:mm:ss')}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="生效结束时间" span={1}>
                <Tag color="red">{dayjs(label.effective_to).format('YYYY-MM-DD HH:mm:ss')}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="模板" span={1}>{label.template}</Descriptions.Item>
              <Descriptions.Item label="关联批次" span={1}>
                {label.batch_id ? (
                  <Button type="link" size="small" onClick={() => navigate(`/import/${label.batch_id}`)}>
                    查看批次 #{label.batch_id}
                  </Button>
                ) : '-'}
              </Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="流转时间线" size="small" style={{ marginTop: 16 }}>
            <Timeline
              items={[
                {
                  color: 'blue',
                  children: (
                    <div>
                      <div><Text strong>创建草稿</Text></div>
                      <div style={{ color: '#8c8c8c', fontSize: 12 }}>
                        {label.created_at && dayjs(label.created_at).format('YYYY-MM-DD HH:mm:ss')}
                      </div>
                    </div>
                  ),
                },
                label.submitted_at && {
                  color: 'purple',
                  children: (
                    <div>
                      <div><Text strong>提交审批</Text></div>
                      <div style={{ color: '#8c8c8c', fontSize: 12 }}>
                        {dayjs(label.submitted_at).format('YYYY-MM-DD HH:mm:ss')}
                      </div>
                    </div>
                  ),
                },
                label.approved_at && {
                  color: 'green',
                  children: (
                    <div>
                      <div><Text strong>审批通过 & 发布</Text></div>
                      <div style={{ color: '#8c8c8c', fontSize: 12 }}>
                        {dayjs(label.approved_at).format('YYYY-MM-DD HH:mm:ss')}
                        {label.approved_by && ` · 审批人ID: ${label.approved_by}`}
                      </div>
                    </div>
                  ),
                },
                label.rolled_back_at && {
                  color: 'red',
                  children: (
                    <div>
                      <div><Text strong>已回滚</Text></div>
                      <div style={{ color: '#8c8c8c', fontSize: 12 }}>
                        {dayjs(label.rolled_back_at).format('YYYY-MM-DD HH:mm:ss')}
                        {label.rollback_reason && <div style={{ marginTop: 4, color: '#ff4d4f' }}>原因：{label.rollback_reason}</div>}
                      </div>
                    </div>
                  ),
                },
              ].filter(Boolean)}
            />
          </Card>

          {rollback_history?.length > 0 && (
            <Card title="回滚历史记录" size="small" style={{ marginTop: 16 }}>
              <Table
                size="small"
                rowKey="id"
                pagination={false}
                dataSource={rh}
                columns={[
                  { title: '操作时间', dataIndex: 'created_at', width: 170, render: v => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
                  { title: '从版本', dataIndex: 'from_version', width: 90, align: 'center', render: v => <Tag>v{v}</Tag> },
                  { title: '到版本', dataIndex: 'to_version', width: 90, align: 'center', render: v => <Tag color="blue">v{v}</Tag> },
                  { title: '原因', dataIndex: 'reason', render: v => v || '-' },
                  { title: '操作人ID', dataIndex: 'operated_by', width: 90, align: 'center' },
                ]}
              />
            </Card>
          )}
        </Col>

        <Col xs={24} lg={8}>
          <Card title="版本历史" size="small">
            <Timeline
              items={versions.slice().reverse().map(v => {
                const isCurrent = v.id === label.id
                const vs = STATUS_MAP[v.status] || { label: v.status, color: 'default' }
                return {
                  color: isCurrent ? 'blue' : 'gray',
                  dot: isCurrent ? <EyeOutlined /> : undefined,
                  children: (
                    <div style={{ padding: '8px 0', border: isCurrent ? '1px dashed #1677ff' : 'none', borderRadius: 6, paddingLeft: isCurrent ? 8 : 0 }}>
                      <Space size={8} align="center">
                        <Text strong style={{ fontSize: 15 }}>v{v.version}</Text>
                        {isCurrent && <Tag color="blue">当前</Tag>}
                        <Tag color={vs.color}>{vs.label}</Tag>
                      </Space>
                      <div style={{ marginTop: 4, fontSize: 13 }}>
                        促销价：<Text strong style={{ color: '#ff4d4f' }}>¥{v.promotion_price}</Text>
                      </div>
                      <div style={{ color: '#8c8c8c', fontSize: 12, marginTop: 2 }}>
                        {dayjs(v.effective_from).format('MM-DD HH:mm')} ~ {dayjs(v.effective_to).format('MM-DD HH:mm')}
                      </div>
                      <div style={{ color: '#8c8c8c', fontSize: 12 }}>
                        创建：{dayjs(v.created_at).format('YYYY-MM-DD HH:mm')}
                      </div>
                    </div>
                  ),
                }
              })}
            />
          </Card>
        </Col>
      </Row>

      <Modal
        title={`回滚价签 #${label.id}`}
        open={rollbackOpen}
        onCancel={() => { setRollbackOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        okText="确认回滚"
        okButtonProps={{ danger: true }}
        destroyOnClose
        width={560}
      >
        <Form form={form} layout="vertical" onFinish={handleRollback}>
          <Form.Item
            name="target_version"
            label="回滚方式"
            initialValue="direct"
            rules={[{ required: true, message: '请选择回滚方式' }]}
          >
            <Select options={versionOptions} />
          </Form.Item>
          <Form.Item
            name="reason"
            label="回滚原因"
            rules={[{ required: true, message: '请填写回滚原因' }]}
          >
            <TextArea rows={4} placeholder="请详细说明回滚原因，将记入历史" maxLength={200} showCount />
          </Form.Item>
          <div style={{ padding: 12, background: '#fff2f0', borderRadius: 6, border: '1px solid #ffccc7' }}>
            <Text type="danger" strong>
              <UndoOutlined /> 回滚操作将写入历史，不可撤销。若选择历史版本，将生成新版本 v{label.version + 1}。
            </Text>
          </div>
        </Form>
      </Modal>
    </div>
  )
}
