import React, { useState, useEffect, useMemo } from 'react'
import {
  Card, Row, Col, Statistic, Table, Button, Space, Tag, Modal, Form,
  Select, Input, App as AntApp, Typography, Descriptions,
  Divider, Alert, Timeline, List, Empty, Input as AntInput,
} from 'antd'
import {
  VideoCameraOutlined, SearchOutlined, ReloadOutlined,
  DownloadOutlined, FileTextOutlined, SafetyOutlined,
  CheckCircleOutlined, StopOutlined, EyeOutlined,
  SwapOutlined, KeyOutlined, RollbackOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { authStationApi, exportApi, handoverApi } from '../utils/api.js'

const { Title, Text } = Typography
const { TextArea } = AntInput

const ACTION_CN = {
  create: { label: '创建交接单', color: '#1677ff', icon: <SwapOutlined /> },
  assign: { label: '指派接手人', color: '#52c41a', icon: <EyeOutlined /> },
  authorize_sign: { label: '生成签收凭证', color: '#722ed1', icon: <KeyOutlined /> },
  authorize_view: { label: '生成查看凭证', color: '#13c2c2', icon: <KeyOutlined /> },
  authorize_receipt: { label: '生成回执凭证', color: '#eb2f96', icon: <KeyOutlined /> },
  validate_token: { label: '校验凭证', color: '#fa8c16', icon: <CheckCircleOutlined /> },
  revoke_auth: { label: '撤回授权', color: '#ff4d4f', icon: <StopOutlined /> },
  revoke_sign: { label: '撤回签收', color: '#fa541c', icon: <RollbackOutlined /> },
  reopen: { label: '重开交接单', color: '#2f54eb', icon: <ReloadOutlined /> },
  sign: { label: '签收交接单', color: '#52c41a', icon: <CheckCircleOutlined /> },
  view_detail: { label: '查看详情', color: '#1890ff', icon: <EyeOutlined /> },
  void: { label: '作废交接单', color: '#8c8c8c', icon: <StopOutlined /> },
  check_conflict: { label: '冲突检查', color: '#faad14', icon: <SafetyOutlined /> },
}

export default function HandoverPlayback({ user }) {
  const { message, modal } = AntApp.useApp()

  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const [stats, setStats] = useState({ total: 0, allowed: 0, blocked: 0 })
  const [filters, setFilters] = useState({ sheet_no: '', action: '', result: '', user_name: '', block_code: '' })
  const [timelineSheet, setTimelineSheet] = useState(null)
  const [timelineLoading, setTimelineLoading] = useState(false)
  const [timelineData, setTimelineData] = useState(null)
  const [searchSheetId, setSearchSheetId] = useState('')
  const [searchSheetNo, setSearchSheetNo] = useState('')

  useEffect(() => { loadLogs() }, [filters])

  const loadLogs = async (page = 1, size = 100) => {
    setLoading(true)
    try {
      const params = { ...filters, page, size }
      Object.keys(params).forEach(k => !params[k] && delete params[k])
      const res = await authStationApi.listAuditLogs(params)
      setLogs(res.data?.list || res.data || [])
      setStats({
        total: res.data?.total || 0,
        allowed: res.data?.allowed_count || 0,
        blocked: res.data?.blocked_count || 0,
      })
    } catch (err) {
      message.error(err.message || '加载审计日志失败')
    } finally {
      setLoading(false)
    }
  }

  const loadTimeline = async () => {
    if (!searchSheetId && !searchSheetNo) {
      message.warning('请输入交接单ID或交接单号')
      return
    }
    setTimelineLoading(true)
    setTimelineSheet(searchSheetId || searchSheetNo)
    try {
      const params = {}
      if (searchSheetId) params.sheet_id = parseInt(searchSheetId)
      if (searchSheetNo) params.sheet_no = searchSheetNo
      const res = await authStationApi.auditTimeline(params)
      setTimelineData(res.data)
    } catch (err) {
      message.error(err.message || '加载回放失败')
    } finally {
      setTimelineLoading(false)
    }
  }

  const actionOptions = useMemo(() => {
    const keys = new Set(logs.map(l => l.action))
    return Array.from(keys).map(k => ({ value: k, label: ACTION_CN[k]?.label || k }))
  }, [logs])

  const blockCodeOptions = useMemo(() => {
    const keys = new Set(logs.filter(l => l.block_code).map(l => l.block_code))
    return Array.from(keys).map(k => ({ value: k, label: k }))
  }, [logs])

  const logColumns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      fixed: 'left',
      render: v => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '—',
    },
    {
      title: '操作类型',
      dataIndex: 'action',
      key: 'action',
      width: 130,
      render: v => {
        const info = ACTION_CN[v] || {}
        return (
          <Tag color={info.color} icon={info.icon}>
            {info.label || v}
          </Tag>
        )
      },
    },
    {
      title: '结果',
      dataIndex: 'result',
      key: 'result',
      width: 80,
      render: v => {
        if (v === 'allowed') return <Tag color="green" icon={<CheckCircleOutlined />}>放行</Tag>
        if (v === 'blocked') return <Tag color="red" icon={<StopOutlined />}>拦截</Tag>
        return <Tag>{v}</Tag>
      },
    },
    {
      title: '拦截码',
      dataIndex: 'block_code',
      key: 'block_code',
      width: 180,
      render: v => v ? <Text code style={{ color: '#ff4d4f' }}>{v}</Text> : '—',
    },
    {
      title: '用户',
      dataIndex: 'user_name',
      key: 'user_name',
      width: 90,
      render: (v, r) => v ? (
        <Space direction="vertical" size={0} style={{ lineHeight: 1.3 }}>
          <span>{v}</span>
          <span style={{ fontSize: 11, color: '#999' }}>{r.user_role}</span>
        </Space>
      ) : '匿名',
    },
    { title: '交接单号', dataIndex: 'sheet_no', key: 'sheet_no', width: 180,
      render: v => v || '—'
    },
    { title: '客户端IP', dataIndex: 'client_ip', key: 'client_ip', width: 120, render: v => v || '—' },
    {
      title: '详情',
      dataIndex: 'detail',
      key: 'detail',
      ellipsis: true,
      render: (v, r) => (
        <div>
          {r.block_reason && <div style={{ color: '#ff4d4f' }}>拦截：{r.block_reason}</div>}
          {v && <div style={{ color: '#666' }}>{v}</div>}
          {!r.block_reason && !v && <span style={{ color: '#999' }}>—</span>}
        </div>
      ),
    },
    { title: 'HTTP状态', dataIndex: 'response_status', key: 'response_status', width: 90,
      render: v => v ? (
        <Tag color={v < 400 ? 'green' : v < 500 ? 'orange' : 'red'}>{v}</Tag>
      ) : '—'
    },
    {
      title: '原始请求',
      key: 'raw',
      width: 100,
      fixed: 'right',
      render: (_, r) => (
        <Button
          size="small"
          icon={<FileTextOutlined />}
          onClick={() => showRawDetail(r)}
        >
          查看
        </Button>
      ),
    },
  ]

  const showRawDetail = (log) => {
    modal.info({
      title: `原始请求详情 - ${log.id}`,
      width: 720,
      content: (
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="请求路径">
            {log.request_method} {log.request_path || '—'}
          </Descriptions.Item>
          <Descriptions.Item label="请求参数">
            {log.request_params ? (
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{log.request_params}</pre>
            ) : <Text type="secondary">(无)</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="请求体">
            {log.request_body ? (
              <TextArea
                autoSize={{ minRows: 3, maxRows: 8 }}
                value={log.request_body}
                readOnly
                style={{ fontFamily: 'monospace', fontSize: 12 }}
              />
            ) : <Text type="secondary">(无)</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="响应状态">{log.response_status || '—'}</Descriptions.Item>
          <Descriptions.Item label="响应消息">
            {log.response_message || <Text type="secondary">(无)</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="拦截原因">
            {log.block_reason || <Text type="secondary">(无)</Text>}
          </Descriptions.Item>
          <Descriptions.Item label="用户代理">
            {log.user_agent ? (
              <Text style={{ fontSize: 12, wordBreak: 'break-all' }} copyable>
                {log.user_agent}
              </Text>
            ) : <Text type="secondary">(无)</Text>}
          </Descriptions.Item>
        </Descriptions>
      ),
      okText: '关闭',
    })
  }

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card>
          <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}>
            <Space>
              <VideoCameraOutlined style={{ fontSize: 28, color: '#722ed1' }} />
              <div>
                <Title level={4} style={{ margin: 0 }}>审计回放台</Title>
                <Text type="secondary">
                  全链路事件溯源：查看每一次授权、签收、拦截、撤回的人、时间、原因、原始请求
                </Text>
              </div>
            </Space>
            <Space>
              <Button onClick={loadLogs} icon={<ReloadOutlined />}>刷新</Button>
              {user?.role === 'admin' && (
                <Button onClick={() => exportApi.auditLogs()} icon={<DownloadOutlined />} type="primary">
                  导出CSV
                </Button>
              )}
            </Space>
          </Space>
        </Card>

        <Row gutter={16}>
          <Col span={8}>
            <Card>
              <Statistic
                title="审计记录总数"
                value={stats.total}
                prefix={<FileTextOutlined />}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="放行次数"
                value={stats.allowed}
                valueStyle={{ color: '#52c41a' }}
                prefix={<CheckCircleOutlined />}
              />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic
                title="拦截次数"
                value={stats.blocked}
                valueStyle={{ color: '#ff4d4f' }}
                prefix={<StopOutlined />}
              />
            </Card>
          </Col>
        </Row>

        <Card
          title={<Space><VideoCameraOutlined />按交接单时间线回放</Space>}
          style={{ borderColor: '#722ed1' }}
          extra={
            <Space>
              <Input
                placeholder="输入交接单ID"
                style={{ width: 160 }}
                value={searchSheetId}
                onChange={e => setSearchSheetId(e.target.value)}
                allowClear
              />
              <Input
                placeholder="或交接单号"
                style={{ width: 200 }}
                value={searchSheetNo}
                onChange={e => setSearchSheetNo(e.target.value)}
                allowClear
                onPressEnter={loadTimeline}
              />
              <Button type="primary" onClick={loadTimeline} icon={<SearchOutlined />} loading={timelineLoading}>
                查询时间线
              </Button>
            </Space>
          }
        >
          {!timelineData && !timelineLoading ? (
            <Empty
              description="输入交接单ID或单号，查看该交接单的完整授权/签收/撤回时间线"
              style={{ padding: 24 }}
            />
          ) : timelineLoading ? (
            <div style={{ textAlign: 'center', padding: 40 }}>加载中...</div>
          ) : (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              {timelineData.sheet && (
                <Card size="small" title="交接单概览">
                  <Descriptions size="small" column={3} bordered>
                    <Descriptions.Item label="交接单号">{timelineData.sheet.sheet_no}</Descriptions.Item>
                    <Descriptions.Item label="标题">{timelineData.sheet.title}</Descriptions.Item>
                    <Descriptions.Item label="门店">{timelineData.sheet.store}</Descriptions.Item>
                    <Descriptions.Item label="状态">
                      <Tag color={
                        timelineData.sheet.status === 'signed' ? 'green' :
                        timelineData.sheet.status === 'voided' ? 'default' : 'processing'
                      }>
                        {timelineData.sheet.status}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="撤回状态">
                      <Tag color={
                        timelineData.sheet.revoke_status === 'revoked' ? 'red' :
                        timelineData.sheet.revoke_status === 'reopened' ? 'blue' : 'default'
                      }>
                        {timelineData.sheet.revoke_status || 'none'}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="价签数">{timelineData.sheet.total_items}</Descriptions.Item>
                  </Descriptions>
                </Card>
              )}

              <Row gutter={16}>
                <Col span={4}>
                  <Card size="small">
                    <Statistic title="事件数" value={timelineData.total_events} />
                  </Card>
                </Col>
                <Col span={4}>
                  <Card size="small">
                    <Statistic title="放行" value={timelineData.allowed_count} valueStyle={{ color: '#52c41a' }} />
                  </Card>
                </Col>
                <Col span={4}>
                  <Card size="small">
                    <Statistic title="拦截" value={timelineData.blocked_count} valueStyle={{ color: '#ff4d4f' }} />
                  </Card>
                </Col>
                <Col span={4}>
                  <Card size="small">
                    <Statistic title="凭证数" value={timelineData.authorizations?.length || 0} />
                  </Card>
                </Col>
                <Col span={4}>
                  <Card size="small">
                    <Statistic title="回执数" value={timelineData.receipts?.length || 0} />
                  </Card>
                </Col>
              </Row>

              <Alert
                type="info"
                showIcon
                message="事件时间线（按发生时间正序）"
                description="点击事件卡片查看详情；拦截事件标红，放行事件标绿"
              />

              <Timeline
                mode="left"
                items={timelineData.events.map((ev, idx) => {
                  const info = ACTION_CN[ev.action] || {}
                  const isBlocked = ev.result === 'blocked'
                  const color = isBlocked ? 'red' : (info.color || 'blue')
                  return {
                    color: color,
                    dot: info.icon,
                    children: (
                      <Card
                        size="small"
                        style={{
                          borderLeft: `4px solid ${isBlocked ? '#ff4d4f' : (info.color || '#1677ff')}`,
                          marginBottom: 8,
                        }}
                        title={
                          <Space>
                            <span>#{idx + 1}</span>
                            <Tag color={info.color}>{info.label || ev.action}</Tag>
                            {isBlocked ? (
                              <Tag color="red" icon={<StopOutlined />}>拦截</Tag>
                            ) : (
                              <Tag color="green" icon={<CheckCircleOutlined />}>放行</Tag>
                            )}
                            <Text style={{ fontSize: 12, color: '#999' }}>
                              {dayjs(ev.time).format('YYYY-MM-DD HH:mm:ss')}
                            </Text>
                          </Space>
                        }
                        extra={
                          <Space>
                            <Tag color="purple">{ev.user_name || '匿名'}</Tag>
                            {ev.user_role && <Tag>{ev.user_role}</Tag>}
                          </Space>
                        }
                      >
                        <Space direction="vertical" size={4} style={{ width: '100%' }}>
                          {ev.block_code && (
                            <div>
                              <Text strong style={{ color: '#ff4d4f' }}>拦截码：</Text>
                              <Text code style={{ color: '#ff4d4f' }}>{ev.block_code}</Text>
                            </div>
                          )}
                          {ev.block_reason && (
                            <div style={{ color: '#ff4d4f' }}>
                              <Text strong>原因：</Text>{ev.block_reason}
                            </div>
                          )}
                          {ev.detail && (
                            <div style={{ color: '#555' }}>
                              <Text strong>详情：</Text>{ev.detail}
                            </div>
                          )}
                          {ev.response_status && (
                            <div>
                              <Text type="secondary">HTTP响应：{ev.response_status}</Text>
                            </div>
                          )}
                          {ev.client_ip && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              IP: {ev.client_ip}
                            </Text>
                          )}
                        </Space>
                      </Card>
                    ),
                  }
                })}
              />

              {timelineData.authorizations && timelineData.authorizations.length > 0 && (
                <Card size="small" title="授权凭证列表" style={{ marginTop: 8 }}>
                  <List
                    size="small"
                    dataSource={timelineData.authorizations}
                    renderItem={(auth) => (
                      <List.Item>
                        <List.Item.Meta
                          avatar={<KeyOutlined style={{ color: '#722ed1' }} />}
                          title={
                            <Space>
                              <Tag color={
                                auth.token_type === 'sign' ? 'blue' :
                                auth.token_type === 'view' ? 'green' : 'purple'
                              }>
                                {auth.token_type}
                              </Tag>
                              {auth.revoked && <Tag color="red">已撤回</Tag>}
                              {auth.is_used && <Tag color="green">已使用</Tag>}
                              {auth.user_name && <Tag>{auth.user_name}</Tag>}
                              {auth.role_restriction && <Tag color="purple">角色:{auth.role_restriction}</Tag>}
                              {auth.one_time && <Tag color="orange">一次性</Tag>}
                            </Space>
                          }
                          description={
                            <Space direction="vertical" size={0} style={{ width: '100%' }}>
                              <Text code style={{ fontSize: 12 }}>{auth.auth_token}</Text>
                              <Text type="secondary" style={{ fontSize: 11 }}>
                                创建：{dayjs(auth.created_at).format('MM-DD HH:mm')}
                                {' | '}有效期：{dayjs(auth.expires_at).format('MM-DD HH:mm')}
                                {auth.generation_id && <> | 批次：{auth.generation_id.slice(-10)}</>}
                              </Text>
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
                </Card>
              )}

              {timelineData.receipts && timelineData.receipts.length > 0 && (
                <Card size="small" title="交接回执（含防篡改哈希）" style={{ marginTop: 8 }}>
                  <List
                    size="small"
                    dataSource={timelineData.receipts}
                    renderItem={(rcpt) => (
                      <List.Item>
                        <List.Item.Meta
                          avatar={<FileTextOutlined style={{ color: '#52c41a' }} />}
                          title={
                            <Space>
                              <Tag color="green">回执 #{rcpt.id}</Tag>
                              <Text strong>{rcpt.receipt_no}</Text>
                              {rcpt.signed_by_name && <Tag color="blue">{rcpt.signed_by_name}</Tag>}
                              <Text type="secondary">
                                {dayjs(rcpt.signed_at).format('YYYY-MM-DD HH:mm:ss')}
                              </Text>
                            </Space>
                          }
                          description={
                            <div>
                              <div>
                                <Text code style={{ fontSize: 11 }}>
                                  SHA256: {rcpt.receipt_hash}
                                </Text>
                              </div>
                              <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
                                价签数：{rcpt.item_count} 
                                {' | '}签收IP：{rcpt.signer_ip || '—'}
                                {' | '}导出次数：{rcpt.export_count || 0}
                                {rcpt.signer_remark && <> | 备注：{rcpt.signer_remark}</>}
                              </div>
                            </div>
                          }
                        />
                      </List.Item>
                    )}
                  />
                </Card>
              )}
            </Space>
          )}
        </Card>

        <Card
          title={<Space><FileTextOutlined />全部审计日志</Space>}
          extra={
            <Space wrap>
              <Select
                allowClear
                placeholder="操作类型"
                style={{ width: 150 }}
                value={filters.action || undefined}
                onChange={v => setFilters({ ...filters, action: v })}
                options={actionOptions}
              />
              <Select
                allowClear
                placeholder="结果"
                style={{ width: 120 }}
                value={filters.result || undefined}
                onChange={v => setFilters({ ...filters, result: v })}
                options={[
                  { value: 'allowed', label: '放行' },
                  { value: 'blocked', label: '拦截' },
                ]}
              />
              <Select
                allowClear
                placeholder="拦截码"
                style={{ width: 200 }}
                value={filters.block_code || undefined}
                onChange={v => setFilters({ ...filters, block_code: v })}
                options={blockCodeOptions}
              />
              <Input
                allowClear
                placeholder="交接单号"
                style={{ width: 160 }}
                value={filters.sheet_no || ''}
                onChange={e => setFilters({ ...filters, sheet_no: e.target.value })}
                onPressEnter={() => loadLogs()}
              />
              <Input
                allowClear
                placeholder="用户名"
                style={{ width: 120 }}
                value={filters.user_name || ''}
                onChange={e => setFilters({ ...filters, user_name: e.target.value })}
                onPressEnter={() => loadLogs()}
              />
            </Space>
          }
        >
          <Table
            rowKey="id"
            size="small"
            loading={loading}
            columns={logColumns}
            dataSource={logs}
            pagination={{ pageSize: 10, showSizeChanger: true }}
            scroll={{ x: 1500 }}
          />
        </Card>
      </Space>
    </div>
  )
}
