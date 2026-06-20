import React, { useState, useEffect } from 'react'
import {
  Descriptions, Tag, Space, Card, Button, App as AntApp, Typography,
  Table, Timeline, Divider, Row, Col, Modal, Form, Input, Badge, Tooltip,
  Alert, List, Empty,
} from 'antd'
import {
  ArrowLeftOutlined, SwapOutlined, CheckCircleOutlined,
  WarningOutlined, StopOutlined, DownloadOutlined, SearchOutlined,
  ExclamationCircleOutlined, EyeOutlined, KeyOutlined,
  UserOutlined, SafetyCertificateOutlined, RollbackOutlined,
  ReloadOutlined, SendOutlined, CopyOutlined, FileTextOutlined,
} from '@ant-design/icons'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { handoverApi, authStationApi, exportApi } from '../utils/api.js'

const { Title, Text } = Typography
const { TextArea } = Input

const STATUS_MAP = {
  pending: { label: '待签收', color: 'processing' },
  signed: { label: '已签收', color: 'success' },
  voided: { label: '已作废', color: 'default' },
}

const REVOKE_STATUS_MAP = {
  none: { label: '正常', color: 'default' },
  revoking: { label: '撤回中', color: 'warning' },
  revoked: { label: '已撤回签收', color: 'error' },
  reopened: { label: '已重开', color: 'blue' },
}

const VIEW_SCOPE_MAP = {
  assigned: { label: '仅指派人员', color: 'blue' },
  store_all: { label: '同门店可见', color: 'cyan' },
  role_all: { label: '同角色可见', color: 'purple' },
  specific: { label: '指定用户', color: 'geekblue' },
}

const LABEL_STATUS_MAP = {
  draft: { label: '草稿', color: 'default' },
  pending_approval: { label: '待审', color: 'processing' },
  published: { label: '已发布', color: 'success' },
  revoking: { label: '撤销中', color: 'warning' },
  rolled_back: { label: '已回滚', color: 'warning' },
  revoked: { label: '已撤销', color: 'error' },
}

const ACTION_MAP = {
  create: { label: '创建', color: 'blue' },
  sign: { label: '签收', color: 'green' },
  void: { label: '作废', color: 'red' },
  check_conflict: { label: '冲突检查', color: 'orange' },
  conflict_auto_mark: { label: '冲突自动标记', color: 'volcano' },
  assign: { label: '指派接手人', color: 'green' },
  authorize: { label: '生成凭证', color: 'purple' },
  revoke_sign: { label: '撤回签收', color: 'orange' },
  reopen: { label: '重开交接单', color: 'cyan' },
}

const TOKEN_TYPE_MAP = {
  sign: { label: '签收凭证', color: 'blue' },
  view: { label: '查看凭证', color: 'green' },
  receipt: { label: '回执凭证', color: 'purple' },
}

const BLOCK_CODE_HINTS = {
  VIEW_NOT_AUTHORIZED: '您未被授权查看此交接单，请联系管理员指派或生成查看凭证',
  TOKEN_USER_MISMATCH: '该凭证绑定的是其他用户，请使用正确的账号登录',
  TOKEN_ROLE_MISMATCH: '该凭证仅允许指定角色使用，请切换到对应角色的账号',
  TOKEN_EXPIRED: '该凭证已过期，请联系管理员重新授权',
  TOKEN_USED: '该凭证已使用过，一次性凭证不允许重复使用',
  TOKEN_REVOKED: '该凭证已被管理员撤回，请重新获取凭证',
  VOIDED_SHEET: '该交接单已作废，无法再进行操作',
  REVOKED_SIGN: '签收权已被撤回，如需重新签收请让管理员重开交接单',
  ALREADY_SIGNED: '该交接单已经签收，不能重复签收',
  SIGN_NOT_ASSIGNED: '您不是指派签收人，请联系管理员获取签收凭证',
  SIGN_NOT_AUTHORIZED: '您没有签收权限，请联系管理员指派或获取签收凭证',
  CONFLICT_EXISTS: '存在冲突价签，请先处理冲突再签收',
  DUPLICATE_DATA: '演示数据已存在，请使用force_reset=true重置后再导入',
  NOT_FOUND: '交接单不存在或已被删除',
  STATUS_INVALID: '交接单当前状态不允许此操作',
}

