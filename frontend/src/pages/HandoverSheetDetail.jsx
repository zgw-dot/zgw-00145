import React, { useState, useEffect } from 'react'
import {
  Descriptions, Tag, Space, Card, Button, App as AntApp, Typography,
  Table, Timeline, Divider, Row, Col, Modal, Form, Input, Badge, Tooltip,
} from 'antd'
import {
  ArrowLeftOutlined, SwapOutlined, CheckCircleOutlined,
  WarningOutlined, StopOutlined, DownloadOutlined, SearchOutlined,
  ExclamationCircleOutlined, EyeOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Text } = Typography
const { TextArea } = Input

const STATUS_MAP = {
  pending: { label: '待签收', color: 'processing' },
  signed: { label: '已签收', color: 'success' },
  voided: { label: '已作废', color: 'default' },
}

const LABEL_STATUS_MAP = {
  draft: { label: '草稿', color: 'default' },
  pending_approval: { label: '待审', color: 'processing' },
  published: { label: '已发布', color: 'success' },
  revoking: { label: '撤销中', color: 'warning' },
  rolled_back: { label: '已回滚', color: 'warning' },
  revoked: { label: '已撤销', color: 'error' },
}

const ACTION_MAP = {
  create: { label: '创建', color: 'blue' },
  sign: { label: '签收', color: 'green' },
  void: { label: '作废', color: 'red' },
  check_conflict: { label: '冲突检查', color: 'orange' },
  conflict_auto_mark: { label: '冲突自动标记', color: 'volcano' },
}

