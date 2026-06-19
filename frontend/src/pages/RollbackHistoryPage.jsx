import React, { useState, useEffect } from 'react'
import {
  Table, Tag, Space, Card, Button, Input, App as AntApp,
  Typography,
} from 'antd'
import { SearchOutlined, ReloadOutlined, UndoOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title } = Typography

export default function RollbackHistoryPage() {
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
      const res = await api.get(`/rollback-history?${params}`)
      setData(res.data.list)
      setPagination({ current: page, pageSize, total: res.data.total })
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const STATUS_MAP = {
    draft: { label: '草稿', color: 'default' },
    pending_approval: { label: '待审', color: 'processing' },
    published: { label: '已发布', color: 'success' },
    rolled_back: { label: '已回滚', color: 'warning' },
  }

  const columns = [
    { title: '记录ID', dataIndex: 'id', key: 'id', width: 80 },
    {
      title: '操作时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    { title: 'SKU', dataIndex: 'sku', key: 'sku', width: 140, render: v => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
    { title: '门店', dataIndex: 'store', key: 'store', width: 140 },
    {
      title: '版本变更',
      key: 'version',
      width: 180,
      align: 'center',
      render: (_, r) => (
        <Space size={4}>
          <Tag>v{r.from_version}</Tag>
          <span style={{ color: '#8c8c8c' }}>→</span>
          <Tag color="blue">v{r.to_version}</Tag>
        </Space>
      ),
    },
    {
      title: '状态变更',
      key: 'status',
      width: 200,
      align: 'center',
      render: (_, r) => {
        const fs = STATUS_MAP[r.from_status] || { label: r.from_status, color: 'default' }
        const ts = STATUS_MAP[r.to_status] || { label: r.to_status, color: 'default' }
        return (
          <Space size={4}>
            <Tag color={fs.color}>{fs.label}</Tag>
            <span style={{ color: '#8c8c8c' }}>→</span>
            <Tag color={ts.color}>{ts.label}</Tag>
          </Space>
        )
      },
    },
    {
      title: '回滚原因',
      dataIndex: 'reason',
      key: 'reason',
      ellipsis: true,
      render: (v) => v || '-',
    },
    {
      title: '操作人ID',
      dataIndex: 'operated_by',
      key: 'operated_by',
      width: 100,
      align: 'center',
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
          <UndoOutlined style={{ color: '#eb2f96' }} /> 回滚历史记录
        </Title>
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
          scroll={{ x: 1300 }}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条回滚记录`,
            onChange: (p, ps) => loadData(p, ps),
          }}
        />
      </Card>
    </div>
  )
}
