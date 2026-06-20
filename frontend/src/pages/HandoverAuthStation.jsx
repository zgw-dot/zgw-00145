import React, { useState, useEffect, useMemo } from 'react'
import {
  Card, Row, Col, Statistic, Table, Button, Space, Tag, Modal, Form,
  Select, Input, DatePicker, App as AntApp, Typography, Descriptions,
  Divider, Tooltip, Badge, Alert, List, Empty,
} from 'antd'
import {
  SafetyCertificateOutlined, CheckCircleOutlined, StopOutlined,
  PlusOutlined, ReloadOutlined, EyeOutlined, DownloadOutlined,
  RollbackOutlined, SendOutlined, CopyOutlined, KeyOutlined,
  UserOutlined, UnorderedListOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { authStationApi, handoverApi, userApi, exportApi } from '../utils/api.js'

const { Title, Text, Paragraph } = Typography
const { TextArea } = Input
const { Option } = Select
const { RangePicker } = DatePicker

const TOKEN_TYPE = {
  sign: { label: '签收凭证', color: 'blue' },
  view: { label: '查看凭证', color: 'green' },
  receipt: { label: '回执凭证', color: 'purple' },
}

const SCOPE_OPTIONS = [
  { value: 'assigned', label: '仅指派人员可见' },
  { value: 'role_all', label: '同角色全部可见' },
  { value: 'store_all', label: '同门店全部可见' },
  { value: 'specific', label: '指定用户可见' },
]

export default function HandoverAuthStation({ user }) {
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()

  const [summary, setSummary] = useState(null)
  const [sheets, setSheets] = useState([])
  const [auths, setAuths] = useState([])
  const [receipts, setReceipts] = useState([])
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('pending')

  const [assignOpen, setAssignOpen] = useState(false)
  const [authOpen, setAuthOpen] = useState(false)
  const [currentSheet, setCurrentSheet] = useState(null)
  const [assignForm] = Form.useForm()
  const [authForm] = Form.useForm()

  const [tokenInputOpen, setTokenInputOpen] = useState(false)
  const [tokenValidateResult, setTokenValidateResult] = useState(null)

  const canManage = user?.role === 'admin' || user?.role === 'operator'

  useEffect(() => {
    loadAll()
    loadUsers()
  }, [])

  const loadAll = async () => {
    setLoading(true)
    try {
      const [sumRes, sheetsRes, receiptsRes] = await Promise.all([
        authStationApi.summary(),
        handoverApi.list({ size: 100 }),
        authStationApi.listReceipts({ size: 100 }),
      ])
      setSummary(sumRes.data)
      setSheets(sheetsRes.data?.list || sheetsRes.data || [])
      setReceipts(receiptsRes.data?.list || receiptsRes.data || [])
    } catch (err) {
      message.error(err.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  const loadUsers = async () => {
    try {
      const res = await userApi.list()
      setUsers(res.data || [])
    } catch (err) { }
  }

  const pendingSheets = useMemo(
    () => sheets.filter(s => s.status === 'pending' && s.revoke_status !== 'revoked'),
    [sheets]
  )
  const signedSheets = useMemo(() => sheets.filter(s => s.status === 'signed'), [sheets])
  const voidedSheets = useMemo(() => sheets.filter(s => s.status === 'voided'), [sheets])
  const revokedSheets = useMemo(() => sheets.filter(s => s.revoke_status === 'revoked'), [sheets])

  const displaySheets = useMemo(() => {
    if (activeTab === 'pending') return pendingSheets
    if (activeTab === 'signed') return signedSheets
    if (activeTab === 'revoked') return revokedSheets
    if (activeTab === 'voided') return voidedSheets
    return sheets
  }, [activeTab, pendingSheets, signedSheets, revokedSheets, voidedSheets, sheets])

  const handleOpenAssign = async (sheet) => {
    setCurrentSheet(sheet)
    assignForm.setFieldsValue({
      assigned_to: sheet.assigned_to,
      view_scope: sheet.view_scope || 'assigned',
    })
    if (sheet.id) {
      try {
        const res = await handoverApi.listAuthorizations(sheet.id)
        setAuths(res.data || [])
      } catch (err) { setAuths([]) }
    }
    setAssignOpen(true)
  }

  const handleAssignSubmit = async () => {
    try {
      const values = await assignForm.validateFields()
      await handoverApi.assign(currentSheet.id, values)
      message.success('指派成功')
      setAssignOpen(false)
      loadAll()
    } catch (err) {
      message.error(err.message || '指派失败')
    }
  }

  const handleOpenAuth = (sheet) => {
    setCurrentSheet(sheet)
    authForm.resetFields()
    authForm.setFieldsValue({
      token_type: 'sign',
      one_time: true,
      expire_hours: 24,
    })
    setAuthOpen(true)
  }

  const handleAuthSubmit = async () => {
    try {
      const values = await authForm.validateFields()
      const res = await handoverApi.authorize(currentSheet.id, values)
      modal.success({
        title: '授权凭证已生成',
        content: (
          <div>
            <Alert
              type="success"
              showIcon
              message="凭证生成成功，请立即复制发送给签收人"
              description="一次性凭证用后即作废，请妥善保管"
              style={{ marginBottom: 16 }}
            />
            <List
              size="small"
              dataSource={res.data?.authorizations || res.data || []}
              renderItem={(auth) => (
                <List.Item
                  actions={[
                    <Tooltip key="copy" title="复制凭证">
                      <Button
                        size="small"
                        icon={<CopyOutlined />}
                        onClick={() => {
                          navigator.clipboard?.writeText(auth.auth_token)
                          message.success('凭证已复制到剪贴板')
                        }}
                      >
                        复制
                      </Button>
                    </Tooltip>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<KeyOutlined style={{ color: '#1677ff' }} />}
                    title={
                      <Space>
                        <Tag color={TOKEN_TYPE[auth.token_type]?.color}>
                          {TOKEN_TYPE[auth.token_type]?.label}
                        </Tag>
                        {auth.user_name && <Tag>用户：{auth.user_name}</Tag>}
                        {auth.role_restriction && <Tag color="purple">角色：{auth.role_restriction}</Tag>}
                        {auth.one_time && <Tag color="orange">一次性</Tag>}
                      </Space>
                    }
                    description={
                      <div>
                        <Text copyable={{ text: auth.auth_token }} code style={{ fontSize: 13 }}>
                          {auth.auth_token}
                        </Text>
                        <div style={{ marginTop: 4, fontSize: 12, color: '#999' }}>
                          有效期至：{auth.expires_at ? dayjs(auth.expires_at).format('YYYY-MM-DD HH:mm') : '—'}
                        </div>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          </div>
        ),
        width: 640,
        okText: '完成',
      })
      setAuthOpen(false)
      if (currentSheet?.id) {
        try {
          const res = await handoverApi.listAuthorizations(currentSheet.id)
          setAuths(res.data || [])
        } catch (err) { }
      }
      loadAll()
    } catch (err) {
      message.error(err.message || '生成失败')
    }
  }

  const handleRevokeAuth = async (authId) => {
    modal.confirm({
      title: '确认撤回该授权凭证？',
      content: '撤回后该凭证立即失效，无法再使用。',
      okText: '确认撤回',
      okType: 'danger',
      onOk: async () => {
        try {
          await handoverApi.revokeAuth(authId, { revoke_reason: '管理员手动撤回' })
          message.success('已撤回凭证')
          loadAll()
          if (currentSheet?.id) {
            const res = await handoverApi.listAuthorizations(currentSheet.id)
            setAuths(res.data || [])
          }
        } catch (err) {
          message.error(err.message || '撤回失败')
        }
      },
    })
  }

  const handleRevokeSign = async (sheet) => {
    modal.confirm({
      title: '撤回签收',
      content: (
        <div>
          <p>确认撤回该交接单的签收？撤回后：</p>
          <ul>
            <li>交接单状态恢复为"待签收"</li>
            <li>原签收记录保留在撤回痕迹中</li>
            <li>原签收凭证标记为已使用</li>
          </ul>
        </div>
      ),
      okText: '确认撤回',
      okType: 'danger',
      onOk: async () => {
        try {
          await handoverApi.revokeSign(sheet.id, { revoke_reason: '管理员撤回签收' })
          message.success('已撤回签收')
          loadAll()
        } catch (err) {
          message.error(err.message || '撤回失败')
        }
      },
    })
  }

  const handleReopen = async (sheet) => {
    modal.confirm({
      title: '重开交接单',
      content: '将已撤回签收的交接单重新开放为"待签收"状态，所有授权、凭证保留撤回痕迹。',
      okText: '确认重开',
      onOk: async () => {
        try {
          await handoverApi.reopen(sheet.id, { reopen_reason: '管理员重开' })
          message.success('已重开交接单')
          loadAll()
        } catch (err) {
          message.error(err.message || '重开失败')
        }
      },
    })
  }

  const handleValidateToken = async () => {
    try {
      const values = await authForm.validateFields()
      const res = await authStationApi.validateToken({
        token: values.token,
        sheet_id: values.sheet_id,
      })
      setTokenValidateResult(res.data)
      if (res.data?.valid) {
        message.success('凭证有效')
      } else {
        message.warning(`凭证无效：${res.data?.reason || '未知原因'}`)
      }
    } catch (err) {
      setTokenValidateResult({
        valid: false,
        reason: err.message,
        code: err.code,
      })
      message.error(err.message || '校验失败')
    }
  }

  const sheetColumns = [
    {
      title: '交接单号',
      dataIndex: 'sheet_no',
      key: 'sheet_no',
      width: 180,
      render: (v, r) => (
        <a onClick={() => navigate(`/handover-sheets/${r.id}`)}>{v}</a>
      ),
    },
    { title: '标题', dataIndex: 'title', key: 'title' },
    { title: '门店', dataIndex: 'store', key: 'store', width: 120 },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v) => {
        const m = {
          pending: { color: 'processing', label: '待签收' },
          signed: { color: 'success', label: '已签收' },
          voided: { color: 'default', label: '已作废' },
        }
        return <Tag color={m[v]?.color}>{m[v]?.label || v}</Tag>
      },
    },
    {
      title: '撤回状态',
      dataIndex: 'revoke_status',
      key: 'revoke_status',
      width: 100,
      render: (v) => {
        if (!v || v === 'none') return <Tag color="default">正常</Tag>
        const m = {
          revoking: { color: 'warning', label: '撤回中' },
          revoked: { color: 'error', label: '已撤回' },
          reopened: { color: 'blue', label: '已重开' },
        }
        return <Tag color={m[v]?.color}>{m[v]?.label || v}</Tag>
      },
    },
    { title: '指派给', dataIndex: 'assigned_to_name', key: 'assigned_to_name', width: 100 },
    {
      title: '授权凭证',
      key: 'auth_count',
      width: 100,
      render: (_, r) => {
        const count = auths.filter(a => a.sheet_id === r.id).length
        return count > 0 ? <Badge count={count} showZero /> : '—'
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 240,
      fixed: 'right',
      render: (_, r) => (
        <Space size="small" wrap>
          {canManage && r.status === 'pending' && (
            <>
              <Button size="small" onClick={() => handleOpenAssign(r)} icon={<UserOutlined />}>
                指派
              </Button>
              <Button size="small" type="primary" onClick={() => handleOpenAuth(r)} icon={<PlusOutlined />}>
                发凭证
              </Button>
            </>
          )}
          {canManage && r.status === 'signed' && (
            <Button size="small" danger onClick={() => handleRevokeSign(r)} icon={<RollbackOutlined />}>
              撤回签收
            </Button>
          )}
          {canManage && r.revoke_status === 'revoked' && (
            <Button size="small" type="primary" onClick={() => handleReopen(r)} icon={<ReloadOutlined />}>
              重开
            </Button>
          )}
          <Button size="small" onClick={() => navigate(`/handover-sheets/${r.id}`)} icon={<EyeOutlined />}>
            详情
          </Button>
        </Space>
      ),
    },
  ]

  const receiptColumns = [
    { title: '回执编号', dataIndex: 'receipt_no', key: 'receipt_no', width: 220 },
    { title: '交接单号', dataIndex: 'sheet_no', key: 'sheet_no', width: 180 },
    { title: '签收人', dataIndex: 'signed_by_name', key: 'signed_by_name', width: 100 },
    { title: '签收时间', dataIndex: 'signed_at', key: 'signed_at', width: 170,
      render: v => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '—'
    },
    { title: '签收IP', dataIndex: 'signer_ip', key: 'signer_ip', width: 120 },
    { title: '价签数', dataIndex: 'item_count', key: 'item_count', width: 80 },
    { title: '导出次数', dataIndex: 'export_count', key: 'export_count', width: 80 },
    {
      title: '哈希',
      dataIndex: 'receipt_hash',
      key: 'receipt_hash',
      render: v => v ? <Text code style={{ fontSize: 11 }}>{v.slice(0, 16)}...</Text> : '—'
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card>
          <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}>
            <Space>
              <SafetyCertificateOutlined style={{ fontSize: 28, color: '#1677ff' }} />
              <div>
                <Title level={4} style={{ margin: 0 }}>授权签收台</Title>
                <Text type="secondary">独立管理谁能看、谁能签、谁能撤回</Text>
              </div>
            </Space>
            <Space>
              <Button onClick={() => setTokenInputOpen(true)} icon={<CheckCircleOutlined />}>
                校验凭证
              </Button>
              <Button onClick={loadAll} icon={<ReloadOutlined />}>刷新</Button>
              <Button onClick={() => exportApi.receipts()} icon={<DownloadOutlined />}>导出回执</Button>
              {user?.role === 'admin' && (
                <Button onClick={() => exportApi.auditLogs()} icon={<DownloadOutlined />} type="primary">
                  导出审计日志
                </Button>
              )}
            </Space>
          </Space>
        </Card>

        {summary && (
          <Row gutter={16}>
            <Col span={4}>
              <Card><Statistic title="待签收单" value={summary.handover_pending || 0} valueStyle={{ color: '#1677ff' }} /></Card>
            </Col>
            <Col span={4}>
              <Card><Statistic title="已指派" value={summary.handover_assigned || 0} valueStyle={{ color: '#52c41a' }} /></Card>
            </Col>
            <Col span={4}>
              <Card><Statistic title="待使用签收凭证" value={summary.auth_pending || 0} valueStyle={{ color: '#1890ff' }} /></Card>
            </Col>
            <Col span={4}>
              <Card><Statistic title="已使用凭证" value={summary.auth_used_count || 0} /></Card>
            </Col>
            <Col span={4}>
              <Card><Statistic title="撤回签收" value={summary.sign_revoked_count || 0} valueStyle={{ color: '#faad14' }} /></Card>
            </Col>
            <Col span={4}>
              <Card><Statistic title="回执总数" value={summary.receipt_count || 0} valueStyle={{ color: '#722ed1' }} /></Card>
            </Col>
          </Row>
        )}

        {summary && (user?.role === 'admin') && (
          <Row gutter={16}>
            <Col span={8}>
              <Card>
                <Statistic
                  title="审计放行次数"
                  value={summary.audit_allowed_count || 0}
                  prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
                  valueStyle={{ color: '#52c41a' }}
                />
              </Card>
            </Col>
            <Col span={8}>
              <Card>
                <Statistic
                  title="审计拦截次数"
                  value={summary.audit_blocked_count || 0}
                  prefix={<StopOutlined style={{ color: '#ff4d4f' }} />}
                  valueStyle={{ color: '#ff4d4f' }}
                />
              </Card>
            </Col>
            <Col span={8}>
              <Card>
                <Statistic title="撤回/作废凭证" value={(summary.auth_revoked_count || 0) + (summary.auth_expired || 0)} />
              </Card>
            </Col>
          </Row>
        )}

        <Card
          tabList={[
            { key: 'pending', tab: `待签收 (${pendingSheets.length})` },
            { key: 'signed', tab: `已签收 (${signedSheets.length})` },
            { key: 'revoked', tab: `已撤回 (${revokedSheets.length})` },
            { key: 'voided', tab: `已作废 (${voidedSheets.length})` },
            { key: 'all', tab: '全部' },
          ]}
          activeTabKey={activeTab}
          onTabChange={setActiveTab}
          title={<Space><UnorderedListOutlined />交接单授权列表</Space>}
        >
          <Table
            rowKey="id"
            size="small"
            loading={loading}
            columns={sheetColumns}
            dataSource={displaySheets}
            pagination={{ pageSize: 10 }}
            scroll={{ x: 1200 }}
          />
        </Card>

        <Card
          title={<Space><SafetyCertificateOutlined />交接回执记录</Space>}
          extra={<Button size="small" onClick={() => exportApi.receipts()}>导出CSV</Button>}
        >
          <Table
            rowKey="id"
            size="small"
            columns={receiptColumns}
            dataSource={receipts}
            pagination={{ pageSize: 10 }}
            scroll={{ x: 1200 }}
          />
        </Card>
      </Space>

      <Modal
        title={
          <Space>
            <UserOutlined />指派与授权：{currentSheet?.sheet_no}
          </Space>
        }
        open={assignOpen}
        onCancel={() => setAssignOpen(false)}
        footer={null}
        width={720}
        destroyOnClose
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="标题">{currentSheet?.title}</Descriptions.Item>
            <Descriptions.Item label="门店">{currentSheet?.store}</Descriptions.Item>
            <Descriptions.Item label="状态">{currentSheet?.status}</Descriptions.Item>
            <Descriptions.Item label="项数">{currentSheet?.total_items}</Descriptions.Item>
          </Descriptions>

          <Form form={assignForm} layout="vertical">
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label="指派接手人" name="assigned_to">
                  <Select allowClear placeholder="请选择指派签收人">
                    {users.map(u => (
                      <Option key={u.id} value={u.id}>
                        {u.username} ({u.role_name})
                      </Option>
                    ))}
                  </Select>
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="查看范围" name="view_scope">
                  <Select options={SCOPE_OPTIONS} />
                </Form.Item>
              </Col>
            </Row>
            <Space>
              <Button type="primary" onClick={handleAssignSubmit}>保存指派</Button>
              <Button
                onClick={() => {
                  handleOpenAuth(currentSheet)
                  setAssignOpen(false)
                }}
                icon={<PlusOutlined />}
              >
                去生成签收凭证
              </Button>
            </Space>
          </Form>

          <Divider orientation="left">已有授权凭证</Divider>
          {auths.length === 0 ? (
            <Empty description="暂无凭证，点击"去生成签收凭证"创建" />
          ) : (
            <List
              size="small"
              dataSource={auths.slice(0, 10)}
              renderItem={(auth) => (
                <List.Item
                  actions={[
                    !auth.revoked && !auth.is_used ? (
                      <Button
                        key="revoke"
                        size="small"
                        danger
                        onClick={() => handleRevokeAuth(auth.id)}
                      >
                        撤回
                      </Button>
                    ) : null,
                  ]}
                >
                  <List.Item.Meta
                    avatar={<KeyOutlined />}
                    title={
                      <Space>
                        <Tag color={TOKEN_TYPE[auth.token_type]?.color}>
                          {TOKEN_TYPE[auth.token_type]?.label}
                        </Tag>
                        {auth.revoked && <Tag color="red">已撤回</Tag>}
                        {auth.is_used && <Tag color="green">已使用</Tag>}
                        {auth.user_name && <Tag>{auth.user_name}</Tag>}
                        {auth.role_restriction && <Tag color="purple">{auth.role_restriction}</Tag>}
                      </Space>
                    }
                    description={
                      <div>
                        <Text code style={{ fontSize: 12 }}>{auth.auth_token}</Text>
                        <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                          创建：{auth.created_at ? dayjs(auth.created_at).format('MM-DD HH:mm') : '—'}
                          　有效期：{auth.expires_at ? dayjs(auth.expires_at).format('MM-DD HH:mm') : '—'}
                        </div>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          )}
        </Space>
      </Modal>

      <Modal
        title={<Space><PlusOutlined />生成授权凭证</Space>}
        open={authOpen}
        onCancel={() => setAuthOpen(false)}
        footer={null}
        width={560}
        destroyOnClose
      >
        <Form form={authForm} layout="vertical">
          <Form.Item label="凭证类型" name="token_type">
            <Select options={[
              { value: 'sign', label: '签收凭证' },
              { value: 'view', label: '查看凭证' },
              { value: 'receipt', label: '回执凭证' },
            ]} />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="指定用户" name="user_id"
                tooltip="绑定到指定用户，其他人无法使用（实现拿错账号拦截）"
              >
                <Select allowClear placeholder="不绑定时可通过角色限制">
                  {users.map(u => (
                    <Option key={u.id} value={u.id}>
                      {u.username} ({u.role_name})
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="角色限制" name="role_restriction"
                tooltip="仅限该角色使用（实现替别人签拦截）"
              >
                <Select allowClear options={[
                  { value: 'admin', label: '管理员' },
                  { value: 'operator', label: '运营' },
                  { value: 'clerk', label: '店员' },
                ]} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="有效期(小时)" name="expire_hours">
                <Select options={[
                  { value: 1, label: '1小时' },
                  { value: 6, label: '6小时' },
                  { value: 12, label: '12小时' },
                  { value: 24, label: '24小时' },
                  { value: 72, label: '3天' },
                  { value: 168, label: '7天' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="一次性" name="one_time" valuePropName="checked"
                tooltip="一次性凭证用后即失效（实现旧凭证拦截）"
              >
                <Select options={[
                  { value: true, label: '一次性（推荐）' },
                  { value: false, label: '可重复使用' },
                ]} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="门店限制" name="store_restriction">
            <Input placeholder="可选：仅允许该门店的用户使用" />
          </Form.Item>
          <Form.Item label="备注" name="remark">
            <TextArea rows={2} placeholder="备注说明" />
          </Form.Item>
          <Space>
            <Button type="primary" onClick={handleAuthSubmit} icon={<SendOutlined />}>
              生成凭证
            </Button>
            <Button onClick={() => setAuthOpen(false)}>取消</Button>
          </Space>
        </Form>
      </Modal>

      <Modal
        title={<Space><CheckCircleOutlined />凭证校验台</Space>}
        open={tokenInputOpen}
        onCancel={() => { setTokenInputOpen(false); setTokenValidateResult(null); authForm.resetFields() }}
        footer={null}
        width={520}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          message="前后端独立校验授权状态"
          description="输入凭证，前端先调用 /validate 端点校验，避免使用旧凭证、错账号凭证等"
          style={{ marginBottom: 16 }}
        />
        <Form form={authForm} layout="vertical">
          <Form.Item label="授权凭证" name="token" rules={[{ required: true, message: '请输入凭证' }]}>
            <Input placeholder="粘贴签收/查看凭证" size="large" prefix={<KeyOutlined />} />
          </Form.Item>
          <Form.Item label="交接单ID(可选)" name="sheet_id">
            <Input placeholder="输入后会校验是否属于该交接单" />
          </Form.Item>
          <Button type="primary" onClick={handleValidateToken} block>
            立即校验
          </Button>
        </Form>

        {tokenValidateResult !== null && (
          <div style={{ marginTop: 20 }}>
            <Divider orientation="left">校验结果</Divider>
            <Alert
              type={tokenValidateResult.valid ? 'success' : 'error'}
              showIcon
              message={tokenValidateResult.valid ? '✅ 凭证有效' : '❌ 凭证无效'}
              description={
                <div>
                  {tokenValidateResult.reason && <p><b>原因：</b>{tokenValidateResult.reason}</p>}
                  {tokenValidateResult.code && <p><b>拦截码：</b>{tokenValidateResult.code}</p>}
                  {tokenValidateResult.valid && (
                    <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
                      {tokenValidateResult.sheet_id !== undefined && (
                        <Descriptions.Item label="交接单ID">{tokenValidateResult.sheet_id}</Descriptions.Item>
                      )}
                      {tokenValidateResult.token_type && (
                        <Descriptions.Item label="凭证类型">
                          {TOKEN_TYPE[tokenValidateResult.token_type]?.label || tokenValidateResult.token_type}
                        </Descriptions.Item>
                      )}
                      {tokenValidateResult.user_name && (
                        <Descriptions.Item label="绑定用户">{tokenValidateResult.user_name}</Descriptions.Item>
                      )}
                      {tokenValidateResult.role_restriction && (
                        <Descriptions.Item label="角色限制">{tokenValidateResult.role_restriction}</Descriptions.Item>
                      )}
                      {tokenValidateResult.expires_at && (
                        <Descriptions.Item label="有效期至">{tokenValidateResult.expires_at}</Descriptions.Item>
                      )}
                    </Descriptions>
                  )}
                </div>
              }
            />
          </div>
        )}
      </Modal>
    </div>
  )
}
