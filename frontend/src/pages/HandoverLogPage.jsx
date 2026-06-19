import React, { useState, useEffect } from 'react'
import {
  Table, Tag, Space, Card, Button, Input, Select, App as AntApp,
  Typography,
} from 'antd'
import { SearchOutlined, ReloadOutlined, SwapOutlined, DownloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title } = Typography

const ACTION_MAP = {
  create: { label: '创建', color: 'blue' },
  sign: { label: '签收', color: 'green' },
  void: { label: '作废', color: 'red' },
  check_conflict: { label: '冲突检查', color: 'orange' },
  conflict_auto_mark: { label: '冲突自动标记', color: 'volcano' },
}

export default function HandoverLogPage() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [data, setData] = useState([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ sheet_no: '', action: '' })

  useEffect(() => { loadData(1, 20) }, [])

  const loadData = async (page, pageSize) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page, size: pageSize,
        sheet_no: filters.sheet_no,
        action: filters.action,
      })
      const res = await api.get(`/handover-logs?${params}`)
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
      sheet_no: filters.sheet_no,
      action: filters.action,
    })
    window.open(`/api/export/handover-logs?${params}`, '_blank')
    message.success('已开始导出')
  }

  const columns = [
    {
      title: '记录ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
    },
    {
      title: '交接单号',
      dataIndex: 'sheet_no',
      key: 'sheet_no',
      width: 200,
      render: (v, r) => (
        <Button type="link" size="small" onClick={() => navigate(`/handover-sheets/${r.sheet_id}`)} style={{ padding: 0 }}>
          {v}
        </Button>
      ),
    },
    {
      title: '操作类型',
      dataIndex: 'action',
      key: 'action',
      width: 130,
      align: 'center',
      render: (v) => {
        const info = ACTION_MAP[v] || { label: v, color: 'default' }
        return <Tag color={info.color}>{info.label}</Tag>
      },
    },
    {
      title: '操作详情',
      dataIndex: 'detail',
      key: 'detail',
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
      title: '操作时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
  ]

  return (
    <div>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>
          <SwapOutlined style={{ color: '#1677ff' }} /> 交接单日志
        </Title>
        <Button type="primary" icon={<DownloadOutlined />} onClick={handleExport}>
          导出 CSV
        </Button>
      </div>

      <Card bodyStyle={{ padding: 0 }}>
        <div className="filter-bar" style={{ padding: '16px 16px 0 16px' }}>
          <Space size={12} wrap>
            <Input
              placeholder="搜索交接单号"
              prefix={<SearchOutlined />}
              style={{ width: 220 }}
              allowClear
              value={filters.sheet_no}
              onChange={(e) => setFilters({ ...filters, sheet_no: e.target.value })}
              onPressEnter={() => loadData(1, pagination.pageSize)}
            />
            <Select
              placeholder="操作类型"
              style={{ width: 160 }}
              allowClear
              value={filters.action || undefined}
              onChange={(v) => setFilters({ ...filters, action: v || '' })}
              options={Object.entries(ACTION_MAP).map(([k, v]) => ({ value: k, label: v.label }))}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={() => loadData(1, pagination.pageSize)}>
              查询
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                setFilters({ sheet_no: '', action: '' })
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
          scroll={{ x: 1000 }}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条日志`,
            onChange: (p, ps) => loadData(p, ps),
          }}
        />
      </Card>
    </div>
  )
}
