import React, { useState, useEffect } from 'react'
import {
  Table, Tag, Space, Card, Button, Input, Select, App as AntApp,
  Typography, Modal, Checkbox,
} from 'antd'
import {
  SearchOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ReloadOutlined, AuditOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title } = Typography
const { TextArea } = Input

export default function ApprovalPage({ user }) {
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()
  const [data, setData] = useState([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ sku: '', store: '' })
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState('')

  const isAdmin = user?.role === 'admin'

  useEffect(() => {
    loadData(1, 20)
  }, [filters])

  const loadData = async (page, pageSize) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page, pageSize,
        status: 'pending_approval',
        sku: filters.sku,
        store: filters.store,
      })
      const res = await api.get(`/labels?${params}`)
      setData(res.data.list)
      setPagination({ current: page, pageSize, total: res.data.total })
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const doApprove = async (approve, reason = '') => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要审批的价签')
      return
    }
    try {
      const res = await api.post('/labels/approve', {
        label_ids: selectedRowKeys,
        approve,
        reject_reason: reason,
      })
      message.success(
        approve
          ? `审批通过 ${res.data.success_count} 条，已自动发布并生成打印清单`
          : `已驳回 ${res.data.success_count} 条`
      )
      setSelectedRowKeys([])
      loadData(pagination.current, pagination.pageSize)
    } catch (err) {
      message.error(err.message)
    }
  }

  const handleApprove = () => {
    modal.confirm({
      title: '确认审批通过？',
      icon: <AuditOutlined />,
      content: (
        <div>
          <p>共选择 <strong>{selectedRowKeys.length}</strong> 条价签，通过后将：</p>
          <ul style={{ paddingLeft: 20 }}>
            <li>状态变更为"已发布"</li>
            <li>自动加入待打印清单</li>
            <li>价格在生效时段内正式生效</li>
          </ul>
        </div>
      ),
      okText: '确认通过',
      okButtonProps: { type: 'primary', danger: false },
      cancelText: '取消',
      onOk: () => doApprove(true),
    })
  }

  const columns = [
    {
      title: 'SKU',
      dataIndex: 'sku',
      key: 'sku',
      width: 140,
      fixed: 'left',
      render: (v) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
    },
    { title: '门店', dataIndex: 'store', key: 'store', width: 140 },
    {
      title: '原价',
      dataIndex: 'original_price',
      key: 'original_price',
      width: 110,
      align: 'right',
      render: (v) => <span style={{ color: '#8c8c8c', textDecoration: 'line-through' }}>¥{v.toFixed(2)}</span>,
    },
    {
      title: '促销价',
      dataIndex: 'promotion_price',
      key: 'promotion_price',
      width: 110,
      align: 'right',
      render: (v, r) => {
        const discount = r.original_price > 0 ? (v / r.original_price * 100).toFixed(1) : '-'
        const warn = v > r.original_price
        return (
          <Space direction="vertical" size={0} style={{ alignItems: 'flex-end' }}>
            <span style={{ fontSize: 16, fontWeight: 600, color: warn ? '#ff4d4f' : '#ff4d4f' }}>
              ¥{v.toFixed(2)}
            </span>
            <span style={{ fontSize: 11, color: warn ? '#ff4d4f' : '#8c8c8c' }}>
              {warn ? '⚠️ 高于原价！' : `${discount}%`}
            </span>
          </Space>
        )
      },
    },
    {
      title: '生效时段',
      key: 'period',
      width: 300,
      render: (_, r) => (
        <div style={{ fontSize: 12 }}>
          <div><Tag color="green">起</Tag>{dayjs(r.effective_from).format('YYYY-MM-DD HH:mm')}</div>
          <div style={{ marginTop: 2 }}><Tag color="red">止</Tag>{dayjs(r.effective_to).format('YYYY-MM-DD HH:mm')}</div>
        </div>
      ),
    },
    { title: '模板', dataIndex: 'template', key: 'template', width: 100 },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 80,
      align: 'center',
      render: (v) => <Tag>v{v}</Tag>,
    },
    {
      title: '提交时间',
      dataIndex: 'submitted_at',
      key: 'submitted_at',
      width: 160,
      render: (v) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
  ]

  return (
    <div>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>
          价签审批 <Tag color="processing">{pagination.total} 条待审</Tag>
        </Title>
        {isAdmin ? (
          <Space>
            <Button
              danger
              icon={<CloseCircleOutlined />}
              disabled={selectedRowKeys.length === 0}
              onClick={() => setRejectOpen(true)}
            >
              批量驳回 ({selectedRowKeys.length})
            </Button>
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              disabled={selectedRowKeys.length === 0}
              onClick={handleApprove}
            >
              批量通过 ({selectedRowKeys.length})
            </Button>
          </Space>
        ) : (
          <Tag color="warning">当前账号无审批权限（仅管理员可审批）</Tag>
        )}
      </div>

      <Card bodyStyle={{ padding: 0 }}>
        <div className="filter-bar" style={{ padding: '16px 16px 0 16px' }}>
          <Space size={12} wrap>
            <Input
              placeholder="搜索 SKU"
              prefix={<SearchOutlined />}
              style={{ width: 200 }}
              allowClear
              value={filters.sku}
              onChange={(e) => setFilters({ ...filters, sku: e.target.value })}
              onPressEnter={() => loadData(1, pagination.pageSize)}
            />
            <Input
              placeholder="搜索门店"
              prefix={<SearchOutlined />}
              style={{ width: 200 }}
              allowClear
              value={filters.store}
              onChange={(e) => setFilters({ ...filters, store: e.target.value })}
              onPressEnter={() => loadData(1, pagination.pageSize)}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={() => loadData(1, pagination.pageSize)}>
              查询
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                setFilters({ sku: '', store: '' })
                setSelectedRowKeys([])
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
          scroll={{ x: 1200 }}
          rowSelection={isAdmin ? {
            selectedRowKeys,
            onChange: setSelectedRowKeys,
          } : undefined}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条待审批`,
            onChange: (p, ps) => loadData(p, ps),
          }}
        />
      </Card>

      <Modal
        title={`驳回 ${selectedRowKeys.length} 条价签`}
        open={rejectOpen}
        onCancel={() => { setRejectOpen(false); setRejectReason('') }}
        onOk={() => {
          doApprove(false, rejectReason)
          setRejectOpen(false)
          setRejectReason('')
        }}
        okText="确认驳回"
        okButtonProps={{ danger: true }}
        width={500}
      >
        <div style={{ marginBottom: 12 }}>请填写驳回原因：</div>
        <TextArea
          rows={4}
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder="例如：促销价设置错误，请核对后重新提交"
          showCount
          maxLength={200}
        />
      </Modal>
    </div>
  )
}
