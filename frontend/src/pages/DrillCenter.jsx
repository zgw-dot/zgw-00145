import React, { useState, useEffect } from 'react'
import {
  Card, Button, Space, Typography, Tag, Row, Col, Select,
  App as AntApp, Modal, Form, Input, List, Avatar, Progress, Alert,
} from 'antd'
import {
  PlayCircleOutlined, HistoryOutlined, BookOutlined,
  FileTextOutlined, TeamOutlined, CheckCircleOutlined,
  ClockCircleOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import api from '../utils/api.js'

const { Title, Text, Paragraph } = Typography
const { Option } = Select

const ROLE_LABEL = {
  admin: '管理员',
  operator: '运营',
  clerk: '店员',
}

const ROLE_COLOR = {
  admin: 'red',
  operator: 'blue',
  clerk: 'green',
}

export default function DrillCenter({ user }) {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [scenarios, setScenarios] = useState([])
  const [loading, setLoading] = useState(false)
  const [startModalVisible, setStartModalVisible] = useState(false)
  const [selectedScenario, setSelectedScenario] = useState(null)
  const [startForm] = Form.useForm()
  const [recentSessions, setRecentSessions] = useState([])

  useEffect(() => {
    loadScenarios()
    loadRecentSessions()
  }, [])

  const loadScenarios = async () => {
    try {
      const res = await api.get('/drill/scenarios')
      setScenarios(res.data)
    } catch (err) {
      message.error(err.message)
    }
  }

  const loadRecentSessions = async () => {
    try {
      const res = await api.get('/drill/sessions?size=5')
      setRecentSessions(res.data.list || [])
    } catch (err) {
      // 忽略错误
    }
  }

  const handleStartDrill = (scenario) => {
    setSelectedScenario(scenario)
    setStartModalVisible(true)
    startForm.setFieldsValue({
      title: `${scenario.name} - ${ROLE_LABEL[user.role]}角色`,
      role: user.role,
    })
  }

  const handleStartSubmit = async (values) => {
    setLoading(true)
    try {
      const res = await api.post('/drill/start', {
        scenario_key: selectedScenario.key,
        role: values.role,
        title: values.title,
      })
      message.success('演练已开始')
      setStartModalVisible(false)
      navigate(`/drill/session/${res.data.id}`)
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: '24px 0' }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          <PlayCircleOutlined style={{ color: '#1677ff', marginRight: 8 }} />
          交接单演练中心
        </Title>
        <Text type="secondary">
          不看源码也能完整跑通建单、补充价签、签收、作废、撤销联动和日志回查
        </Text>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} md={6}>
          <Card size="small" onClick={() => navigate('/drill')} style={{ cursor: 'pointer', borderColor: '#1677ff' }}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <PlayCircleOutlined style={{ fontSize: 24, color: '#1677ff' }} />
              <Text strong>开始演练</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>选择场景，按步骤操作</Text>
            </Space>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small" onClick={() => navigate('/drill/history')} style={{ cursor: 'pointer' }}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <HistoryOutlined style={{ fontSize: 24, color: '#52c41a' }} />
              <Text strong>演练历史</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>查看过往演练记录</Text>
            </Space>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small" onClick={() => navigate('/drill/api-docs')} style={{ cursor: 'pointer' }}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <BookOutlined style={{ fontSize: 24, color: '#fa8c16' }} />
              <Text strong>接口说明</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>所有接口文档与示例</Text>
            </Space>
          </Card>
        </Col>
        <Col xs={24} sm={12} md={6}>
          <Card size="small" onClick={() => navigate('/drill/checklist')} style={{ cursor: 'pointer' }}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <FileTextOutlined style={{ fontSize: 24, color: '#722ed1' }} />
              <Text strong>操作清单</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>照着就能复现的步骤</Text>
            </Space>
          </Card>
        </Col>
      </Row>

      <Title level={4} style={{ marginBottom: 16 }}>
        <TeamOutlined style={{ marginRight: 8 }} />
        演练场景
      </Title>

      <Row gutter={[16, 16]}>
        {scenarios.map((scenario) => (
          <Col xs={24} md={12} lg={8} key={scenario.key}>
            <Card
              hoverable
              actions={[
                <Button
                  type="primary"
                  icon={<PlayCircleOutlined />}
                  onClick={() => handleStartDrill(scenario)}
                  block
                >
                  开始演练
                </Button>,
              ]}
            >
              <Card.Meta
                title={
                  <Space>
                    {scenario.name}
                    <Tag color="blue">{scenario.step_count}步</Tag>
                  </Space>
                }
                description={
                  <div>
                    <Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ marginBottom: 8 }}>
                      {scenario.description}
                    </Paragraph>
                    <Space wrap>
                      {scenario.roles.map((r) => (
                        <Tag key={r} color={ROLE_COLOR[r]}>
                          {ROLE_LABEL[r]}
                        </Tag>
                      ))}
                    </Space>
                  </div>
                }
              />
            </Card>
          </Col>
        ))}
      </Row>

      <Title level={4} style={{ marginTop: 32, marginBottom: 16 }}>
        <ClockCircleOutlined style={{ marginRight: 8 }} />
        最近演练
      </Title>

      <Card bodyStyle={{ padding: 0 }}>
        {recentSessions.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: '#999' }}>
            暂无演练记录，点击上方场景开始第一次演练
          </div>
        ) : (
          <List
            dataSource={recentSessions}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button type="link" onClick={() => navigate(`/drill/session/${item.id}`)}>
                    查看详情
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  avatar={
                    <Avatar
                      icon={item.status === 'completed' ? <CheckCircleOutlined /> : <ClockCircleOutlined />}
                      style={{ backgroundColor: item.status === 'completed' ? '#52c41a' : '#1677ff' }}
                    />
                  }
                  title={
                    <Space>
                      {item.title}
                      <Tag color={item.status === 'completed' ? 'green' : 'processing'}>
                        {item.status === 'completed' ? '已完成' : '进行中'}
                      </Tag>
                    </Space>
                  }
                  description={
                    <Space size={16}>
                      <Text type="secondary">场景：{item.scenario_name}</Text>
                      <Text type="secondary">角色：{ROLE_LABEL[item.role] || item.role}</Text>
                      <Text type="secondary">
                        进度：{item.completed_steps}/{item.total_steps}
                      </Text>
                      <Text type="secondary">
                        {dayjs(item.created_at).format('YYYY-MM-DD HH:mm')}
                      </Text>
                    </Space>
                  }
                />
                <Progress
                  percent={Math.round((item.completed_steps / item.total_steps) * 100)}
                  size="small"
                  style={{ width: 120 }}
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Modal
        title="开始演练"
        open={startModalVisible}
        onCancel={() => setStartModalVisible(false)}
        onOk={() => startForm.submit()}
        confirmLoading={loading}
        okText="开始"
        width={500}
      >
        {selectedScenario && (
          <Form form={startForm} layout="vertical" onFinish={handleStartSubmit}>
            <div style={{ marginBottom: 16, padding: 12, background: '#f5f5f5', borderRadius: 6 }}>
              <Text strong>{selectedScenario.name}</Text>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {selectedScenario.description}
              </Text>
              <br />
              <Text type="secondary" style={{ fontSize: 12 }}>
                共 {selectedScenario.step_count} 个步骤
              </Text>
            </div>

            <Form.Item
              name="title"
              label="演练标题"
              rules={[{ required: true, message: '请输入演练标题' }]}
            >
              <Input placeholder="输入演练标题" maxLength={100} showCount />
            </Form.Item>

            <Form.Item
              name="role"
              label="演练角色"
              rules={[{ required: true, message: '请选择演练角色' }]}
            >
              <Select>
                {selectedScenario.roles?.map((r) => (
                  <Option key={r} value={r}>
                    {ROLE_LABEL[r]} ({r === user.role ? '当前角色' : '切换角色'})
                  </Option>
                ))}
              </Select>
            </Form.Item>

            <Alert
              message="演练说明"
              description={
                <ul style={{ margin: 0, paddingLeft: 16 }}>
                  <li>演练会自动创建演示数据，不会影响生产数据</li>
                  <li>每一步都有操作提示和预期结果</li>
                  <li>演练记录会保存，可随时回看</li>
                  <li>包含正常流程和异常分支验证</li>
                </ul>
              }
              type="info"
              showIcon
            />
          </Form>
        )}
      </Modal>
    </div>
  )
}
