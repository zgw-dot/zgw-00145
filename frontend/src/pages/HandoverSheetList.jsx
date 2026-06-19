import React, { useState, useEffect } from 'react'
import {
  Table, Tag, Space, Card, Button, Input, Select, App as AntApp,
  Typography, Modal, Form, Checkbox, Badge, Tooltip,
} from 'antd'
import {
  SearchOutlined, ReloadOutlined, PlusOutlined, DownloadOutlined,
  SwapOutlined, WarningOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Text } = Typography

const STATUS_MAP = {
  pending: { label: '待签收', color: 'processing' },
  signed: { label: '已签收', color: 'success' },
  voided: { label: '已作废', color: 'default' },
}

export default function HandoverSheetList({ user }) {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [data, setData] = useState([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ status: '', store: '', sheet_no: '', has_conflict: '' })
  const [createOpen, setCreateOpen] = useState(false)
  const [availableLabels, setAvailableLabels] = useState([])
  const [labelsLoading, setLabelsLoading] = useState(false)
  const [createForm] = Form.useForm()

  const canCreate = ['admin', 'operator'].includes(user?.role)

  useEffect(() => { loadData(1, 20) }, [])

  const loadData = async (page, pageSize) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page, size: pageSize,
        status: filters.status,
        store: filters.store,
        sheet_no: filters.sheet_no,
        has_conflict: filters.has_conflict,
      })
      const res = await api.get(`/handover-sheets?${params}`)
      setData(res.data.list)
      setPagination({ current: page, pageSize, total: res.data.total })
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleExport = () => {
    const params = new URLSearchParams({
      status: filters.status,
      store: filters.store,
    })
    window.open(`/api/export/handover-sheets?${params}`, '_blank')
    message.success('已开始导出')
  }

  const openCreateDialog = () => {
    setCreateOpen(true)
    createForm.resetFields()
    setAvailableLabels([])
  }

  const handleStoreSelect = async (store) => {
    if (!store) {
      setAvailableLabels([])
      return
    }
    setLabelsLoading(true)
    try {
      const res = await api.get(`/handover-sheets/available-labels?store=${encodeURIComponent(store)}`)
      setAvailableLabels(res.data.filter(l => !l.in_active_sheet))
    } catch (err) {
      message.error(err.message)
    } finally {
      setLabelsLoading(false)
    }
  }

  const handleCreate = async (values) => {
    try {
      const res = await api.post('/handover-sheets', {
        title: values.title,
        store: values.store,
        remark: values.remark,
        label_ids: values.label_ids,
      })
      if (res.data.failed?.length > 0) {
        message.warning(`创建成功(${res.data.total_items}项)，${res.data.failed.length}项被拒绝: ${res.data.failed.map(f => f.reason).join('; ')}`)
      } else {
        message.success(`交接单创建成功，含${res.data.total_items}项价签`)
      }
      setCreateOpen(false)
      createForm.resetFields()
      setAvailableLabels([])
      loadData(1, pagination.pageSize)
    } catch (err) {
      message.error(err.message)
    }
  }

  const columns = [
    {
      title: '交接单号',
      dataIndex: 'sheet_no',
      key: 'sheet_no',
      width: 200,
      render: (v, r) => (
        <Button type="link" size="small" onClick={() => navigate(`/handover-sheets/${r.id}`)} style={{ padding: 0 }}>
          {v}
        </Button>
      ),
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      width: 200,
      ellipsis: true,
    },
    {
      title: '门店',
      dataIndex: 'store',
      key: 'store',
      width: 140,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      align: 'center',
      render: (v, r) => {
        const s = STATUS_MAP[v] || { label: v, color: 'default' }
        return (
          <Space size={4}>
            <Tag color={s.color}>{s.label}</Tag>
            {r.has_conflict && (
              <Tooltip title="存在冲突项">
                <WarningOutlined style={{ color: '#faad14' }} />
              </Tooltip>
            )}
          </Space>
        )
      },
    },
    {
      title: '价签数',
      dataIndex: 'total_items',
      key: 'total_items',
      width: 80,
      align: 'center',
    },
    {
      title: '备注',
      dataIndex: 'remark',
      key: 'remark',
      width: 160,
      ellipsis: true,
      render: (v) => v || '-',
    },
    {
      title: '创建人',
      key: 'creator',
      width: 100,
      render: (_, r) => r.created_by_name || `ID:${r.created_by}`,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '签收人',
      key: 'signer',
      width: 100,
      render: (_, r) => r.signed_by_name || '-',
    },
    {
      title: '签收时间',
      dataIndex: 'signed_at',
      key: 'signed_at',
      width: 160,
      render: (v) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      fixed: 'right',
      render: (_, r) => (
        <Button type="link" size="small" onClick={() => navigate(`/handover-sheets/${r.id}`)}>
          查看详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>
          <SwapOutlined style={{ color: '#1677ff' }} /> 交接单管理
        </Title>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={handleExport}>
            导出 CSV
          </Button>
          {canCreate && (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreateDialog}>
              新建交接单
            </Button>
          )}
        </Space>
      </div>

      <Card bodyStyle={{ padding: 0 }}>
        <div className="filter-bar" style={{ padding: '16px 16px 0 16px' }}>
          <Space size={12} wrap>
            <Select
              placeholder="交接单状态"
              style={{ width: 140 }}
              allowClear
              value={filters.status || undefined}
              onChange={(v) => setFilters({ ...filters, status: v || '' })}
              options={[
                { value: 'pending', label: '待签收' },
                { value: 'signed', label: '已签收' },
                { value: 'voided', label: '已作废' },
              ]}
            />
            <Input
              placeholder="搜索门店"
              prefix={<SearchOutlined />}
              style={{ width: 180 }}
              allowClear
              value={filters.store}
              onChange={(e) => setFilters({ ...filters, store: e.target.value })}
              onPressEnter={() => loadData(1, pagination.pageSize)}
            />
            <Input
              placeholder="搜索交接单号"
              style={{ width: 200 }}
              allowClear
              value={filters.sheet_no}
              onChange={(e) => setFilters({ ...filters, sheet_no: e.target.value })}
              onPressEnter={() => loadData(1, pagination.pageSize)}
            />
            <Select
              placeholder="冲突状态"
              style={{ width: 140 }}
              allowClear
              value={filters.has_conflict || undefined}
              onChange={(v) => setFilters({ ...filters, has_conflict: v || '' })}
              options={[
                { value: 'true', label: '有冲突' },
              ]}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={() => loadData(1, pagination.pageSize)}>
              查询
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                setFilters({ status: '', store: '', sheet_no: '', has_conflict: '' })
                setTimeout(() => loadData(1, pagination.pageSize), 50)
              }}
            >
              重置
            </Button>
          </Space>
        </div>

        <Table
          rowKey="id"
          columns={columns}
          dataSource={data}
          loading={loading}
          scroll={{ x: 1600 }}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条交接单`,
            onChange: (p, ps) => loadData(p, ps),
          }}
        />
      </Card>

      <Modal
        title="新建交接单"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); createForm.resetFields(); setAvailableLabels([]) }}
        onOk={() => createForm.submit()}
        okText="创建"
        width={720}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            name="title"
            label="交接单标题"
            rules={[{ required: true, message: '请输入交接单标题' }]}
          >
            <Input placeholder="例如：北京朝阳店2024年6月第一批" maxLength={100} showCount />
          </Form.Item>
          <Form.Item
            name="store"
            label="门店"
            rules={[{ required: true, message: '请选择门店' }]}
          >
            <Select
              placeholder="请选择门店"
              onChange={handleStoreSelect}
              options={[
                { value: '北京朝阳店', label: '北京朝阳店' },
                { value: '上海浦东店', label: '上海浦东店' },
                { value: '广州天河店', label: '广州天河店' },
                { value: '深圳南山店', label: '深圳南山店' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="label_ids"
            label="选择价签"
            rules={[{ required: true, message: '请选择至少一个价签' }]}
          >
            <Checkbox.Group style={{ width: '100%' }}>
              {labelsLoading ? (
                <Text type="secondary">加载中...</Text>
              ) : availableLabels.length === 0 ? (
                <Text type="secondary">请先选择门店以加载可用价签</Text>
              ) : (
                <div style={{ maxHeight: 300, overflow: 'auto' }}>
                  {availableLabels.map(label => (
                    <div key={label.id} style={{ padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}>
                      <Checkbox value={label.id}>
                        <Space size={8}>
                          <Text code style={{ fontFamily: 'monospace' }}>{label.sku}</Text>
                          <Text type="secondary">{label.store}</Text>
                          <Text delete type="secondary">¥{label.original_price?.toFixed(2)}</Text>
                          <Text type="danger" strong>¥{label.promotion_price?.toFixed(2)}</Text>
                          <Text type="secondary" style={{ fontSize: 11 }}>
                            {dayjs(label.effective_from).format('MM-DD')}~{dayjs(label.effective_to).format('MM-DD')}
                          </Text>
                        </Space>
                      </Checkbox>
                    </div>
                  ))}
                </div>
              )}
            </Checkbox.Group>
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={3} placeholder="备注信息(选填)" maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
