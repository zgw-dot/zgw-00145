import React, { useState, useEffect } from 'react'
import { Upload, Button, Table, Tag, Space, Card, App as AntApp, Typography, Tooltip, Modal, List, Row, Col } from 'antd'
import {
  UploadOutlined, FileTextOutlined, EyeOutlined, CheckCircleOutlined,
  CloseCircleOutlined, InfoCircleOutlined, DownloadOutlined, ArrowRightOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Paragraph, Text } = Typography

const RowStat = ({ label, value, color }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px dashed #f0f0f0' }}>
    <Text>{label}</Text>
    <Text strong style={{ fontSize: 18, color }}>{value}</Text>
  </div>
)

export default function ImportPage({ user }) {
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()
  const [uploading, setUploading] = useState(false)
  const [data, setData] = useState([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 10, total: 0 })
  const [loading, setLoading] = useState(false)

  const canImport = ['admin', 'operator'].includes(user?.role)

  useEffect(() => {
    loadData(1, 10)
  }, [])

  const loadData = async (page, pageSize) => {
    setLoading(true)
    try {
      const res = await api.get(`/import/batches?page=${page}&size=${pageSize}`)
      setData(res.data.list)
      setPagination({ ...pagination, current: page, pageSize, total: res.data.total })
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const buildModalContent = (d) => {
    const items = (d.validation_results || []).map((v) => ({
      key: v.row_number,
      label: (
        <Space size={12} style={{ width: '100%' }}>
          <Tag color={v.is_valid ? 'success' : 'error'} style={{ minWidth: 60, textAlign: 'center' }}>
            行{v.row_number}
          </Tag>
          <span style={{ flex: 1 }}>
            <Text strong>{(v.parsed || {}).sku || '-'}</Text> / {(v.parsed || {}).store || '-'}
          </span>
          {v.is_valid ? (
            <Tag color="green">校验通过</Tag>
          ) : (
            <Tooltip title={(v.errors || []).join('；')}>
              <Tag color="red">
                {((v.errors || [])[0] || '校验失败').slice(0, 20)}
                {(v.errors || []).length > 1 && ` 等${v.errors.length}项`}
              </Tag>
            </Tooltip>
          )}
        </Space>
      ),
    }))
    return (
      <div>
        <Space size={24} style={{ marginBottom: 16 }}>
          <Tag color="blue" style={{ fontSize: 14, padding: '4px 12px' }}>批次号：{d.batch_no}</Tag>
        </Space>
        <RowStat label="总行数" value={d.total_rows} color="#1677ff" />
        <RowStat label="校验通过" value={d.valid_rows} color="#52c41a" />
        <RowStat label="校验失败" value={d.invalid_rows} color="#ff4d4f" />
        <div style={{ marginTop: 16 }}>
          <Title level={5} style={{ marginBottom: 8 }}>逐行校验结果（前100条）</Title>
          {items.length > 0 ? (
            <List
              size="small"
              dataSource={items}
              style={{ maxHeight: 300, overflowY: 'auto', border: '1px solid #f0f0f0', borderRadius: 6 }}
              renderItem={(item) => (
                <List.Item style={{ padding: '8px 12px', borderBottom: '1px solid #f5f5f5' }}>
                  {item.label}
                </List.Item>
              )}
            />
          ) : null}
          {d.has_more && (
            <Paragraph type="secondary" style={{ marginTop: 8 }}>
              还有更多结果，点击"查看详情"查看完整校验报告
            </Paragraph>
          )}
        </div>
      </div>
    )
  }

  const handleUpload = async (file) => {
    if (!canImport) {
      message.error('没有导入权限')
      return false
    }
    if (!file.name.toLowerCase().endsWith('.csv')) {
      message.error('只支持 CSV 格式文件')
      return false
    }

    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await fetch('/api/import', {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
      const result = await res.json()
      if (!result.success) {
        throw new Error(result.message || '导入失败')
      }
      const d = result.data
      message.success(
        `导入完成：共${d.total_rows}行，通过${d.valid_rows}行，失败${d.invalid_rows}行`
      )
      loadData(pagination.current, pagination.pageSize)

      modal.success({
        title: '导入结果',
        width: 700,
        content: buildModalContent(d),
        okText: '查看详情',
        cancelText: '知道了',
        onOk: () => navigate(`/import/${d.batch_id}`),
      })
    } catch (err) {
      message.error(err.message)
    } finally {
      setUploading(false)
    }
    return false
  }

  const columns = [
    {
      title: '批次号',
      dataIndex: 'batch_no',
      key: 'batch_no',
      width: 200,
      render: (v) => <Tag color="blue">{v}</Tag>,
    },
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      ellipsis: true,
      render: (v) => (
        <Space>
          <FileTextOutlined style={{ color: '#1677ff' }} />
          <span>{v}</span>
        </Space>
      ),
    },
    {
      title: '总行数',
      dataIndex: 'total_rows',
      key: 'total_rows',
      width: 90,
      align: 'center',
      render: (v) => <Text strong>{v}</Text>,
    },
    {
      title: '校验通过',
      dataIndex: 'valid_rows',
      key: 'valid_rows',
      width: 100,
      align: 'center',
      render: (v) => <Tag color="success" icon={<CheckCircleOutlined />}>{v}</Tag>,
    },
    {
      title: '校验失败',
      dataIndex: 'invalid_rows',
      key: 'invalid_rows',
      width: 100,
      align: 'center',
      render: (v, row) => (
        <Tag color={row.invalid_rows > 0 ? 'error' : 'default'} icon={row.invalid_rows > 0 ? <CloseCircleOutlined /> : <CheckCircleOutlined />}>
          {v}
        </Tag>
      ),
    },
    {
      title: '导入时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      fixed: 'right',
      render: (_, row) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/import/${row.id}`)}>
            查看校验
          </Button>
          <Button type="link" size="small" icon={<ArrowRightOutlined />} onClick={() => navigate(`/labels?batch_id=${row.id}`)}>
            对应价签
          </Button>
        </Space>
      ),
    },
  ]

  const downloadTemplate = () => {
    const content = 'SKU,门店,原价,促销价,生效开始时间,生效结束时间,模板\nSKU001,北京朝阳店,99.00,69.00,2026-07-01 00:00:00,2026-07-31 23:59:59,default\nSKU002,上海浦东店,199.00,149.00,2026-06-25 00:00:00,2026-07-15 23:59:59,promotion\n'
    const blob = new Blob(['\uFEFF' + content], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '价签导入模板.csv'
    a.click()
    URL.revokeObjectURL(url)
    message.success('模板已下载')
  }

  return (
    <div>
      <div className="action-bar">
        <div>
          <Title level={4} style={{ margin: 0 }}>导入批次管理</Title>
          <Paragraph type="secondary" style={{ margin: '4px 0 0 0' }}>
            <InfoCircleOutlined /> CSV 字段顺序：SKU、门店、原价、促销价、生效时间（或生效开始时间+生效结束时间）、模板
          </Paragraph>
        </div>
        <Space>
          <Button icon={<DownloadOutlined />} onClick={downloadTemplate}>
            下载模板
          </Button>
          {canImport && (
            <Upload
              beforeUpload={handleUpload}
              showUploadList={false}
              accept=".csv"
              disabled={uploading}
            >
              <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
                {uploading ? '导入中...' : '上传价签 CSV'}
              </Button>
            </Upload>
          )}
        </Space>
      </div>

      <Card bodyStyle={{ padding: 0 }}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={data}
          loading={loading}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => loadData(p, ps),
          }}
        />
      </Card>
    </div>
  )
}