export default function HandoverSheetDetail({ user }) {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState(null)
  const [signOpen, setSignOpen] = useState(false)
  const [voidOpen, setVoidOpen] = useState(false)
  const [tokenValidateOpen, setTokenValidateOpen] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [signToken, setSignToken] = useState('')
  const [signerRemark, setSignerRemark] = useState('')
  const [tokenValidateResult, setTokenValidateResult] = useState(null)
  const [voidForm] = Form.useForm()
  const [validateForm] = Form.useForm()

  const canManage = user?.role === 'admin' || user?.role === 'operator'

  useEffect(() => {
    const vt = searchParams.get('view_token')
    if (vt) {
      setTokenInput(vt)
    }
    loadDetail()
  }, [id])

  const loadDetail = async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const params = {}
      const vt = searchParams.get('view_token') || tokenInput
      if (vt) params.view_token = vt
      const res = await handoverApi.getDetail(id, params)
      setData(res.data)
    } catch (err) {
      const code = err.code
      const hint = BLOCK_CODE_HINTS[code] || '无法加载交接单详情'
      setLoadError({
        message: err.message,
        code,
        hint,
        raw: err.raw,
      })
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  const handleTokenAccess = async () => {
    if (!tokenInput.trim()) {
      message.warning('请输入查看凭证')
      return
    }
    loadDetail()
  }

  const handleCheckConflicts = async () => {
    try {
      const res = await handoverApi.checkConflicts(id)
      if (res.data?.has_conflict) {
        modal.warning({
          title: '发现冲突',
          content: `检测到 ${res.data.conflict_count} 项冲突，请查看冲突明细`,
          okText: '知道了',
        })
      } else {
        message.success('未发现冲突，所有价签状态正常')
      }
      loadDetail()
    } catch (err) {
      message.error(err.message || '检查失败')
    }
  }

  const handleSign = async () => {
    try {
      const payload = {}
      if (signToken.trim()) payload.sign_token = signToken.trim()
      if (signerRemark.trim()) payload.signer_remark = signerRemark.trim()
      const res = await handoverApi.sign(id, payload)
      modal.success({
        title: '签收成功',
        content: (
          <div>
            <Alert
              type="success"
              showIcon
              message="交接回执已生成"
              description="签收后所有价签标记为已打印"
              style={{ marginBottom: 12 }}
            />
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="交接单ID">{res.data?.sheet_id || id}</Descriptions.Item>
              <Descriptions.Item label="签收时间">
                {res.data?.signed_at ? dayjs(res.data.signed_at).format('YYYY-MM-DD HH:mm:ss') : '—'}
              </Descriptions.Item>
              <Descriptions.Item label="回执编号">
                <Text code copyable>{res.data?.receipt_no || '—'}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="回执哈希">
                <Text code style={{ fontSize: 12 }}>
                  {res.data?.receipt_hash ? res.data.receipt_hash.slice(0, 32) + '...' : '—'}
                </Text>
              </Descriptions.Item>
              {res.data?.sign_token_used && (
                <Descriptions.Item label="使用凭证">
                  <Tag color="blue">签收凭证已标记为已使用</Tag>
                </Descriptions.Item>
              )}
            </Descriptions>
          </div>
        ),
        width: 520,
        okText: '完成',
      })
      setSignOpen(false)
      setSignToken('')
      setSignerRemark('')
      loadDetail()
    } catch (err) {
      const code = err.code
      const hint = BLOCK_CODE_HINTS[code]
      if (code === 'VOIDED_SHEET' || code === 'REVOKED_SIGN' || code === 'ALREADY_SIGNED' ||
          code === 'CONFLICT_EXISTS' || code === 'TOKEN_USER_MISMATCH' ||
          code === 'TOKEN_ROLE_MISMATCH' || code === 'TOKEN_USED' ||
          code === 'TOKEN_EXPIRED' || code === 'TOKEN_REVOKED' ||
          code === 'SIGN_NOT_ASSIGNED' || code === 'SIGN_NOT_AUTHORIZED') {
        modal.warning({
          title: '签收被拦截',
          width: 520,
          content: (
            <div>
              <Alert
                type="error"
                showIcon
                message={err.message}
                description={hint}
              />
              <Descriptions size="small" column={1} bordered style={{ marginTop: 12 }}>
                <Descriptions.Item label="拦截码">
                  <Tag color="red">{code}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="当前用户">
                  {user?.username} ({user?.role})
                </Descriptions.Item>
                <Descriptions.Item label="处理结果">
                  <Text type="secondary">
                    本次操作已被写入审计日志（人、时间、原因、原始请求）
                  </Text>
                </Descriptions.Item>
              </Descriptions>
            </div>
          ),
          okText: '了解',
        })
      } else if (err.message && err.message.includes('冲突')) {
        modal.warning({
          title: '无法签收',
          content: err.message,
          okText: '知道了',
        })
      } else {
        message.error(err.message || '签收失败')
      }
    }
  }

  const handleVoid = async (values) => {
    try {
      await handoverApi.void(id, { reason: values.reason })
      message.success('作废成功')
      setVoidOpen(false)
      voidForm.resetFields()
      loadDetail()
    } catch (err) {
      message.error(err.message || '作废失败')
    }
  }

  const handleRevokeSign = () => {
    modal.confirm({
      title: '撤回签收',
      content: '确认撤回该交接单的签收？撤回后可以重开再次签收，所有撤回痕迹保留。',
      okText: '确认撤回',
      okType: 'danger',
      onOk: async () => {
        try {
          await handoverApi.revokeSign(id, { revoke_reason: '管理员撤回签收' })
          message.success('已撤回签收')
          loadDetail()
        } catch (err) {
          message.error(err.message || '撤回失败')
        }
      },
    })
  }

  const handleReopen = () => {
    modal.confirm({
      title: '重开交接单',
      content: '将该交接单重新开放为"待签收"状态，可重新指派和授权。',
      okText: '确认重开',
      onOk: async () => {
        try {
          await handoverApi.reopen(id, { reopen_reason: '管理员重开' })
          message.success('已重开交接单')
          loadDetail()
        } catch (err) {
          message.error(err.message || '重开失败')
        }
      },
    })
  }

  const handleValidateToken = async () => {
    try {
      const values = await validateForm.validateFields()
      const res = await authStationApi.validateToken({
        token: values.token,
        sheet_id: parseInt(id),
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
        code: err.code,
        reason: err.message,
      })
      message.error(err.message || '校验失败')
    }
  }

  const handleExportDetail = () => {
    exportApi.handoverSheet(id)
  }

  if (loadError) {
    return (
      <div style={{ padding: 24 }}>
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>
            返回
          </Button>

          <Card>
            <Alert
              type="error"
              showIcon
              message={`拒绝访问：${loadError.message}`}
              description={loadError.hint}
              action={
                <Space direction="vertical">
                  <Input
                    size="large"
                    placeholder="请粘贴查看凭证(view_token)"
                    prefix={<KeyOutlined />}
                    value={tokenInput}
                    onChange={e => setTokenInput(e.target.value)}
                    style={{ width: 400 }}
                  />
                  <Button type="primary" onClick={handleTokenAccess} icon={<EyeOutlined />}>
                    使用凭证访问
                  </Button>
                </Space>
              }
            />

            <Descriptions size="small" column={1} bordered style={{ marginTop: 16 }}>
              {loadError.code && (
                <Descriptions.Item label="拦截码">
                  <Tag color="red">{loadError.code}</Tag>
                </Descriptions.Item>
              )}
              <Descriptions.Item label="当前用户">
                {user?.username} ({user?.role})
              </Descriptions.Item>
              <Descriptions.Item label="说明">
                <Text type="secondary">
                  您的请求已被系统记录到审计日志（用户、时间、拦截原因、原始请求IP、UA全部写入）
                </Text>
              </Descriptions.Item>
            </Descriptions>

            {loadError.code === 'VIEW_NOT_AUTHORIZED' && (
              <div style={{ marginTop: 16 }}>
                <Title level={5}>可能的解决方案：</Title>
                <ol style={{ paddingLeft: 20, color: '#595959' }}>
                  <li>向管理员索要绑定您账号的 <Text code>view_token</Text> 查看凭证</li>
                  <li>让管理员将您设为 <Text code>assigned_to</Text> 指派接手人</li>
                  <li>让管理员将查看范围设为 <Text code>role_all</Text> 或 <Text code>store_all</Text></li>
                  <li>确认您的登录账号是否正确</li>
                </ol>
              </div>
            )}
          </Card>
        </Space>
      </div>
    )
  }

  if (!data) return <div style={{ padding: 40 }}>加载中...</div>

  const statusInfo = STATUS_MAP[data.status] || { label: data.status, color: 'default' }
  const revokeInfo = REVOKE_STATUS_MAP[data.revoke_status] || REVOKE_STATUS_MAP.none
  const scopeInfo = VIEW_SCOPE_MAP[data.view_scope] || VIEW_SCOPE_MAP.assigned
  const canSignNow = !!data.can_sign

  const itemColumns = [
    {
      title: 'SKU',
      dataIndex: 'snapshot_sku',
      key: 'sku',
      width: 140,
      render: (v) => <span style={{ fontFamily: 'monospace' }}>{v}</span>,
    },
    { title: '门店', dataIndex: 'snapshot_store', key: 'store', width: 120 },
    {
      title: '原价',
      dataIndex: 'snapshot_original_price',
      key: 'original_price',
      width: 100,
      align: 'right',
      render: (v) => <span style={{ textDecoration: 'line-through', color: '#8c8c8c' }}>¥{v?.toFixed(2)}</span>,
    },
    {
      title: '促销价',
      dataIndex: 'snapshot_promotion_price',
      key: 'promotion_price',
      width: 120,
      align: 'right',
      render: (v, r) => {
        const discount = r.snapshot_original_price > 0 ? (v / r.snapshot_original_price * 100).toFixed(1) : '-'
        return (
          <Space direction="vertical" size={0} style={{ alignItems: 'flex-end' }}>
            <span style={{ fontSize: 16, fontWeight: 600, color: '#ff4d4f' }}>¥{v?.toFixed(2)}</span>
            <span style={{ fontSize: 11, color: '#8c8c8c' }}>{discount}%</span>
          </Space>
        )
      },
    },
    {
      title: '生效时段',
      key: 'period',
      width: 260,
      render: (_, r) => (
        <div style={{ fontSize: 12 }}>
          <div><Tag color="green">起</Tag>{dayjs(r.snapshot_effective_from).format('YYYY-MM-DD HH:mm')}</div>
          <div style={{ marginTop: 2 }}><Tag color="red">止</Tag>{dayjs(r.snapshot_effective_to).format('YYYY-MM-DD HH:mm')}</div>
        </div>
      ),
    },
    {
      title: '快照版本',
      dataIndex: 'snapshot_label_version',
      key: 'version',
      width: 90,
      align: 'center',
      render: (v) => <Tag>v{v}</Tag>,
    },
    {
      title: '打印状态',
      dataIndex: 'print_status',
      key: 'print_status',
      width: 100,
      align: 'center',
      render: (v) => v === 'printed'
        ? <Tag color="success" icon={<CheckCircleOutlined />}>已打印</Tag>
        : <Tag color="processing">待打印</Tag>,
    },
    {
      title: '当前状态',
      dataIndex: 'current_label_status',
      key: 'current_status',
      width: 100,
      align: 'center',
      render: (v, r) => {
        const ls = LABEL_STATUS_MAP[v] || { label: v || '已删除', color: 'default' }
        return <Tag color={ls.color}>{ls.label}</Tag>
      },
    },
    {
      title: '冲突',
      key: 'conflict',
      width: 200,
      render: (_, r) => r.is_conflict
        ? (
          <Tooltip title={r.conflict_reason}>
            <Tag color="error" icon={<WarningOutlined />}>冲突</Tag>
            <Text type="danger" style={{ fontSize: 12 }}>{r.conflict_reason}</Text>
          </Tooltip>
        )
        : <Tag color="success">正常</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
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
        <div>
          <Button type="link" icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)} style={{ paddingLeft: 0 }}>
            返回列表
          </Button>
          <Space size={12} align="center" style={{ marginTop: 4 }} wrap>
            <Title level={4} style={{ margin: 0 }}>交接单详情</Title>
            <Tag color={statusInfo.color} style={{ fontSize: 14, padding: '4px 12px' }}>
              {statusInfo.label}
            </Tag>
            {revokeInfo.color !== 'default' && (
              <Tag color={revokeInfo.color} style={{ fontSize: 14, padding: '4px 12px' }}>
                {revokeInfo.label}
              </Tag>
            )}
            <Tag color="blue">{data.sheet_no}</Tag>
            {data.has_conflict && (
              <Badge count="有冲突" style={{ backgroundColor: '#faad14' }}>
                <Tag color="warning" icon={<WarningOutlined />}>冲突</Tag>
              </Badge>
            )}
          </Space>
        </div>
        <Space wrap>
          <Button icon={<DownloadOutlined />} onClick={handleExportDetail}>
            导出明细
          </Button>
          <Button icon={<SearchOutlined />} onClick={handleCheckConflicts}>
            检查冲突
          </Button>
          <Button icon={<SafetyCertificateOutlined />} onClick={() => setTokenValidateOpen(true)}>
            校验凭证
          </Button>
          {canSignNow && (
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              onClick={() => setSignOpen(true)}
              disabled={data.has_conflict || data.status !== 'pending'}
            >
              签收
            </Button>
          )}
          {data.status === 'signed' && canManage && (
            <Button danger icon={<RollbackOutlined />} onClick={handleRevokeSign}>
              撤回签收
            </Button>
          )}
          {data.revoke_status === 'revoked' && canManage && (
            <Button type="primary" icon={<ReloadOutlined />} onClick={handleReopen}>
              重开
            </Button>
          )}
          {data.status !== 'voided' && user?.role === 'admin' && (
            <Button danger icon={<StopOutlined />} onClick={() => setVoidOpen(true)}>
              作废
            </Button>
          )}
        </Space>
      </div>

      {data.status === 'voided' && (
        <div style={{ padding: '0 16px' }}>
          <Alert
            type="warning"
            showIcon
            message="该交接单已作废"
            description={`作废时间：${data.voided_at ? dayjs(data.voided_at).format('YYYY-MM-DD HH:mm:ss') : '—'}，作废人：${data.voided_by_name || '—'}，作废原因：${data.void_reason || '未填写'}`}
            style={{ marginBottom: 16 }}
          />
        </div>
      )}

      {data.revoke_status === 'revoked' && (
        <div style={{ padding: '0 16px' }}>
          <Alert
            type="warning"
            showIcon
            message="签收已被撤回"
            description={`撤回时间：${data.revoked_at ? dayjs(data.revoked_at).format('YYYY-MM-DD HH:mm:ss') : '—'}，撤回人：${data.revoked_by_name || '—'}，原因：${data.revoke_reason || '未填写'}`}
            style={{ marginBottom: 16 }}
          />
        </div>
      )}

      {data.revoke_status === 'reopened' && (
        <div style={{ padding: '0 16px' }}>
          <Alert
            type="info"
            showIcon
            message="该交接单已重开"
            description={`重开时间：${data.reopened_at ? dayjs(data.reopened_at).format('YYYY-MM-DD HH:mm:ss') : '—'}，重开人：${data.reopened_by_name || '—'}`}
            style={{ marginBottom: 16 }}
          />
        </div>
      )}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={16}>
          <Card title="价签明细" size="small">
            <Table
              rowKey="id"
              size="small"
              columns={itemColumns}
              dataSource={data.items || []}
              scroll={{ x: 1400 }}
              pagination={false}
              rowClassName={(r) => r.is_conflict ? 'conflict-row' : ''}
            />
          </Card>

          {(data.receipts && data.receipts.length > 0) && (
            <Card
              title={<Space><FileTextOutlined />交接回执 ({data.receipts.length})</Space>}
              size="small"
              style={{ marginTop: 16 }}
              extra={
                <Button
                  size="small"
                  onClick={() => exportApi.receipts()}
                  icon={<DownloadOutlined />}
                >
                  导出CSV
                </Button>
              }
            >
              <List
                size="small"
                dataSource={data.receipts}
                renderItem={(rcpt) => (
                  <Card
                    size="small"
                    style={{
                      marginBottom: 12,
                      borderLeft: '4px solid #52c41a',
                      background: 'linear-gradient(135deg, #f6ffed 0%, #ffffff 60%)',
                    }}
                    title={
                      <Space>
                        <Tag color="green">回执 #{rcpt.id}</Tag>
                        <Text strong>{rcpt.receipt_no}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {dayjs(rcpt.signed_at).format('YYYY-MM-DD HH:mm:ss')}
                        </Text>
                      </Space>
                    }
                    extra={
                      <Space>
                        <Tag color="blue">{rcpt.signed_by_name || '未知用户'}</Tag>
                        {rcpt.signer_ip && <Tag>{rcpt.signer_ip}</Tag>}
                      </Space>
                    }
                  >
                    <Descriptions size="small" column={2} bordered>
                      <Descriptions.Item label="价签数量">{rcpt.item_count}</Descriptions.Item>
                      <Descriptions.Item label="导出次数">{rcpt.export_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="签收人备注" span={2}>
                        {rcpt.signer_remark || <Text type="secondary">(无)</Text>}
                      </Descriptions.Item>
                      <Descriptions.Item label="防篡改哈希 (SHA256)" span={2}>
                        <Text copyable code style={{ fontSize: 12, wordBreak: 'break-all' }}>
                          {rcpt.receipt_hash}
                        </Text>
                      </Descriptions.Item>
                      {rcpt.last_exported_at && (
                        <Descriptions.Item label="最后导出时间" span={2}>
                          {dayjs(rcpt.last_exported_at).format('YYYY-MM-DD HH:mm:ss')}
                        </Descriptions.Item>
                      )}
                    </Descriptions>
                  </Card>
                )}
              />
            </Card>
          )}
        </Col>

        <Col xs={24} lg={8}>
          <Card
            title={<Space><SafetyCertificateOutlined />授权信息</Space>}
            size="small"
          >
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="指派接手人">
                {data.assigned_to_name
                  ? <Space><Tag color="blue">{data.assigned_to_name}</Tag>
                    {data.assigned_at && <Text type="secondary">{dayjs(data.assigned_at).format('MM-DD HH:mm')}</Text>}
                  </Space>
                  : <Text type="secondary">尚未指派</Text>
                }
              </Descriptions.Item>
              <Descriptions.Item label="指派操作人">
                {data.assigned_by_name || <Text type="secondary">—</Text>}
              </Descriptions.Item>
              <Descriptions.Item label="查看范围">
                <Tag color={scopeInfo.color}>{scopeInfo.label}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="当前用户">
                <Space>
                  <Tag color="purple">{data.current_user_name || user?.username}</Tag>
                  <Tag>{data.current_user_role || user?.role}</Tag>
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="签收权限">
                {canSignNow
                  ? <Tag color="green" icon={<CheckCircleOutlined />}>有权限签收</Tag>
                  : <Tag color="red" icon={<StopOutlined />}>无权限签收</Tag>
                }
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {data.authorizations && data.authorizations.length > 0 && (
            <Card
              title={<Space><KeyOutlined />授权凭证 ({data.authorizations.length})</Space>}
              size="small"
              style={{ marginTop: 16 }}
            >
              <List
                size="small"
                dataSource={data.authorizations.slice(0, 8)}
                renderItem={(auth) => {
                  const tInfo = TOKEN_TYPE_MAP[auth.token_type] || TOKEN_TYPE_MAP.sign
                  return (
                    <List.Item
                      actions={[
                        <Tooltip key="copy" title="复制凭证">
                          <Button
                            size="small"
                            icon={<CopyOutlined />}
                            onClick={() => {
                              navigator.clipboard?.writeText(auth.auth_token)
                              message.success('凭证已复制')
                            }}
                          />
                        </Tooltip>,
                      ]}
                    >
                      <List.Item.Meta
                        avatar={<KeyOutlined style={{ color: '#722ed1' }} />}
                        title={
                          <Space direction="vertical" size={2}>
                            <Space>
                              <Tag color={tInfo.color}>{tInfo.label}</Tag>
                              {auth.revoked && <Tag color="red">已撤回</Tag>}
                              {auth.is_used && <Tag color="green">已使用</Tag>}
                              {auth.one_time && <Tag color="orange">一次性</Tag>}
                              {auth.user_name && <Tag>{auth.user_name}</Tag>}
                              {auth.role_restriction && <Tag color="purple">角色:{auth.role_restriction}</Tag>}
                              {auth.store_restriction && <Tag color="cyan">门店:{auth.store_restriction}</Tag>}
                            </Space>
                          </Space>
                        }
                        description={
                          <Space direction="vertical" size={0} style={{ width: '100%' }}>
                            <Text copyable={{ text: auth.auth_token }} code style={{ fontSize: 12 }}>
                              {auth.auth_token}
                            </Text>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              创建：{dayjs(auth.created_at).format('MM-DD HH:mm')}
                              {' · '}到期：{dayjs(auth.expires_at).format('MM-DD HH:mm')}
                              {auth.is_used && auth.used_at && <> {' · '}使用：{dayjs(auth.used_at).format('MM-DD HH:mm')}</>}
                              {auth.revoked && auth.revoked_at && <> {' · '}撤回：{dayjs(auth.revoked_at).format('MM-DD HH:mm')}</>}
                              {auth.remark && <> {' · '}{auth.remark}</>}
                            </Text>
                          </Space>
                        }
                      />
                    </List.Item>
                  )
                }}
              />
              {data.authorizations.length > 8 && (
                <div style={{ textAlign: 'center', marginTop: 8 }}>
                  <Text type="secondary">还有 {data.authorizations.length - 8} 条凭证，请到授权签收台查看</Text>
                </div>
              )}
            </Card>
          )}

          <Card title="基本信息" size="small" style={{ marginTop: 16 }}>
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="交接单号">{data.sheet_no}</Descriptions.Item>
              <Descriptions.Item label="标题">{data.title}</Descriptions.Item>
              <Descriptions.Item label="门店">{data.store}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Space direction="vertical" size={2}>
                  <Tag color={statusInfo.color}>{statusInfo.label}</Tag>
                  {revokeInfo.color !== 'default' && <Tag color={revokeInfo.color}>{revokeInfo.label}</Tag>}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="价签数量">{data.total_items}</Descriptions.Item>
              <Descriptions.Item label="冲突状态">
                {data.has_conflict
                  ? <Tag color="error" icon={<WarningOutlined />}>有冲突</Tag>
                  : <Tag color="success">无冲突</Tag>
                }
              </Descriptions.Item>
              {data.remark && <Descriptions.Item label="备注">{data.remark}</Descriptions.Item>}
              <Descriptions.Item label="创建人">{data.created_by_name || `ID:${data.created_by}`}</Descriptions.Item>
              <Descriptions.Item label="创建时间">{dayjs(data.created_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
              {data.signed_by && (
                <>
                  <Descriptions.Item label="签收人">{data.signed_by_name || `ID:${data.signed_by}`}</Descriptions.Item>
                  <Descriptions.Item label="签收时间">{dayjs(data.signed_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
                </>
              )}
              {data.voided_by && (
                <>
                  <Descriptions.Item label="作废人">{data.voided_by_name || `ID:${data.voided_by}`}</Descriptions.Item>
                  <Descriptions.Item label="作废时间">{dayjs(data.voided_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
                  <Descriptions.Item label="作废原因">{data.void_reason}</Descriptions.Item>
                </>
              )}
              {data.conflict_checked_at && (
                <Descriptions.Item label="最近冲突检查">{dayjs(data.conflict_checked_at).format('YYYY-MM-DD HH:mm:ss')}</Descriptions.Item>
              )}
            </Descriptions>
          </Card>

          {(data.logs?.length > 0) && (
            <Card title="操作日志" size="small" style={{ marginTop: 16 }}>
              <Timeline
                items={data.logs.map(log => {
                  const actionInfo = ACTION_MAP[log.action] || { label: log.action, color: 'default' }
                  return {
                    color: actionInfo.color === 'red' ? 'red' : actionInfo.color === 'green' ? 'green' : 'blue',
                    children: (
                      <div>
                        <Space size={4}>
                          <Tag color={actionInfo.color} style={{ fontSize: 11 }}>{actionInfo.label}</Tag>
                          <Text type="secondary" style={{ fontSize: 12 }}>{log.operated_by_name}</Text>
                        </Space>
                        <div style={{ marginTop: 4, fontSize: 12, color: '#595959' }}>{log.detail}</div>
                        <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 2 }}>
                          {dayjs(log.created_at).format('YYYY-MM-DD HH:mm:ss')}
                        </div>
                      </div>
                    ),
                  }
                })}
              />
            </Card>
          )}
        </Col>
      </Row>

      <Modal
        title={
          <Space>
            <CheckCircleOutlined style={{ color: '#52c41a' }} />
            确认签收交接单
          </Space>
        }
        open={signOpen}
        onCancel={() => { setSignOpen(false); setSignToken(''); setSignerRemark('') }}
        onOk={handleSign}
        okText="确认签收"
        okButtonProps={{ danger: data.status === 'pending' }}
        width={560}
        destroyOnClose
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="warning"
            showIcon
            message="签收后将标记所有价签为已打印，此操作可通过撤回签收+重开进行修正。"
          />

          {!canSignNow && (
            <Alert
              type="error"
              showIcon
              message="您不是指派签收人"
              description="请粘贴管理员提供的签收凭证进行签收"
            />
          )}

          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="交接单号" span={2}>{data.sheet_no}</Descriptions.Item>
            <Descriptions.Item label="价签数量">{data.total_items}</Descriptions.Item>
            <Descriptions.Item label="门店">{data.store}</Descriptions.Item>
            <Descriptions.Item label="当前用户" span={2}>
              <Space>
                <Tag color="purple">{data.current_user_name || user?.username}</Tag>
                <Tag>{data.current_user_role || user?.role}</Tag>
              </Space>
            </Descriptions.Item>
          </Descriptions>

          <Form layout="vertical">
            <Form.Item
              label={
                <Space>
                  <KeyOutlined />签收凭证
                  {canSignNow ? <Text type="secondary">（非必须，您是指派签收人可不填）</Text> : <Text type="danger">（必须）</Text>}
                </Space>
              }
              required={!canSignNow}
            >
              <Input
                prefix={<KeyOutlined />}
                placeholder="粘贴管理员发送的签收凭证 sign_token"
                value={signToken}
                onChange={e => setSignToken(e.target.value)}
                allowClear
                size="large"
              />
            </Form.Item>
            <Form.Item label="签收人备注（可选）">
              <TextArea
                rows={2}
                placeholder="例如：已核对所有价签无误，现场打印完毕。"
                value={signerRemark}
                onChange={e => setSignerRemark(e.target.value)}
                maxLength={200}
                showCount
              />
            </Form.Item>
          </Form>

          {data.has_conflict && (
            <Alert
              type="error"
              showIcon
              message="当前交接单存在冲突项，无法签收。请先处理冲突。"
            />
          )}
        </Space>
      </Modal>

      <Modal
        title={<Space><SafetyCertificateOutlined />凭证校验台</Space>}
        open={tokenValidateOpen}
        onCancel={() => { setTokenValidateOpen(false); setTokenValidateResult(null); validateForm.resetFields() }}
        footer={null}
        width={520}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          message="前后端独立校验"
          description="前端先通过 /validate 端点预校验，签收时后端再次校验，避免TOCTOU问题"
          style={{ marginBottom: 16 }}
        />
        <Form form={validateForm} layout="vertical">
          <Form.Item
            label="凭证 (sign_token / view_token)"
            name="token"
            rules={[{ required: true, message: '请输入凭证' }]}
          >
            <Input size="large" placeholder="粘贴任意类型的授权凭证" prefix={<KeyOutlined />} />
          </Form.Item>
          <Button type="primary" onClick={handleValidateToken} icon={<SendOutlined />} block>
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
                  {tokenValidateResult.code && <p><b>拦截码：</b><Tag color="red">{tokenValidateResult.code}</Tag></p>}
                  {BLOCK_CODE_HINTS[tokenValidateResult.code] && (
                    <p style={{ color: '#666' }}>{BLOCK_CODE_HINTS[tokenValidateResult.code]}</p>
                  )}
                  {tokenValidateResult.valid && (
                    <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
                      {tokenValidateResult.sheet_id !== undefined && (
                        <Descriptions.Item label="交接单ID">{tokenValidateResult.sheet_id}</Descriptions.Item>
                      )}
                      {tokenValidateResult.token_type && (
                        <Descriptions.Item label="凭证类型">
                          {TOKEN_TYPE_MAP[tokenValidateResult.token_type]?.label || tokenValidateResult.token_type}
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
                      {tokenValidateResult.one_time !== undefined && (
                        <Descriptions.Item label="是否一次性">
                          {tokenValidateResult.one_time ? '是（用后即焚）' : '否'}
                        </Descriptions.Item>
                      )}
                    </Descriptions>
                  )}
                </div>
              }
            />
          </div>
        )}
      </Modal>

      <Modal
        title="作废交接单"
        open={voidOpen}
        onCancel={() => { setVoidOpen(false); voidForm.resetFields() }}
        onOk={() => voidForm.submit()}
        okText="确认作废"
        okButtonProps={{ danger: true }}
        width={560}
        destroyOnClose
      >
        <Form form={voidForm} layout="vertical" onFinish={handleVoid}>
          <Form.Item
            name="reason"
            label="作废原因"
            rules={[{ required: true, message: '请填写作废原因' }]}
          >
            <TextArea rows={4} placeholder="请详细说明作废原因" maxLength={200} showCount />
          </Form.Item>
          <div style={{ padding: 12, background: '#fff2f0', borderRadius: 6, border: '1px solid #ffccc7' }}>
            <Text type="danger" strong>
              <ExclamationCircleOutlined /> 作废后该交接单将不可恢复（状态永远为voided），但历史记录会保留。
              已签收的交接单作废后，不会撤销已打印状态。若想撤销签收请使用"撤回签收+重开"。
            </Text>
          </div>
        </Form>
      </Modal>
    </div>
  )
}
