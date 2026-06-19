import React, { useState, useEffect } from 'react'
import {
  Table, Tag, Space, Card, Button, Input, Select, App as AntApp,
  Typography, Modal, DatePicker, Tooltip, Checkbox, message as AntMsg,
} from 'antd'
import {
  SearchOutlined, EyeOutlined, SendOutlined, DownloadOutlined,
  CheckCircleOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Paragraph } = Typography
const { RangePicker } = DatePicker

const STATUS_MAP = {
  draft: { label: '草稿', color: 'default' },
  pending_approval: { label: '待审', color: 'processing' },
  published: { label: '已发布', color: 'success' },
  rolled_back: { label: '已回滚', color: 'warning' },
}

export default function LabelList({ user }) {
  const navigate = useNavigate()
  const [sp, setSp] = useSearchParams()
  const { message, modal } = AntApp.useApp()
  const [data, setData] = useState([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({
    status: sp.get('status') || '',
    sku: '',
    store: '',
  })
  const [selectedRowKeys, setSelectedRowKeys] = useState([])

  const canSubmit = ['admin', 'operator'].includes(user?.role)
  const canExport = ['admin', 'operator', 'clerk'].includes(user?.role)

  useEffect(() => {
    loadData(1, 20)
  }, [filters])

  const loadData = async (page, pageSize) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page, pageSize,
        status: filters.status,
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

  const handleSubmit = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要提交的价签')
      return
    }
    const invalid = data.filter(d => selectedRowKeys.includes(d.id) && d.status !== 'draft')
    if (invalid.length > 0) {
      message.warning(`已筛选出 ${invalid.length} 条非草稿状态价签，将跳过`)
    }
    modal.confirm({
      title: '确认提交审批？',
      content: `共选择 ${selectedRowKeys.length} 条价签，提交后将进入待审批状态。`,
      okText: '确认提交',
      onOk: async () => {
        try {
          const res = await api.post('/labels/submit', { label_ids: selectedRowKeys })
          message.success(`成功提交 ${res.data.success_count} 条，失败 ${res.data.failed.length} 条`)
          setSelectedRowKeys([])
          loadData(pagination.current, pagination.pageSize)
        } catch (err) {
          message.error(err.message)
        }
      },
    })
  }

  const handleExport = () => {
    const params = new URLSearchParams({
      status: filters.status,
      sku: filters.sku,
      store: filters.store,
    })
    window.open(`/api/export/labels?${params}`, '_blank')
    message.success('已开始导出')
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
        return (
          <Space direction="vertical" size={0} style={{ alignItems: 'flex-end' }}>
            <span style={{ fontSize: 16, fontWeight: 600, color: '#ff4d4f' }}>¥{v.toFixed(2)}</span>
            <span style={{ fontSize: 11, color: '#8c8c8c' }}>{discount}%</span>
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
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      align: 'center',
      render: (v) => {
        const s = STATUS_MAP[v] || { label: v, color: 'default' }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      fixed: 'right',
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/labels/${r.id}`)}>
            详情
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>价签管理</Title>
        <Space>
          {canExport && (
            <Button icon={<DownloadOutlined />} onClick={handleExport}>
              导出 CSV
            </Button>
          )}
          {canSubmit && (
            <Button type="primary" icon={<SendOutlined />} disabled={selectedRowKeys.length === 0} onClick={handleSubmit}>
              提交审批 ({selectedRowKeys.length})
            </Button>
          )}
        </Space>
      </div>

      <Card bodyStyle={{ padding: 0 }}>
        <div className="filter-bar" style={{ padding: '16px 16px 0 16px' }}>
          <Space size={12} wrap style={{ width: '100%' }}>
            <Select
              placeholder="选择状态"
              style={{ width: 140 }}
              allowClear
              value={filters.status || undefined}
              onChange={(v) => setFilters({ ...filters, status: v || '' })}
              options={Object.entries(STATUS_MAP).map(([k, v]) => ({ value: k, label: v.label }))}
            />
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
            <Space>
              <Button type="primary" icon={<SearchOutlined />} onClick={() => loadData(1, pagination.pageSize)}>
                查询
              </Button>
              <Button
                icon={<ReloadOutlined />}
                onClick={() => {
                  setFilters({ status: '', sku: '', store: '' })
                  setSelectedRowKeys([])
                  setTimeout(() => loadData(1, pagination.pageSize), 50)
                }}
              >
                重置
              </Button>
            </Space>
          </Space>
        </div>

        <Table
          rowKey="id"
          columns={columns}
          dataSource={data}
          loading={loading}
          scroll={{ x: 1400 }}
          rowSelection={canSubmit ? {
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            getCheckboxProps: (r) => ({ disabled: r.status !== 'draft' }),
          } : undefined}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条价签`,
            onChange: (p, ps) => loadData(p, ps),
          }}
        />
      </Card>
    </div>
  )
}