export default function HandoverSheetDetail({ user }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [signOpen, setSignOpen] = useState(false)
  const [voidOpen, setVoidOpen] = useState(false)
  const [voidForm] = Form.useForm()

  const canSign = ['admin', 'operator', 'clerk'].includes(user?.role)
  const canVoid = user?.role === 'admin'

  useEffect(() => { loadDetail() }, [id])

  const loadDetail = async () => {
    setLoading(true)
    try {
      const res = await api.get(`/handover-sheets/${id}`)
      setData(res.data)
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleCheckConflicts = async () => {
    try {
      const res = await api.post(`/handover-sheets/${id}/check-conflicts`)
      if (res.data.has_conflict) {
        modal.warning({
          title: '发现冲突',
          content: `检测到 ${res.data.conflict_count} 项冲突，请查看冲突明细`,
          okText: '知道了',
        })
      } else {
        message.success('未发现冲突，所有价签状态正常')
      }
      loadDetail()
    } catch (err) {
      message.error(err.message)
    }
  }

  const handleSign = async () => {
    try {
      await api.post(`/handover-sheets/${id}/sign`)
      message.success('签收成功')
      setSignOpen(false)
      loadDetail()
    } catch (err) {
      if (err.message && err.message.includes('冲突')) {
        modal.warning({
          title: '无法签收',
          content: err.message,
          okText: '知道了',
        })
      } else {
        message.error(err.message)
      }
    }
  }

  const handleVoid = async (values) => {
    try {
      await api.post(`/handover-sheets/${id}/void`, { reason: values.reason })
      message.success('作废成功')
      setVoidOpen(false)
      voidForm.resetFields()
      loadDetail()
    } catch (err) {
      message.error(err.message)
    }
  }

  const handleExportDetail = () => {
    window.open(`/api/export/handover-sheet/${id}`, '_blank')
    message.success('已开始导出')
  }

  if (!data) return <div style={{ padding: 40 }}>加载中...</div>

  const statusInfo = STATUS_MAP[data.status] || { label: data.status, color: 'default' }

  const itemColumns = [
    {
      title: 'SKU',
      dataIndex: 'snapshot_sku',
      key: 'sku',
      width: 140,
      render: (v) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
    },
    {
      title: '门店',
      dataIndex: 'snapshot_store',
      key: 'store',
      width: 120,
    },
    {
      title: '原价',
      dataIndex: 'snapshot_original_price',
      key: 'original_price',
      width: 100,
      align: 'right',
      render: (v) => <span style={{ textDecoration: 'line-through', color: '#8c8c8c' }}>¥{v?.toFixed(2)}</span>,
    },
    {
      title: '促销价',
      dataIndex: 'snapshot_promotion_price',
      key: 'promotion_price',
      width: 120,
      align: 'right',
      render: (v, r) => {
        const discount = r.snapshot_original_price > 0 ? (v / r.snapshot_original_price * 100).toFixed(1) : '-'
        return (
          <Space direction="vertical" size={0} style={{ alignItems: 'flex-end' }}>
            <span style={{ fontSize: 16, fontWeight: 600, color: '#ff4d4f' }}>¥{v?.toFixed(2)}</span>
            <span style={{ fontSize: 11, color: '#8c8c8c' }}>{discount}%</span>
          </Space>
        )
      },
    },
    {
      title: '生效时段',
      key: 'period',
      width: 260,
      render: (_, r) => (
        <div style={{ fontSize: 12 }}>
          <div><Tag color="green">起</Tag>{dayjs(r.snapshot_effective_from).format('YYYY-MM-DD HH:mm')}</div>
          <div style={{ marginTop: 2 }}><Tag color="red">止</Tag>{dayjs(r.snapshot_effective_to).format('YYYY-MM-DD HH:mm')}</div>
        </div>
      ),
    },
    {
      title: '快照版本',
      dataIndex: 'snapshot_label_version',
      key: 'version',
      width: 90,
      align: 'center',
      render: (v) => <Tag>v{v}</Tag>,
    },
    {
      title: '打印状态',
      dataIndex: 'print_status',
      key: 'print_status',
      width: 100,
      align: 'center',
      render: (v) => v === 'printed'
        ? <Tag color="success" icon={<CheckCircleOutlined />}>已打印</Tag>
        : <Tag color="processing">待打印</Tag>,
    },
    {
      title: '当前状态',
      dataIndex: 'current_label_status',
      key: 'current_status',
      width: 100,
      align: 'center',
      render: (v, r) => {
        const ls = LABEL_STATUS_MAP[v] || { label: v || '已删除', color: 'default' }
        return <Tag color={ls.color}>{ls.label}</Tag>
      },
    },
    {
      title: '冲突',
      key: 'conflict',
      width: 200,
      render: (_, r) => r.is_conflict
        ? (
          <Tooltip title={r.conflict_reason}>
            <Tag color="error" icon={<WarningOutlined />}>冲突</Tag>
            <Text type="danger" style={{ fontSize: 12 }}>{r.conflict_reason}</Text>
          </Tooltip>
        )
        : <Tag color="success">正常</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      fixed: 'right',
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => navigate(`/labels/${r.label_id}`)}>
          查看价签
        </Button>
      ),
    },
  ]

  return (
    <div>
      <div className="action-bar">
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ paddingLeft: 0 }}>
            返回列表
          </Button>
          <Space size={12} align="center" style={{ marginTop: 4 }}>
            <Title level={4} style={{ margin: 0 }}>交接单详情</Title>
            <Tag color={statusInfo.color} style={{ fontSize: 14, padding: '4px 12px' }}>
              {statusInfo.label}
            </Tag>
            <Tag color="blue">{data.sheet_no}</Tag>
            {data.has_conflict && (
              <Badge count="有冲突" style={{ backgroundColor: '#faad14' }}>
                <Tag color="warning" icon={<WarningOutlined />}>冲突</Tag>
              </Badge>
            )}
          </Space>
        </div>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={handleExportDetail}>
            导出明细
          </Button>
          <Button icon={<SearchOutlined />} onClick={handleCheckConflicts}>
            检查冲突
          </Button>
          {data.status === 'pending' && canSign && (
            <Button type="primary" icon={<CheckCircleOutlined />} onClick={() => setSignOpen(true)}>
              签收
            </Button>
          )}
          {data.status !== 'voided' && canVoid && (
            <Button danger icon={<StopOutlined />} onClick={() => setVoidOpen(true)}>
              作废
            </Button>
          )}
        </Space>
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card title="价签明细" size="small">
            <Table
              rowKey="id"
              size="small"
              columns={itemColumns}
              dataSource={data.items || []}
              scroll={{ x: 1400 }}
              pagination={false}
              rowClassName={(r) => r.is_conflict ? 'conflict-row' : ''}
            />
          </Card>
        </Col>

        <Col xs={24} lg={8}>
          <Card title="基本信息" size="small">
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="交接单号">{data.sheet_no}</Descriptions.Item>
              <Descriptions.Item label="标题">{data.title}</Descriptions.Item>
              <Descriptions.Item label="门店">{data.store}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="价签数量">{data.total_items}</Descriptions.Item>
              <Descriptions.Item label="冲突状态">
                {data.has_conflict
                  ? <Tag color="error" icon={<WarningOutlined />}>有冲突</Tag>
                  : <Tag color="success">无冲突</Tag>
                }
              </Descriptions.Item>
              {data.remark && <Descriptions.Item label="备注">{data.remark}</Descriptions.Item>}
              <Descriptions.Item label="创建人">{data.created_by_name || `ID:${data.created_by}`}</Descriptions.Item>
              <Descriptions.Item label="创建时间">{dayjs(data.created_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
              {data.signed_by && (
                <>
                  <Descriptions.Item label="签收人">{data.signed_by_name || `ID:${data.signed_by}`}</Descriptions.Item>
                  <Descriptions.Item label="签收时间">{dayjs(data.signed_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
                </>
              )}
              {data.voided_by && (
                <>
                  <Descriptions.Item label="作废人">{data.voided_by_name || `ID:${data.voided_by}`}</Descriptions.Item>
                  <Descriptions.Item label="作废时间">{dayjs(data.voided_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
                  <Descriptions.Item label="作废原因">{data.void_reason}</Descriptions.Item>
                </>
              )}
              {data.conflict_checked_at && (
                <Descriptions.Item label="最近冲突检查">{dayjs(data.conflict_checked_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          {(data.logs?.length > 0) && (
            <Card title="操作日志" size="small" style={{ marginTop: 16 }}>
              <Timeline
                items={data.logs.map(log => {
                  const actionInfo = ACTION_MAP[log.action] || { label: log.action, color: 'default' }
                  return {
                    color: actionInfo.color === 'red' ? 'red' : actionInfo.color === 'green' ? 'green' : 'blue',
                    children: (
                      <div>
                        <Space size={4}>
                          <Tag color={actionInfo.color} style={{ fontSize: 11 }}>{actionInfo.label}</Tag>
                          <Text type="secondary" style={{ fontSize: 12 }}>{log.operated_by_name}</Text>
                        </Space>
                        <div style={{ marginTop: 4, fontSize: 12, color: '#595959' }}>{log.detail}</div>
                        <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 2 }}>
                          {dayjs(log.created_at).format('YYYY-MM-DD HH:mm:ss')}
                        </div>
                      </div>
                    ),
                  }
                })}
              />
            </Card>
          )}
        </Col>
      </Row>

      <Modal
        title="确认签收"
        open={signOpen}
        onCancel={() => setSignOpen(false)}
        onOk={handleSign}
        okText="确认签收"
        okButtonProps={{ danger: true }}
        width={480}
      >
        <div style={{ padding: 12, background: '#e6f7ff', borderRadius: 6, border: '1px solid #91d5ff', marginBottom: 16 }}>
          <Text strong>签收后将标记所有价签为已打印，此操作不可撤销。</Text>
        </div>
        {data.has_conflict && (
          <div style={{ padding: 12, background: '#fff2f0', borderRadius: 6, border: '1px solid #ffccc7', marginBottom: 16 }}>
            <Text type="danger" strong icon={<WarningOutlined />}>
              当前交接单存在冲突项，无法签收。请先处理冲突。
            </Text>
          </div>
        )}
        <Descriptions column={1} size="small">
          <Descriptions.Item label="交接单号">{data.sheet_no}</Descriptions.Item>
          <Descriptions.Item label="价签数量">{data.total_items}</Descriptions.Item>
          <Descriptions.Item label="签收人">{user?.username}</Descriptions.Item>
        </Descriptions>
      </Modal>

      <Modal
        title="作废交接单"
        open={voidOpen}
        onCancel={() => { setVoidOpen(false); voidForm.resetFields() }}
        onOk={() => voidForm.submit()}
        okText="确认作废"
        okButtonProps={{ danger: true }}
        width={560}
        destroyOnClose
      >
        <Form form={voidForm} layout="vertical" onFinish={handleVoid}>
          <Form.Item
            name="reason"
            label="作废原因"
            rules={[{ required: true, message: '请填写作废原因' }]}
          >
            <TextArea rows={4} placeholder="请详细说明作废原因" maxLength={200} showCount />
          </Form.Item>
          <div style={{ padding: 12, background: '#fff2f0', borderRadius: 6, border: '1px solid #ffccc7' }}>
            <Text type="danger" strong>
              <ExclamationCircleOutlined /> 作废后该交接单将不可恢复，但历史记录会保留在日志中。
              已签收的交接单作废后，不会撤销已打印状态。
            </Text>
          </div>
        </Form>
      </Modal>
    </div>
  )
}
