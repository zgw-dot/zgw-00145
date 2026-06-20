import React, { useState, useEffect } from 'react'
import {
  Card, Button, Space, Typography, Tag, Table, Input, Select,
  App as AntApp,
} from 'antd'
import {
  SearchOutlined, ReloadOutlined, DownloadOutlined,
  HistoryOutlined, EyeOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Text } = Typography
const { Option } = Select

const ROLE_LABEL = {
  admin: '管理员',
  operator: '运营',
  clerk: '店员',
}

const STATUS_MAP = {
  in_progress: { label: '进行中', color: 'processing' },
  completed: { label: '已完成', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

export default function DrillHistoryPage() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [data, setData] = useState([])
  const [loading, setLoading] = useState(false)
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [filters, setFilters] = useState({ status: '', scenario_key: '', role: '' })

  useEffect(() => {
    loadData(1, 20)
  }, [])

  const loadData = async (page, pageSize) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page,
        size: pageSize,
        status: filters.status,
        scenario_key: filters.scenario_key,
        role: filters.role,
      })
      const res = await api.get(`/drill/sessions?${params}`)
      setData(res.data.list || [])
      setPagination({ current: page, pageSize, total: res.data.total || 0 })
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleExport = (id) => {
    window.open(`/api/drill/export/acceptance/${id}`, '_blank')
    message.success('已开始导出')
  }

  const columns = [
    {
      title: '演练编号',
      dataIndex: 'session_no',
      key: 'session_no',
      width: 200,
      render: (v, r) => (
        <Button type="link" size="small" onClick={() => navigate(`/drill/session/${r.id}`)} style={{ padding: 0 }}>
          {v}
        </Button>
      ),
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '场景',
      dataIndex: 'scenario_name',
      key: 'scenario_name',
      width: 180,
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 100,
      render: (v) => <Tag>{ROLE_LABEL[v] || v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v) => {
        const s = STATUS_MAP[v] || { label: v, color: 'default' }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '进度',
      key: 'progress',
      width: 140,
      render: (_, r) => (
        <Text>
          {r.completed_steps}/{r.total_steps}
          {r.failed_steps > 0 && <Text type="danger"> (失败{r.failed_steps})</Text>}
        </Text>
      ),
    },
    {
      title: '创建人',
      key: 'creator',
      width: 100,
      render: (_, r) => r.created_by_name || `ID:${r.created_by}`,
    },
    {
      title: '开始时间',
      dataIndex: 'start_time',
      key: 'start_time',
      width: 160,
      render: (v) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '结束时间',
      dataIndex: 'end_time',
      key: 'end_time',
      width: 160,
      render: (v) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/drill/session/${r.id}`)}>
            查看
          </Button>
          {r.status === 'completed' && (
            <Button type="link" size="small" icon={<DownloadOutlined />} onClick={() => handleExport(r.id)}>
              导出
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>
          <HistoryOutlined style={{ color: '#52c41a' }} /> 演练历史
        </Title>
      </div>

      <Card bodyStyle={{ padding: 0 }}>
        <div className="filter-bar" style={{ padding: '16px 16px 0 16px' }}>
          <Space size={12} wrap>
            <Select
              placeholder="演练状态"
              style={{ width: 140 }}
              allowClear
              value={filters.status || undefined}
              onChange={(v) => setFilters({ ...filters, status: v || '' })}
              options={[
                { value: 'in_progress', label: '进行中' },
                { value: 'completed', label: '已完成' },
              ]}
            />
            <Select
              placeholder="演练场景"
              style={{ width: 200 }}
              allowClear
              value={filters.scenario_key || undefined}
              onChange={(v) => setFilters({ ...filters, scenario_key: v || '' })}
              options={[
                { value: 'handover_full_flow', label: '交接单完整流程演练' },
              ]}
            />
            <Select
              placeholder="角色"
              style={{ width: 120 }}
              allowClear
              value={filters.role || undefined}
              onChange={(v) => setFilters({ ...filters, role: v || '' })}
              options={[
                { value: 'admin', label: '管理员' },
                { value: 'operator', label: '运营' },
                { value: 'clerk', label: '店员' },
              ]}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={() => loadData(1, pagination.pageSize)}>
              查询
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                setFilters({ status: '', scenario_key: '', role: '' })
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
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条记录`,
            onChange: (p, ps) => loadData(p, ps),
          }}
        />
      </Card>
    </div>
  )
}
