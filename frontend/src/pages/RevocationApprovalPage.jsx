import React, { useState, useEffect } from 'react'
import {
  Table, Tag, Space, Card, Button, Input, Select, App as AntApp,
  Typography, Modal, Checkbox, Tabs, Timeline, Descriptions,
  Divider, Row, Col,
} from 'antd'
import {
  SearchOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ReloadOutlined, DownloadOutlined, EyeOutlined, ClockCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Text } = Typography
const { TextArea } = Input
const { TabPane } = Tabs

const STATUS_MAP = {
  draft: { label: '草稿', color: 'default' },
  pending_approval: { label: '待审', color: 'processing' },
  published: { label: '已发布', color: 'success' },
  revoking: { label: '撤销中', color: 'warning' },
  rolled_back: { label: '已回滚', color: 'warning' },
  revoked: { label: '已撤销', color: 'error' },
}

const REQUEST_STATUS_MAP = {
  pending: { label: '待处理', color: 'processing' },
  approved: { label: '已通过', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
}

export default function RevocationApprovalPage({ user }) {
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()
  const [data, setData] = useState([])
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20, total: 0 })
  const [loading, setLoading] = useState(false)
  const [filters, setFilters] = useState({ status: 'pending', sku: '', store: '' })
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [activeTab, setActiveTab] = useState('pending')

  const [rejectOpen, setRejectOpen] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [processing, setProcessing] = useState(false)

  const [detailOpen, setDetailOpen] = useState(false)
  const [detailData, setDetailData] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [offlineNoteRequired, setOfflineNoteRequired] = useState(false)
  const [offlineNote, setOfflineNote] = useState('')
  const [approveComment, setApproveComment] = useState('')
  const [approveOpen, setApproveOpen] = useState(false)

  const isAdmin = user?.role === 'admin'

  useEffect(() => {
    loadData(1, 20, activeTab)
  }, [activeTab])

  const loadData = async (page, pageSize, status) => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        page, pageSize,
        status: status || '',
        sku: filters.sku,
        store: filters.store,
      })
      const res = await api.get(`/revocation-requests?${params}`)
      setData(res.data.list)
      setPagination({ current: page, pageSize, total: res.data.total })
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleTabChange = (key) => {
    setActiveTab(key)
    setSelectedRowKeys([])
  }

  const handleViewDetail = async (record) => {
    setDetailLoading(true)
    setDetailOpen(true)
    try {
      const res = await api.get(`/revocation-requests/${record.id}`)
      setDetailData(res.data)
    } catch (err) {
      message.error(err.message)
    } finally {
      setDetailLoading(false)
    }
  }

  const checkPrintedItems = async (requestIds) => {
    let hasPrinted = false
    for (const rid of requestIds) {
      const req = data.find(d => d.id === rid)
      if (req) {
        try {
          const labelRes = await api.get(`/labels/${req.label_id}`)
          const printQueueRes = await api.get(`/print-queue?status=printed`)
          const printedItems = printQueueRes.data.list.filter(pq => pq.label_id === req.label_id)
          if (printedItems.length > 0) {
            hasPrinted = true
            break
          }
        } catch (e) {
          // ignore
        }
      }
    }
    return hasPrinted
  }

  const handleBatchApprove = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要处理的申请')
      return
    }
    const pendingSelected = data.filter(d => selectedRowKeys.includes(d.id) && d.status === 'pending')
    if (pendingSelected.length === 0) {
      message.warning('请选择待处理状态的申请')
      return
    }

    const hasPrinted = await checkPrintedItems(selectedRowKeys)
    if (hasPrinted) {
      setOfflineNoteRequired(true)
      setOfflineNote('')
      setApproveComment('')
      setApproveOpen(true)
      return
    }

    modal.confirm({
      title: '确认通过撤销申请？',
      icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
      content: (
        <div>
          <p>共选择 <strong>{pendingSelected.length}</strong> 条撤销申请，通过后将：</p>
          <ul style={{ paddingLeft: 20 }}>
            <li>价签状态变更为"已撤销"</li>
            <li>未打印的打印清单项将被移除</li>
            <li>记录撤销操作日志</li>
          </ul>
        </div>
      ),
      okText: '确认通过',
      okButtonProps: { type: 'primary', style: { background: '#52c41a' } },
      onOk: () => doApprove(selectedRowKeys, '', ''),
    })
  }

  const confirmApproveWithNote = () => {
    if (offlineNoteRequired && !offlineNote.trim()) {
      message.warning('存在已打印记录，请填写线下处理说明')
      return
    }
    setApproveOpen(false)
    doApprove(selectedRowKeys, approveComment, offlineNote)
  }

  const doApprove = async (ids, comment, offlineNote) => {
    setProcessing(true)
    let successCount = 0
    let failCount = 0
    const pendingSelected = data.filter(d => ids.includes(d.id) && d.status === 'pending')

    for (const req of pendingSelected) {
      try {
        await api.post(`/revocation-requests/${req.id}/review`, {
          approve: true,
          comment: comment.trim(),
          offline_processing_note: offlineNote.trim(),
        })
        successCount++
      } catch (err) {
        failCount++
        message.error(`申请 #${req.id} 处理失败: ${err.message}`)
      }
    }

    setProcessing(false)
    setSelectedRowKeys([])
    if (successCount > 0) {
      message.success(`成功批准 ${successCount} 条撤销申请`)
    }
    loadData(pagination.current, pagination.pageSize, activeTab)
  }

  const handleBatchReject = () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要处理的申请')
      return
    }
    const pendingSelected = data.filter(d => selectedRowKeys.includes(d.id) && d.status === 'pending')
    if (pendingSelected.length === 0) {
      message.warning('请选择待处理状态的申请')
      return
    }
    setRejectReason('')
    setRejectOpen(true)
  }

  const confirmReject = async () => {
    if (!rejectReason.trim()) {
      message.warning('请填写驳回原因')
      return
    }
    setProcessing(true)
    setRejectOpen(false)
    let successCount = 0
    let failCount = 0
    const pendingSelected = data.filter(d => selectedRowKeys.includes(d.id) && d.status === 'pending')

    for (const req of pendingSelected) {
      try {
        await api.post(`/revocation-requests/${req.id}/review`, {
          approve: false,
          comment: rejectReason.trim(),
        })
        successCount++
      } catch (err) {
        failCount++
        message.error(`申请 #${req.id} 驳回失败: ${err.message}`)
      }
    }

    setProcessing(false)
    setSelectedRowKeys([])
    if (successCount > 0) {
      message.success(`成功驳回 ${successCount} 条撤销申请`)
    }
    loadData(pagination.current, pagination.pageSize, activeTab)
  }

  const handleSingleApprove = async (record) => {
    if (record.status !== 'pending') {
      message.warning('只有待处理状态的申请可以审批')
      return
    }

    let hasPrinted = false
    try {
      const printQueueRes = await api.get(`/print-queue?status=printed`)
      const printedItems = printQueueRes.data.list.filter(pq => pq.label_id === record.label_id)
      hasPrinted = printedItems.length > 0
    } catch (e) {
      // ignore
    }

    if (hasPrinted) {
      setSelectedRowKeys([record.id])
      setOfflineNoteRequired(true)
      setOfflineNote('')
      setApproveComment('')
      setApproveOpen(true)
      return
    }

    modal.confirm({
      title: '确认通过该撤销申请？',
      icon: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
      content: (
        <div>
          <p>通过后将：</p>
          <ul style={{ paddingLeft: 20 }}>
            <li>价签状态变更为"已撤销"</li>
            <li>未打印的打印清单项将被移除</li>
            <li>记录撤销操作日志</li>
          </ul>
        </div>
      ),
      okText: '确认通过',
      okButtonProps: { type: 'primary', style: { background: '#52c41a' } },
      onOk: () => doApprove([record.id], '', ''),
    })
  }

  const handleSingleReject = (record) => {
    if (record.status !== 'pending') {
      message.warning('只有待处理状态的申请可以审批')
      return
    }
    setSelectedRowKeys([record.id])
    setRejectReason('')
    setRejectOpen(true)
  }

  const handleExport = () => {
    const params = new URLSearchParams({
      status: activeTab === 'all' ? '' : activeTab,
      sku: filters.sku,
      store: filters.store,
    })
    window.open(`/api/export/revocation-requests?${params}`, '_blank')
    message.success('已开始导出')
  }

  const columns = [
    {
      title: '申请ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
    },
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
      width: 140,
      render: (v) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
    },
    { title: '门店', dataIndex: 'store', key: 'store', width: 140 },
    {
      title: '申请时状态',
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
      title: '申请状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      align: 'center',
      render: (v) => {
        const s = REQUEST_STATUS_MAP[v] || { label: v, color: 'default' }
        return <Tag color={s.color}>{s.label}</Tag>
      },
    },
    {
      title: '申请原因',
      dataIndex: 'reason',
      key: 'reason',
      ellipsis: true,
      render: (v) => v || '-',
    },
    {
      title: '申请人',
      key: 'requester',
      width: 120,
      render: (_, r) => r.requested_by_name || `ID:${r.requested_by}`,
    },
    {
      title: '申请时间',
      dataIndex: 'requested_at',
      key: 'requested_at',
      width: 170,
      render: (v) => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      fixed: 'right',
      render: (_, r) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(r)}>
            详情
          </Button>
          <Button type="link" size="small" onClick={() => navigate(`/labels/${r.label_id}`)}>
            价签
          </Button>
          {isAdmin && r.status === 'pending' && (
            <>
              <Button type="link" size="small" style={{ color: '#52c41a' }} onClick={() => handleSingleApprove(r)}>
                通过
              </Button>
              <Button type="link" size="small" danger onClick={() => handleSingleReject(r)}>
                驳回
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ]

  const tabItems = [
    { key: 'pending', label: '待处理' },
    { key: 'approved', label: '已通过' },
    { key: 'rejected', label: '已驳回' },
    { key: 'all', label: '全部' },
  ]

  return (
    <div>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>
          撤销申请审批
        </Title>
        {isAdmin ? (
          <Space>
            <Button icon={<DownloadOutlined />} onClick={handleExport}>
              导出 CSV
            </Button>
            <Button
              danger
              icon={<CloseCircleOutlined />}
              disabled={data.filter(d => selectedRowKeys.includes(d.id) && d.status === 'pending').length === 0}
              onClick={handleBatchReject}
            >
              批量驳回 ({data.filter(d => selectedRowKeys.includes(d.id) && d.status === 'pending').length})
            </Button>
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              disabled={data.filter(d => selectedRowKeys.includes(d.id) && d.status === 'pending').length === 0}
              onClick={handleBatchApprove}
              style={{ background: '#52c41a', borderColor: '#52c41a' }}
            >
              批量通过 ({data.filter(d => selectedRowKeys.includes(d.id) && d.status === 'pending').length})
            </Button>
          </Space>
        ) : (
          <Tag color="warning">当前账号无审批权限（仅管理员可审批）</Tag>
        )}
      </div>

      <Card bodyStyle={{ padding: 0 }}>
        <Tabs
          activeKey={activeTab}
          onChange={handleTabChange}
          items={tabItems}
          style={{ padding: '0 16px' }}
        />

        <div className="filter-bar" style={{ padding: '0 16px 16px 16px' }}>
          <Space size={12} wrap>
            <Input
              placeholder="搜索 SKU"
              prefix={<SearchOutlined />}
              style={{ width: 200 }}
              allowClear
              value={filters.sku}
              onChange={(e) => setFilters({ ...filters, sku: e.target.value })}
              onPressEnter={() => loadData(1, pagination.pageSize, activeTab)}
            />
            <Input
              placeholder="搜索门店"
              prefix={<SearchOutlined />}
              style={{ width: 200 }}
              allowClear
              value={filters.store}
              onChange={(e) => setFilters({ ...filters, store: e.target.value })}
              onPressEnter={() => loadData(1, pagination.pageSize, activeTab)}
            />
            <Button type="primary" icon={<SearchOutlined />} onClick={() => loadData(1, pagination.pageSize, activeTab)}>
              查询
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                setFilters({ sku: '', store: '', status: 'pending' })
                setSelectedRowKeys([])
                setTimeout(() => loadData(1, pagination.pageSize, activeTab), 50)
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
          rowSelection={isAdmin && activeTab === 'pending' ? {
            selectedRowKeys,
            onChange: setSelectedRowKeys,
            getCheckboxProps: (r) => ({ disabled: r.status !== 'pending' }),
          } : undefined}
          pagination={{
            ...pagination,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (t) => `共 ${t} 条申请`,
            onChange: (p, ps) => loadData(p, ps, activeTab),
          }}
        />
      </Card>

      <Modal
        title={`驳回 ${data.filter(d => selectedRowKeys.includes(d.id) && d.status === 'pending').length} 条撤销申请`}
        open={rejectOpen}
        onCancel={() => { setRejectOpen(false); setRejectReason('') }}
        onOk={confirmReject}
        okText="确认驳回"
        okButtonProps={{ danger: true }}
        confirmLoading={processing}
        destroyOnClose
        width={520}
      >
        <div style={{ marginBottom: 12 }}>请填写驳回原因：</div>
        <TextArea
          rows={4}
          value={rejectReason}
          onChange={(e) => setRejectReason(e.target.value)}
          placeholder="例如：经核实，促销活动仍在有效期内，无需撤销"
          showCount
          maxLength={200}
        />
      </Modal>

      <Modal
        title="批准撤销申请"
        open={approveOpen}
        onCancel={() => { setApproveOpen(false); setOfflineNoteRequired(false); setOfflineNote(''); setApproveComment('') }}
        onOk={confirmApproveWithNote}
        okText="确认批准"
        okButtonProps={{ type: 'primary', style: { background: '#52c41a' } }}
        confirmLoading={processing}
        destroyOnClose
        width={560}
      >
        {offlineNoteRequired && (
          <div style={{ marginBottom: 16, padding: 12, background: '#fff2f0', borderRadius: 6, border: '1px solid #ffccc7' }}>
            <Text type="danger" strong>
              <ExclamationCircleOutlined /> 存在已打印记录，请填写线下处理说明
            </Text>
            <div style={{ marginTop: 8, fontSize: 12, color: '#8c8c8c' }}>
              请说明已打印价签的回收、销毁等处理方式
            </div>
          </div>
        )}
        <div style={{ marginBottom: 12 }}>
          <Text strong>线下处理说明{offlineNoteRequired ? '（必填）' : '（选填）'}</Text>
        </div>
        <TextArea
          rows={3}
          value={offlineNote}
          onChange={(e) => setOfflineNote(e.target.value)}
          placeholder="例如：已通知门店回收全部已打印价签并销毁"
          showCount
          maxLength={200}
          style={{ marginBottom: 16 }}
        />
        <div style={{ marginBottom: 12 }}>
          <Text strong>审批意见（选填）</Text>
        </div>
        <TextArea
          rows={3}
          value={approveComment}
          onChange={(e) => setApproveComment(e.target.value)}
          placeholder="例如：情况属实，同意撤销"
          showCount
          maxLength={200}
        />
      </Modal>

      <Modal
        title="撤销申请详情"
        open={detailOpen}
        onCancel={() => { setDetailOpen(false); setDetailData(null) }}
        width={800}
        footer={[
          <Button key="close" onClick={() => { setDetailOpen(false); setDetailData(null) }}>
            关闭
          </Button>,
        ]}
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>加载中...</div>
        ) : detailData ? (
          <div>
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={12}>
                <Card title="申请信息" size="small">
                  <Descriptions column={1} bordered size="small">
                    <Descriptions.Item label="申请状态">
                      {REQUEST_STATUS_MAP[detailData.request.status] && (
                        <Tag color={REQUEST_STATUS_MAP[detailData.request.status].color}>
                          {REQUEST_STATUS_MAP[detailData.request.status].label}
                        </Tag>
                      )}
                    </Descriptions.Item>
                    <Descriptions.Item label="申请原因">
                      {detailData.request.reason || '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="申请时间">
                      {detailData.request.requested_at ? dayjs(detailData.request.requested_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="申请人">
                      {detailData.request.requested_by_name || `ID:${detailData.request.requested_by}`}
                    </Descriptions.Item>
                    {detailData.request.status !== 'pending' && (
                      <>
                        <Descriptions.Item label="处理时间">
                          {detailData.request.reviewed_at ? dayjs(detailData.request.reviewed_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
                        </Descriptions.Item>
                        <Descriptions.Item label="处理人">
                          {detailData.request.reviewed_by_name || `ID:${detailData.request.reviewed_by}`}
                        </Descriptions.Item>
                        <Descriptions.Item label="处理意见">
                          {detailData.request.review_comment || '-'}
                        </Descriptions.Item>
                        {detailData.request.offline_processing_note && (
                          <Descriptions.Item label="线下处理说明">
                            {detailData.request.offline_processing_note}
                          </Descriptions.Item>
                        )}
                      </>
                    )}
                  </Descriptions>
                </Card>
              </Col>
              <Col xs={24} lg={12}>
                <Card title="价签信息" size="small">
                  <Descriptions column={1} bordered size="small">
                    <Descriptions.Item label="价签ID">
                      <Button type="link" size="small" onClick={() => navigate(`/labels/${detailData.request.label_id}`)}>
                        #{detailData.request.label_id}
                      </Button>
                    </Descriptions.Item>
                    <Descriptions.Item label="SKU">
                      <span style={{ fontFamily: 'monospace' }}>{detailData.request.sku}</span>
                    </Descriptions.Item>
                    <Descriptions.Item label="门店">{detailData.request.store}</Descriptions.Item>
                    <Descriptions.Item label="申请时状态">
                      {STATUS_MAP[detailData.request.original_status] && (
                        <Tag color={STATUS_MAP[detailData.request.original_status].color}>
                          {STATUS_MAP[detailData.request.original_status].label}
                        </Tag>
                      )}
                    </Descriptions.Item>
                    {detailData.request.affected_print_queue_ids && (
                      <Descriptions.Item label="受影响打印清单">
                        {detailData.request.affected_print_queue_ids}
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                </Card>
              </Col>
            </Row>

            <Divider />

            <Card title="操作日志" size="small" style={{ marginTop: 16 }}>
              <Timeline
                items={detailData.logs.map(log => ({
                  color: log.action === 'submit' ? 'blue' : log.action === 'approve' ? 'green' : 'red',
                  children: (
                    <div>
                      <div>
                        <Text strong>
                          {log.action === 'submit' && '提交申请'}
                          {log.action === 'approve' && '批准撤销'}
                          {log.action === 'reject' && '驳回申请'}
                        </Text>
                      </div>
                      <div style={{ marginTop: 4 }}>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {log.operated_by_name || `ID:${log.operated_by}`} · {log.created_at ? dayjs(log.created_at).format('YYYY-MM-DD HH:mm:ss') : ''}
                        </Text>
                      </div>
                      {log.reason && (
                        <div style={{ marginTop: 8, padding: '8px 12px', background: '#f5f5f5', borderRadius: 4 }}>
                          {log.reason}
                        </div>
                      )}
                    </div>
                  ),
                }))}
              />
            </Card>
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
