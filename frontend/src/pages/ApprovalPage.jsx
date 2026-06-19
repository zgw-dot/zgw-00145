import React, { useState, useEffect } from 'react'
import {
  Table, Tag, Space, Card, Button, Input, Select, App as AntApp,
  Typography, Modal, Checkbox, Tabs, Spin,
} from 'antd'
import {
  SearchOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ReloadOutlined, AuditOutlined, SafetyCertificateOutlined,
  DownloadOutlined, ExclamationCircleOutlined, StopOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Text } = Typography
const { TextArea } = Input

const precheckColumns = [
  {
    title: '价签ID',
    dataIndex: 'label_id',
    key: 'label_id',
    width: 80,
  },
  {
    title: 'SKU',
    dataIndex: 'sku',
    key: 'sku',
    width: 120,
    render: (v) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
  },
  { title: '门店', dataIndex: 'store', key: 'store', width: 120 },
  {
    title: '生效时段',
    key: 'period',
    width: 240,
    render: (_, r) => (
      <div style={{ fontSize: 12 }}>
        <div><Tag color="green">起</Tag>{r.effective_from ? dayjs(r.effective_from).format('YYYY-MM-DD HH:mm') : '-'}</div>
        <div style={{ marginTop: 2 }}><Tag color="red">止</Tag>{r.effective_to ? dayjs(r.effective_to).format('YYYY-MM-DD HH:mm') : '-'}</div>
      </div>
    ),
  },
  {
    title: '风险原因',
    dataIndex: 'risk_reason',
    key: 'risk_reason',
    width: 260,
    render: (v) => v || <Text type="secondary">无</Text>,
  },
  {
    title: '建议动作',
    dataIndex: 'suggested_action',
    key: 'suggested_action',
    width: 220,
    render: (v) => v || '-',
  },
]

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
  const [precheckOpen, setPrecheckOpen] = useState(false)
  const [precheckLoading, setPrecheckLoading] = useState(false)
  const [precheckResult, setPrecheckResult] = useState(null)

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

  const handlePrecheck = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要预检的价签')
      return
    }
    setPrecheckOpen(true)
    setPrecheckLoading(true)
    setPrecheckResult(null)
    try {
      const res = await api.post('/labels/precheck', {
        label_ids: selectedRowKeys,
      })
      setPrecheckResult(res.data)
    } catch (err) {
      message.error(err.message)
    } finally {
      setPrecheckLoading(false)
    }
  }

  const handleExportPrecheck = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要导出的价签')
      return
    }
    try {
      const res = await fetch('/api/export/precheck', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ label_ids: selectedRowKeys }),
      })
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.message || '导出失败')
      }
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const disposition = res.headers.get('Content-Disposition')
      const filename = disposition
        ? disposition.split('filename=')[1]?.replace(/"/g, '')
        : `precheck_${dayjs().format('YYYYMMDDHHmmss')}.csv`
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
      message.success('导出成功')
    } catch (err) {
      message.error(err.message)
    }
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

  const precheckTabs = precheckResult ? [
    {
      key: 'publishable',
      label: (
        <span>
          <SafetyCertificateOutlined style={{ color: '#52c41a' }} />
          可发布 ({precheckResult.publishable_count})
        </span>
      ),
      children: (
        <Table
          rowKey="label_id"
          columns={precheckColumns}
          dataSource={precheckResult.publishable}
          pagination={false}
          size="small"
          scroll={{ x: 900 }}
          locale={{ emptyText: '暂无' }}
        />
      ),
    },
    {
      key: 'conflict',
      label: (
        <span>
          <ExclamationCircleOutlined style={{ color: '#faad14' }} />
          冲突 ({precheckResult.conflict_count})
        </span>
      ),
      children: (
        <Table
          rowKey="label_id"
          columns={precheckColumns}
          dataSource={precheckResult.conflict}
          pagination={false}
          size="small"
          scroll={{ x: 900 }}
          locale={{ emptyText: '暂无' }}
        />
      ),
    },
    {
      key: 'config_restricted',
      label: (
        <span>
          <StopOutlined style={{ color: '#ff4d4f' }} />
          配置限制 ({precheckResult.config_restricted_count})
        </span>
      ),
      children: (
        <Table
          rowKey="label_id"
          columns={precheckColumns}
          dataSource={precheckResult.config_restricted}
          pagination={false}
          size="small"
          scroll={{ x: 900 }}
          locale={{ emptyText: '暂无' }}
        />
      ),
    },
  ] : []

  return (
    <div>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>
          价签审批 <Tag color="processing">{pagination.total} 条待审</Tag>
        </Title>
        {isAdmin ? (
          <Space>
            <Button
              icon={<SafetyCertificateOutlined />}
              disabled={selectedRowKeys.length === 0}
              onClick={handlePrecheck}
            >
              发布预检 ({selectedRowKeys.length})
            </Button>
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

      <Modal
        title={
          <Space>
            <SafetyCertificateOutlined style={{ color: '#1677ff' }} />
            <span>发布预检结果</span>
          </Space>
        }
        open={precheckOpen}
        onCancel={() => { setPrecheckOpen(false); setPrecheckResult(null) }}
        width={960}
        footer={[
          <Button key="export" icon={<DownloadOutlined />} onClick={handleExportPrecheck} disabled={!precheckResult}>
            导出 CSV
          </Button>,
          <Button key="close" onClick={() => { setPrecheckOpen(false); setPrecheckResult(null) }}>
            关闭
          </Button>,
        ]}
      >
        {precheckLoading ? (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Spin size="large" tip="正在预检..." />
          </div>
        ) : precheckResult ? (
          <div>
            <div style={{ marginBottom: 16, display: 'flex', gap: 16 }}>
              <Card size="small" style={{ flex: 1, background: '#f6ffed', borderColor: '#b7eb8f' }}>
                <Text type="success" strong style={{ fontSize: 20 }}>{precheckResult.publishable_count}</Text>
                <div><Text type="secondary">可发布</Text></div>
              </Card>
              <Card size="small" style={{ flex: 1, background: '#fffbe6', borderColor: '#ffe58f' }}>
                <Text style={{ color: '#faad14', fontSize: 20, fontWeight: 600 }}>{precheckResult.conflict_count}</Text>
                <div><Text type="secondary">冲突</Text></div>
              </Card>
              <Card size="small" style={{ flex: 1, background: '#fff2f0', borderColor: '#ffccc7' }}>
                <Text danger strong style={{ fontSize: 20 }}>{precheckResult.config_restricted_count}</Text>
                <div><Text type="secondary">配置限制</Text></div>
              </Card>
            </div>
            <Tabs items={precheckTabs} />
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
