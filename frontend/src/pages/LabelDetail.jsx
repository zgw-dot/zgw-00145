import React, { useState, useEffect } from 'react'
import {
  Descriptions, Tag, Space, Card, Button, App as AntApp, Typography,
  Modal, Form, Select, Input, Table, Timeline, Divider, Row, Col, Tooltip,
} from 'antd'
import {
  ArrowLeftOutlined, UndoOutlined, CheckCircleOutlined, EyeOutlined,
  ClockCircleOutlined, SendOutlined, PrinterOutlined, RollbackOutlined,
  StopOutlined, ExclamationCircleOutlined,
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
  revoking: { label: '撤销中', color: 'warning' },
  rolled_back: { label: '已回滚', color: 'warning' },
  revoked: { label: '已撤销', color: 'error' },
}

export default function LabelDetail({ user }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [rollbackOpen, setRollbackOpen] = useState(false)
  const [revokeOpen, setRevokeOpen] = useState(false)
  const [revokeRequestOpen, setRevokeRequestOpen] = useState(false)
  const [form] = Form.useForm()
  const [revokeForm] = Form.useForm()
  const [revokeRequestForm] = Form.useForm()

  const canRollback = user?.role === 'admin'
  const canDirectRevoke = user?.role === 'admin'
  const canRevokeRequest = ['admin', 'operator'].includes(user?.role)

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

  const handleRevoke = async (values) => {
    try {
      await api.post(`/labels/${id}/revoke`, { reason: values.reason })
      message.success('发布撤销成功')
      setRevokeOpen(false)
      revokeForm.resetFields()
      loadDetail()
    } catch (err) {
      if (err.message && err.message.includes('已打印')) {
        modal.warning({
          title: '无法撤销',
          content: err.message,
          okText: '知道了',
        })
      } else {
        message.error(err.message)
      }
    }
  }

  const handleRevokeRequest = async (values) => {
    try {
      const res = await api.post('/labels/revoke-request', {
        label_ids: [parseInt(id)],
        reason: values.reason
      })
      if (res.data.success_count > 0) {
        message.success('撤销申请已提交，待管理员审批')
      } else if (res.data.failed.length > 0) {
        message.warning(res.data.failed[0].reason)
      }
      setRevokeRequestOpen(false)
      revokeRequestForm.resetFields()
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
          {label.status === 'published' && canRevokeRequest && (
            <Button
              danger
              icon={<StopOutlined />}
              onClick={() => setRevokeRequestOpen(true)}
            >
              申请撤销
            </Button>
          )}
          {label.status === 'revoking' && canRevokeRequest && (
            <Tooltip title="撤销申请处理中，请等待管理员审批">
              <Button
                danger
                icon={<ClockCircleOutlined />}
                disabled
              >
                撤销申请处理中
              </Button>
            </Tooltip>
          )}
          {label.status === 'published' && canDirectRevoke && (
            <Button
              danger
              icon={<StopOutlined />}
              onClick={() => setRevokeOpen(true)}
            >
              直接撤销
            </Button>
          )}
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
                label.revoked_at && {
                  color: 'red',
                  children: (
                    <div>
                      <div><Text strong>已撤销</Text></div>
                      <div style={{ color: '#8c8c8c', fontSize: 12 }}>
                        {dayjs(label.revoked_at).format('YYYY-MM-DD HH:mm:ss')}
                        {label.revoke_reason && <div style={{ marginTop: 4, color: '#ff4d4f' }}>原因：{label.revoke_reason}</div>}
                      </div>
                    </div>
                  ),
                },
              ].filter(Boolean)}
            />
          </Card>

          {rh?.length > 0 && (
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

          {data.revocation_requests?.length > 0 && (
            <Card
              title={
                <Space>
                  <ClockCircleOutlined style={{ color: '#faad14' }} />
                  <span>撤销申请进度</span>
                  {data.revocation_requests[0]?.status === 'pending' && (
                    <Tag color="processing" style={{ marginLeft: 8 }}>处理中</Tag>
                  )}
                </Space>
              }
              size="small"
              style={{ marginTop: 16, background: data.revocation_requests[0]?.status === 'pending' ? '#fffbe6' : undefined, borderColor: data.revocation_requests[0]?.status === 'pending' ? '#ffe58f' : undefined }}
            >
              <div style={{ marginBottom: 12 }}>
                <Text strong>最近一次撤销申请：</Text>
              </div>
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="申请状态">
                  {data.revocation_requests[0]?.status === 'pending' && <Tag color="processing">待处理</Tag>}
                  {data.revocation_requests[0]?.status === 'approved' && <Tag color="success">已通过</Tag>}
                  {data.revocation_requests[0]?.status === 'rejected' && <Tag color="error">已驳回</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="申请原因">
                  {data.revocation_requests[0]?.reason || '-'}
                </Descriptions.Item>
                <Descriptions.Item label="申请时间">
                  {data.revocation_requests[0]?.requested_at ? dayjs(data.revocation_requests[0].requested_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
                </Descriptions.Item>
                <Descriptions.Item label="申请人">
                  {data.revocation_requests[0]?.requested_by_name || `ID:${data.revocation_requests[0]?.requested_by}`}
                </Descriptions.Item>
                {data.revocation_requests[0]?.status !== 'pending' && (
                  <>
                    <Descriptions.Item label="处理时间">
                      {data.revocation_requests[0]?.reviewed_at ? dayjs(data.revocation_requests[0].reviewed_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="处理人">
                      {data.revocation_requests[0]?.reviewed_by_name || `ID:${data.revocation_requests[0]?.reviewed_by}`}
                    </Descriptions.Item>
                    <Descriptions.Item label="处理意见">
                      {data.revocation_requests[0]?.review_comment || '-'}
                    </Descriptions.Item>
                    {data.revocation_requests[0]?.offline_processing_note && (
                      <Descriptions.Item label="线下处理说明">
                        {data.revocation_requests[0].offline_processing_note}
                      </Descriptions.Item>
                    )}
                  </>
                )}
              </Descriptions>
            </Card>
          )}

          {data.revocation_logs?.length > 0 && (
            <Card title="撤销日志" size="small" style={{ marginTop: 16 }}>
              <Table
                size="small"
                rowKey="id"
                pagination={false}
                dataSource={data.revocation_logs}
                columns={[
                  { title: '撤销时间', dataIndex: 'created_at', width: 170, render: v => dayjs(v).format('YYYY-MM-DD HH:mm:ss') },
                  { title: '原状态', dataIndex: 'original_status', width: 100, align: 'center', render: v => {
                    const s = STATUS_MAP[v] || { label: v, color: 'default' }
                    return <Tag color={s.color}>{s.label}</Tag>
                  }},
                  { title: '撤销原因', dataIndex: 'reason', render: v => v || '-' },
                  { title: '受影响打印清单ID', dataIndex: 'affected_print_queue_ids', width: 160, render: v => v || '无' },
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

      <Modal
        title={`发布撤销价签 #${label.id}`}
        open={revokeOpen}
        onCancel={() => { setRevokeOpen(false); revokeForm.resetFields() }}
        onOk={() => revokeForm.submit()}
        okText="确认撤销"
        okButtonProps={{ danger: true }}
        destroyOnClose
        width={560}
      >
        <Form form={revokeForm} layout="vertical" onFinish={handleRevoke}>
          <Form.Item
            name="reason"
            label="撤销原因"
            rules={[{ required: true, message: '请填写撤销原因' }]}
          >
            <TextArea rows={4} placeholder="请详细说明撤销发布的原因，将记入独立操作日志" maxLength={200} showCount />
          </Form.Item>
          <div style={{ padding: 12, background: '#fff2f0', borderRadius: 6, border: '1px solid #ffccc7' }}>
            <Text type="danger" strong>
              <ExclamationCircleOutlined /> 撤销后价签将从"已发布"变为"已撤销"，未打印的打印清单项将被同步移除。该操作不可逆。
            </Text>
            <div style={{ marginTop: 8 }}>
              <Text type="warning">
                如果该价签已有已打印记录，将无法直接撤销，需先记录线下处理原因并回收已打印价签。
              </Text>
            </div>
          </div>
        </Form>
      </Modal>

      <Modal
        title={`撤销申请价签 #${label.id}`}
        open={revokeRequestOpen}
        onCancel={() => { setRevokeRequestOpen(false); revokeRequestForm.resetFields() }}
        onOk={() => revokeRequestForm.submit()}
        okText="提交申请"
        okButtonProps={{ danger: true }}
        destroyOnClose
        width={560}
      >
        <Form form={revokeRequestForm} layout="vertical" onFinish={handleRevokeRequest}>
          <Form.Item
            name="reason"
            label="撤销原因"
            rules={[{ required: true, message: '请填写撤销原因' }]}
          >
            <TextArea rows={4} placeholder="请详细说明撤销发布的原因，管理员审批后生效" maxLength={200} showCount />
          </Form.Item>
          <div style={{ padding: 12, background: '#fffbe6', borderRadius: 6, border: '1px solid #ffe58f' }}>
            <Text type="warning" strong>
              提交后价签将进入"撤销中"状态，不再进入打印队列，待管理员批准或驳回。审批期间不可重复提交申请。
            </Text>
          </div>
        </Form>
      </Modal>
    </div>
  )
}
