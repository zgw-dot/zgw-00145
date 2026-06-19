import React, { useState, useEffect } from 'react'
import {
  Table, Tag, Space, Card, Button, Input, App as AntApp,
  Typography,
} from 'antd'
import { SearchOutlined, ReloadOutlined, StopOutlined, DownloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title } = Typography

const STATUS_MAP = {
  draft: { label: '草稿', color: 'default' },
  pending_approval: { label: '待审', color: 'processing' },
  published: { label: '已发布', color: 'success' },
  rolled_back: { label: '已回滚', color: 'warning' },
  revoked: { label: '已撤销', color: 'error' },
}

export default function RevocationLogPage() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [data, setData] = useState([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ sku: '', store: '' })

  useEffect(() => { loadData(1, 20) }, [filters])

  const loadData = async (page, pageSize) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page, pageSize,
        sku: filters.sku,
        store: filters.store,
      })
      const res = await api.get(`/revocation-logs?${params}`)
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
      sku: filters.sku,
      store: filters.store,
    })
    window.open(`/api/export/revocation-logs?${params}`, '_blank')
    message.success('已开始导出')
  }

  const columns = [
    { title: '记录ID', dataIndex: 'id', key: 'id', width: 80 },
    {
      title: '撤销时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    { title: 'SKU', dataIndex: 'sku', key: 'sku', width: 140, render: v => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
    { title: '门店', dataIndex: 'store', key: 'store', width: 140 },
    {
      title: '原状态',
      dataIndex: 'original_status',
      key: 'original_status',
      width: 100,
      align: 'center',
      render: (v) => {
        const s = STATUS_MAP[v] || { label: v, color: 'default' }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '撤销原因',
      dataIndex: 'reason',
      key: 'reason',
      ellipsis: true,
      render: (v) => v || '-',
    },
    {
      title: '操作人',
      key: 'operator',
      width: 120,
      render: (_, r) => r.operated_by_name || `ID:${r.operated_by}`,
    },
    {
      title: '受影响打印清单ID',
      dataIndex: 'affected_print_queue_ids',
      key: 'affected_print_queue_ids',
      width: 160,
      render: (v) => v || '无',
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
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
        <Title level={4} style={{ margin: 0 }}>
          <StopOutlined style={{ color: '#ff4d4f' }} /> 撤销日志
        </Title>
        <Button type="primary" icon={<DownloadOutlined />} onClick={handleExport}>
          导出 CSV
        </Button>
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
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条撤销记录`,
            onChange: (p, ps) => loadData(p, ps),
          }}
        />
      </Card>
    </div>
  )
}
