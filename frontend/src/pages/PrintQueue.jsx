import React, { useState, useEffect } from 'react'
import {
  Table, Tag, Space, Card, Button, Input, Select, App as AntApp,
  Typography,
} from 'antd'
import {
  SearchOutlined, PrinterOutlined, CheckCircleOutlined,
  ReloadOutlined, DownloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title } = Typography

export default function PrintQueue({ user }) {
  const { message } = AntApp.useApp()
  const [data, setData] = useState([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 50, total: 0 })
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ status: '', store: '' })
  const [selectedRowKeys, setSelectedRowKeys] = useState([])

  const canMark = ['admin', 'operator', 'clerk'].includes(user?.role)

  useEffect(() => { loadData(1, 50) }, [filters])

  const loadData = async (page, pageSize) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page, pageSize,
        status: filters.status,
        store: filters.store,
      })
      const res = await api.get(`/print-queue?${params}`)
      setData(res.data.list)
      setPagination({ current: page, pageSize, total: res.data.total })
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleMarkPrinted = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要标记的记录')
      return
    }
    try {
      const res = await api.post('/print-queue/mark-printed', { ids: selectedRowKeys })
      message.success(`已标记 ${res.data.count} 条为已打印`)
      setSelectedRowKeys([])
      loadData(pagination.current, pagination.pageSize)
    } catch (err) {
      message.error(err.message)
    }
  }

  const handleExport = () => {
    const params = new URLSearchParams({
      status: filters.status,
      store: filters.store,
    })
    window.open(`/api/export/print-queue?${params}`, '_blank')
    message.success('已开始导出')
  }

  const columns = [
    {
      title: '打印状态',
      dataIndex: 'status',
      key: 'status',
      width: 110,
      align: 'center',
      fixed: 'left',
      render: (v) => v === 'printed'
        ? <Tag color="success" icon={<CheckCircleOutlined />}>已打印</Tag>
        : <Tag color="processing" icon={<PrinterOutlined />}>待打印</Tag>,
    },
    {
      title: 'SKU',
      dataIndex: 'sku',
      key: 'sku',
      width: 140,
      render: (v) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
    },
    { title: '门店', dataIndex: 'store', key: 'store', width: 140 },
    {
      title: '原价',
      dataIndex: 'original_price',
      key: 'original_price',
      width: 100,
      align: 'right',
      render: (v) => <span style={{ textDecoration: 'line-through', color: '#8c8c8c' }}>¥{v.toFixed(2)}</span>,
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
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '打印时间',
      dataIndex: 'printed_at',
      key: 'printed_at',
      width: 160,
      render: (v) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
  ]

  return (
    <div>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>打印清单</Title>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={handleExport}>
            导出 CSV
          </Button>
          {canMark && (
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              disabled={selectedRowKeys.length === 0}
              onClick={handleMarkPrinted}
            >
              标记为已打印 ({selectedRowKeys.length})
            </Button>
          )}
        </Space>
      </div>

      <Card bodyStyle={{ padding: 0 }}>
        <div className="filter-bar" style={{ padding: '16px 16px 0 16px' }}>
          <Space size={12} wrap>
            <Select
              placeholder="打印状态"
              style={{ width: 140 }}
              allowClear
              value={filters.status || undefined}
              onChange={(v) => setFilters({ ...filters, status: v || '' })}
              options={[
                { value: 'pending', label: '待打印' },
                { value: 'printed', label: '已打印' },
              ]}
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
                setFilters({ status: '', store: '' })
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
          scroll={{ x: 1400 }}
          rowSelection={canMark ? {
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            getCheckboxProps: (r) => ({ disabled: r.status === 'printed' }),
          } : undefined}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条打印记录`,
            onChange: (p, ps) => loadData(p, ps),
          }}
        />
      </Card>
    </div>
  )
}
