import React, { useState, useEffect, useRef } from 'react'
import {
  Card, Button, Space, Typography, Tag, Row, Col, Steps,
  App as AntApp, Descriptions, Alert, Divider, List, Badge,
  Collapse, Empty, Spin, Result, Modal,
} from 'antd'
import {
  PlayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ClockCircleOutlined, DownloadOutlined, ReloadOutlined,
  ArrowLeftOutlined, ArrowRightOutlined, ExclamationCircleOutlined,
  FileTextOutlined, ApiOutlined,
} from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Text, Paragraph } = Typography
const { Step } = Steps
const { Panel } = Collapse

const ROLE_LABEL = {
  admin: '管理员',
  operator: '运营',
  clerk: '店员',
}

const STATUS_MAP = {
  pending: { label: '待执行', color: 'default', icon: <ClockCircleOutlined /> },
  in_progress: { label: '进行中', color: 'processing', icon: <Spin size="small" /> },
  completed: { label: '已完成', color: 'success', icon: <CheckCircleOutlined /> },
  failed: { label: '失败', color: 'error', icon: <CloseCircleOutlined /> },
}

export default function DrillSessionPage({ user }) {
  const { id } = useParams()
  const navigate = useNavigate()
  const { message, modal } = AntApp.useApp()
  const [session, setSession] = useState(null)
  const [steps, setSteps] = useState([])
  const [loading, setLoading] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [currentStep, setCurrentStep] = useState(0)
  const [acceptanceRecords, setAcceptanceRecords] = useState([])
  const stepsRef = useRef([])

  useEffect(() => {
    loadSession()
  }, [id])

  useEffect(() => {
    stepsRef.current = steps
  }, [steps])

  const loadSession = async () => {
    setLoading(true)
    try {
      const res = await api.get(`/drill/sessions/${id}`)
      setSession(res.data)
      setSteps(res.data.steps || [])
      setAcceptanceRecords(res.data.acceptance_records || [])

      const pendingIndex = (res.data.steps || []).findIndex(s => s.status === 'pending')
      if (pendingIndex >= 0) {
        setCurrentStep(pendingIndex)
      } else {
        setCurrentStep((res.data.steps || []).length - 1)
      }
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleExecuteStep = async (stepKey) => {
    setExecuting(true)
    try {
      const res = await api.post(`/drill/sessions/${id}/steps/${stepKey}/execute`)
      message.success(res.action_result?.message || '执行成功')

      const idx = stepsRef.current.findIndex(s => s.step_key === stepKey)
      const newSteps = [...stepsRef.current]
      if (res.data?.step) {
        newSteps[idx] = res.data.step
      }
      setSteps(newSteps)

      if (res.data?.session) {
        setSession(prev => ({ ...prev, ...res.data.session }))
      }

      if (idx + 1 < newSteps.length) {
        setCurrentStep(idx + 1)
      }
    } catch (err) {
      message.error(err.message)
    } finally {
      setExecuting(false)
    }
  }

  const handleExecuteAll = () => {
    modal.confirm({
      title: '自动执行所有步骤',
      content: '系统将自动按顺序执行所有演练步骤，确定要继续吗？',
      onOk: () => executeAllSteps(),
    })
  }

  const executeAllSteps = async () => {
    const pendingSteps = steps.filter(s => s.status === 'pending')
    for (const step of pendingSteps) {
      await handleExecuteStep(step.step_key)
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    loadSession()
  }

  const handleRestart = () => {
    modal.confirm({
      title: '重置演练',
      content: '确定要重置本次演练吗？所有步骤将重置为待执行状态。',
      onOk: async () => {
        try {
          await api.post(`/drill/sessions/${id}/restart`)
          message.success('演练已重置')
          loadSession()
        } catch (err) {
          message.error(err.message)
        }
      },
    })
  }

  const handleExportAcceptance = () => {
    window.open(`/api/drill/export/acceptance/${id}`, '_blank')
    message.success('已开始导出验收记录')
  }

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!session) {
    return <Empty description="演练会话不存在" />
  }

  const currentStepData = steps[currentStep]
  const isCompleted = session.status === 'completed'
  const passRate = session.total_steps > 0
    ? Math.round((session.completed_steps / session.total_steps) * 100)
    : 0

  return (
    <div style={{ padding: '16px 0' }}>
      <div className="action-bar">
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/drill')}>
            返回演练中心
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            {session.title}
          </Title>
          <Tag color={isCompleted ? 'green' : 'processing'}>
            {isCompleted ? '已完成' : '进行中'}
          </Tag>
        </Space>
        <Space>
          {!isCompleted && (
            <>
              <Button icon={<PlayCircleOutlined />} onClick={handleExecuteAll}>
                一键执行
              </Button>
              <Button icon={<ReloadOutlined />} onClick={handleRestart}>
                重置演练
              </Button>
            </>
          )}
          {isCompleted && (
            <Button icon={<DownloadOutlined />} type="primary" onClick={handleExportAcceptance}>
              导出验收记录
            </Button>
          )}
        </Space>
      </div>

      <Row gutter={16}>
        <Col xs={24} lg={6}>
          <Card title="演练概览" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="场景">{session.scenario_name}</Descriptions.Item>
              <Descriptions.Item label="角色">
                <Tag color={user?.role === session.role ? 'blue' : 'default'}>
                  {ROLE_LABEL[session.role] || session.role}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="总步骤">{session.total_steps}</Descriptions.Item>
              <Descriptions.Item label="已完成">{session.completed_steps}</Descriptions.Item>
              <Descriptions.Item label="失败">{session.failed_steps}</Descriptions.Item>
              <Descriptions.Item label="开始时间">
                {dayjs(session.start_time).format('MM-DD HH:mm')}
              </Descriptions.Item>
              {session.end_time && (
                <Descriptions.Item label="结束时间">
                  {dayjs(session.end_time).format('MM-DD HH:mm')}
                </Descriptions.Item>
              )}
            </Descriptions>

            <Divider style={{ margin: '12px 0' }} />

            <div style={{ textAlign: 'center' }}>
              <Text type="secondary">完成进度</Text>
              <div style={{ fontSize: 28, fontWeight: 'bold', color: isCompleted ? '#52c41a' : '#1677ff' }}>
                {passRate}%
              </div>
            </div>
          </Card>

          <Card title="步骤导航" size="small" style={{ marginTop: 16 }}>
            <Steps
              direction="vertical"
              size="small"
              current={currentStep}
              status={isCompleted ? 'finish' : 'process'}
              items={steps.map((step, idx) => ({
                title: (
                  <Space size={4} onClick={() => setCurrentStep(idx)} style={{ cursor: 'pointer' }}>
                    {step.is_exception_branch && <ExclamationCircleOutlined style={{ color: '#faad14' }} />}
                    <Text style={{ fontSize: 12 }}>{step.step_name}</Text>
                  </Space>
                ),
                status: step.status === 'completed' ? 'finish' : step.status === 'failed' ? 'error' : step.status === 'in_progress' ? 'process' : 'wait',
              }))}
            />
          </Card>
        </Col>

        <Col xs={24} lg={18}>
          {currentStepData && (
            <Card
              title={
                <Space>
                  <span>步骤 {currentStep + 1}: {currentStepData.step_name}</span>
                  {currentStepData.is_exception_branch && (
                    <Tag color="orange">异常分支</Tag>
                  )}
                  <Tag color={STATUS_MAP[currentStepData.status]?.color || 'default'}>
                    {STATUS_MAP[currentStepData.status]?.label || currentStepData.status}
                  </Tag>
                </Space>
              }
              extra={
                <Space>
                  {currentStep > 0 && (
                    <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => setCurrentStep(currentStep - 1)}>
                      上一步
                    </Button>
                  )}
                  {currentStep < steps.length - 1 && (
                    <Button size="small" onClick={() => setCurrentStep(currentStep + 1)}>
                      下一步 <ArrowRightOutlined />
                    </Button>
                  )}
                </Space>
              }
            >
              {currentStepData.step_description && (
                <Alert
                  message="步骤说明"
                  description={currentStepData.step_description}
                  type="info"
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              )}

              {currentStepData.is_exception_branch && currentStepData.exception_description && (
                <Alert
                  message="异常分支说明"
                  description={currentStepData.exception_description}
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              )}

              <Row gutter={16}>
                <Col span={12}>
                  <div style={{ marginBottom: 12 }}>
                    <Text strong>预期结果：</Text>
                  </div>
                  <div style={{ padding: 12, background: '#f6ffed', borderRadius: 6, border: '1px solid #b7eb8f' }}>
                    <Text type="success">{currentStepData.expected_result || '无'}</Text>
                  </div>
                </Col>
                <Col span={12}>
                  <div style={{ marginBottom: 12 }}>
                    <Text strong>实际结果：</Text>
                  </div>
                  <div
                    style={{
                      padding: 12,
                      borderRadius: 6,
                      border: '1px solid',
                      background: currentStepData.status === 'completed' ? '#f6ffed' : currentStepData.status === 'failed' ? '#fff2f0' : '#fafafa',
                      borderColor: currentStepData.status === 'completed' ? '#b7eb8f' : currentStepData.status === 'failed' ? '#ffa39e' : '#d9d9d9',
                    }}
                  >
                    {currentStepData.status === 'pending' ? (
                      <Text type="secondary">尚未执行</Text>
                    ) : (
                      <Text type={currentStepData.status === 'completed' ? 'success' : 'danger'}>
                        {currentStepData.actual_result || currentStepData.error_message || '-'}
                      </Text>
                    )}
                  </div>
                </Col>
              </Row>

              {currentStepData.response_data && (
                <Collapse style={{ marginTop: 16 }} size="small">
                  <Panel header="查看响应数据" key="1">
                    <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, fontSize: 12, maxHeight: 300, overflow: 'auto' }}>
                      {currentStepData.response_data}
                    </pre>
                  </Panel>
                </Collapse>
              )}

              <Divider />

              <div style={{ display: 'flex', justifyContent: 'center' }}>
                {currentStepData.status === 'pending' && (
                  <Button
                    type="primary"
                    size="large"
                    icon={<PlayCircleOutlined />}
                    loading={executing}
                    onClick={() => handleExecuteStep(currentStepData.step_key)}
                  >
                    执行此步骤
                  </Button>
                )}
                {currentStepData.status === 'completed' && (
                  <Badge status="success" text="步骤已完成" />
                )}
                {currentStepData.status === 'failed' && (
                  <Space>
                    <Badge status="error" text="步骤执行失败" />
                    <Button onClick={() => handleExecuteStep(currentStepData.step_key)}>
                      重新执行
                    </Button>
                  </Space>
                )}
              </div>
            </Card>
          )}

          {isCompleted && acceptanceRecords.length > 0 && (
            <Card
              title={<Space><FileTextOutlined /> 验收记录</Space>}
              style={{ marginTop: 16 }}
              size="small"
            >
              <List
                size="small"
                dataSource={acceptanceRecords}
                renderItem={(item) => (
                  <List.Item>
                    <List.Item.Meta
                      avatar={
                        item.passed
                          ? <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 20 }} />
                          : <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />
                      }
                      title={item.acceptance_item}
                      description={
                        <Space size={16}>
                          <Text type="secondary">分类：{item.acceptance_category || '-'}</Text>
                          <Text type="secondary">预期：{item.expected_value || '-'}</Text>
                          <Text type="secondary">实际：{item.actual_value || '-'}</Text>
                          {item.remark && <Text type="secondary">备注：{item.remark}</Text>}
                        </Space>
                      }
                    />
                    <Tag color={item.passed ? 'green' : 'red'}>
                      {item.passed ? '通过' : '不通过'}
                    </Tag>
                  </List.Item>
                )}
              />
            </Card>
          )}

          <Card
            title={<Space><ApiOutlined /> 操作提示</Space>}
            style={{ marginTop: 16 }}
            size="small"
          >
            <StepsTypeGuide stepKey={currentStepData?.step_key} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

