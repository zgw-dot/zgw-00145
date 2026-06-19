import React, { useState, useEffect } from 'react'
import { Table, Tag, Space, Card, Button, Typography, App as AntApp, Switch, Tooltip } from 'antd'
import { ArrowLeftOutlined, CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Paragraph } = Typography

export default function ImportBatchDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [batch, setBatch] = useState(null)
  const [data, setData] = useState([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 50, total: 0 })
  const [loading, setLoading] = useState(false)
  const [onlyInvalid, setOnlyInvalid] = useState(false)

  useEffect(() => {
    loadData(1, 50, onlyInvalid)
  }, [id, onlyInvalid])

  const loadData = async (page, pageSize, invalid) => {
    setLoading(true)
    try {
      const res = await api.get(`/import/batches/${id}?page=${page}&size=${pageSize}&only_invalid=${invalid}`)
      setBatch(res.data.batch)
      setData(res.data.validations.list)
      setPagination({ current: page, pageSize, total: res.data.validations.total })
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const columns = [
    {
      title: '行号',
      dataIndex: 'row_number',
      key: 'row_number',
      width: 80,
      align: 'center',
      render: (v, r) => (
        <Tag color={r.is_valid ? 'green' : 'red'} style={{ minWidth: 50, textAlign: 'center', margin: 0 }}>
          #{v}
        </Tag>
      ),
    },
    {
      title: '校验结果',
      key: 'result',
      width: 110,
      align: 'center',
      render: (_, r) => r.is_valid ? (
        <Tag color="success" icon={<CheckCircleOutlined />}>校验通过</Tag>
      ) : (
        <Tag color="error" icon={<CloseCircleOutlined />}>校验失败</Tag>
      ),
    },
    { title: 'SKU', dataIndex: 'sku', key: 'sku', width: 140, ellipsis: true },
    { title: '门店', dataIndex: 'store', key: 'store', width: 140, ellipsis: true },
    {
      title: '原价',
      dataIndex: 'original_price',
      key: 'original_price',
      width: 100,
      align: 'right',
      render: (v) => v === 0 ? <span style={{ color: '#8c8c8c' }}>-</span> : `¥${v?.toFixed?.(2) ?? v}`,
    },
    {
      title: '促销价',
      dataIndex: 'promotion_price',
      key: 'promotion_price',
      width: 100,
      align: 'right',
      render: (v, r) => {
        const warn = r.original_price > 0 && v > r.original_price
        return (
          <span style={{ color: warn ? '#ff4d4f' : undefined, fontWeight: warn ? 600 : undefined }}>
            {v === 0 ? <span style={{ color: '#8c8c8c' }}>-</span> : `¥${v?.toFixed?.(2) ?? v}`}
          </span>
        )
      },
    },
    {
      title: '生效时段',
      key: 'period',
      width: 360,
      render: (_, r) => (
        <div style={{ fontSize: 12 }}>
          <div>起：{r.effective_from || '-'}</div>
          <div>止：{r.effective_to || '-'}</div>
        </div>
      ),
    },
    { title: '模板', dataIndex: 'template', key: 'template', width: 100 },
    {
      title: '错误信息',
      dataIndex: 'error_message',
      key: 'error_message',
      ellipsis: true,
      render: (v) => v ? (
        <Tooltip title={v}>
          <span style={{ color: '#ff4d4f' }}>{v}</span>
        </Tooltip>
      ) : <span style={{ color: '#8c8c8c' }}>无</span>,
    },
  ]

  return (
    <div>
      <div className="action-bar">
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ paddingLeft: 0 }}>
            返回批次列表
          </Button>
          <Title level={4} style={{ margin: '8px 0 4px 0' }}>
            批次校验详情 <Tag color="blue" style={{ fontSize: 14 }}>{batch?.batch_no}</Tag>
          </Title>
          {batch && (
            <Space size={20} style={{ marginBottom: 0 }}>
              <span>文件：<strong>{batch.filename}</strong></span>
              <span>导入时间：{dayjs(batch.created_at).format('YYYY-MM-DD HH:mm:ss')}</span>
              <Tag color="blue">总行数 {batch.total_rows}</Tag>
              <Tag color="success">通过 {batch.valid_rows}</Tag>
              <Tag color="error">失败 {batch.invalid_rows}</Tag>
            </Space>
          )}
        </div>
        <Space>
          <Space>
            <span>只看失败行</span>
            <Switch checked={onlyInvalid} onChange={(v) => { setOnlyInvalid(v); setPagination(p => ({ ...p, current: 1 })) }} />
          </Space>
          <Button type="primary" onClick={() => navigate('/labels')}>
            去价签管理
          </Button>
        </Space>
      </div>

      <Card bodyStyle={{ padding: 0 }}>
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
            showTotal: (t) => `共 ${t} 行校验记录`,
            onChange: (p, ps) => loadData(p, ps, onlyInvalid),
          }}
        />
      </Card>
    </div>
  )
}