function StepsTypeGuide({ stepKey }) {
  const guides = {
    import_demo_data: {
      title: '导入演示数据操作说明',
      points: [
        '点击"执行此步骤"按钮，系统会自动导入演练专用的演示价签数据',
        '演示数据包含6条不同门店的价签，全部为草稿状态',
        '同一批数据只能导入一次，重复导入会被系统拦截',
        '导入的数据会标记为演练专用，不会与生产数据混淆',
      ],
    },
    submit_labels: {
      title: '提交价签审批操作说明',
      points: [
        '运营角色可以提交价签进入审批流程',
        '提交后价签状态从"草稿"变为"待审批"',
        '只有草稿状态的价签才能提交审批',
        '提交后需要等待管理员审批通过才能发布',
      ],
    },
    approve_labels: {
      title: '审批价签操作说明',
      points: [
        '只有管理员角色可以审批价签',
        '审批通过后价签状态变为"已发布"',
        '同时自动加入打印清单，供门店打印',
        '如果是运营或店员角色，这一步会显示权限不足',
      ],
    },
    create_handover: {
      title: '创建交接单操作说明',
      points: [
        '管理员和运营可以创建交接单',
        '交接单用于门店之间的价签交接确认',
        '只能选择同一门店的已发布价签',
        '同一张价签不能同时在多张有效交接单中',
      ],
    },
    check_conflict: {
      title: '检查冲突操作说明',
      points: [
        '交接单创建后应检查是否存在冲突',
        '冲突可能来自：价签被撤销、价签被回滚、价签版本变更',
        '有冲突的交接单不能签收，必须先处理冲突',
        '系统会自动标记冲突项并记录冲突原因',
      ],
    },
    sign_handover: {
      title: '签收交接单操作说明',
      points: [
        '所有角色都可以签收交接单',
        '签收前必须确保没有冲突项',
        '签收后交接单状态变为"已签收"',
        '签收同时会将所有价签标记为已打印',
      ],
    },
    void_handover: {
      title: '作废交接单操作说明',
      points: [
        '只有管理员可以作废交接单',
        '作废需要填写作废原因',
        '作废后交接单不能再进行任何操作',
        '作废操作会记录到操作日志中',
      ],
    },
    exception_duplicate_import: {
      title: '重复导入拦截验证',
      points: [
        '此步骤验证重复导入的拦截逻辑',
        '系统会检查同一 data_key 是否已导入过',
        '如果已导入且处于激活状态，会返回 DUPLICATE_DATA 错误',
        '这是为了避免演示数据重复，保持数据干净',
      ],
    },
    exception_voided_sheet_drill: {
      title: '作废单继续操作拦截验证',
      points: [
        '此步骤验证已作废交接单的操作拦截',
        '已作废的交接单不能再签收、修改等',
        '系统会返回 VOIDED_SHEET 错误码',
        '保证作废状态的严肃性和数据一致性',
      ],
    },
    exception_unauthorized_sign: {
      title: '越权操作拦截验证',
      points: [
        '此步骤验证不同角色的权限边界',
        '管理员：全部权限（审批、作废、配置等）',
        '运营：导入、提交、创建交接单、签收',
        '店员：查看、打印、签收',
        '越权操作会返回 403 权限不足错误',
      ],
    },
    view_logs: {
      title: '日志回查操作说明',
      points: [
        '所有重要操作都会记录操作日志',
        '包括：创建、签收、作废、冲突检查等',
        '日志包含操作人、操作时间、操作详情',
        '日志可追溯、不可篡改，用于审计和问题排查',
      ],
    },
    export_check: {
      title: '导出与日志一致性校验',
      points: [
        '导出的数据应与日志记录保持一致',
        '包括：数量、状态、操作人、时间等',
        '如果发现不一致，说明数据可能存在问题',
        '这是数据完整性的重要保障机制',
      ],
    },
  }

  const guide = guides[stepKey]

  if (!guide) {
    return <Text type="secondary">选择左侧步骤查看操作说明</Text>
  }

  return (
    <div>
      <Text strong>{guide.title}</Text>
      <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
        {guide.points.map((p, i) => (
          <li key={i} style={{ marginBottom: 4 }}>
            <Text>{p}</Text>
          </li>
        ))}
      </ul>
    </div>
  )
}
