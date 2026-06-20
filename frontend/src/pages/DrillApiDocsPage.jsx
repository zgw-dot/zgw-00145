import React, { useState, useEffect } from 'react'
import {
  Card, Typography, Tabs, Table, Tag, Space, Collapse, Descriptions,
  App as AntApp, Alert,
} from 'antd'
import {
  ApiOutlined, BookOutlined, CodeOutlined,
} from '@ant-design/icons'
import api from '../utils/api.js'

const { Title, Text, Paragraph } = Typography
const { TabPane } = Tabs
const { Panel } = Collapse

const METHOD_COLOR = {
  GET: 'green',
  POST: 'blue',
  PUT: 'orange',
  DELETE: 'red',
}

const ROLE_LABEL = {
  admin: '管理员',
  operator: '运营',
  clerk: '店员',
}

export default function DrillApiDocsPage() {
  const { message } = AntApp.useApp()
  const [docs, setDocs] = useState({})
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    loadDocs()
  }, [])

  const loadDocs = async () => {
    setLoading(true)
    try {
      const res = await api.get('/drill/api-docs')
      setDocs(res.data || {})
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const renderEndpoints = (endpoints) => {
    const columns = [
      {
        title: '方法',
        dataIndex: 'method',
        key: 'method',
        width: 80,
        render: (v) => <Tag color={METHOD_COLOR[v] || 'default'}>{v}</Tag>,
      },
      {
        title: '路径',
        dataIndex: 'path',
        key: 'path',
        width: 280,
        render: (v) => <Text code>{v}</Text>,
      },
      {
        title: '说明',
        dataIndex: 'description',
        key: 'description',
      },
      {
        title: '权限角色',
        dataIndex: 'roles',
        key: 'roles',
        width: 180,
        render: (roles) => (
          <Space wrap>
            {roles?.map(r => (
              <Tag key={r}>{ROLE_LABEL[r] || r}</Tag>
            ))}
          </Space>
        ),
      },
      {
        title: '参数',
        dataIndex: 'params',
        key: 'params',
        width: 200,
        render: (params) => params?.join(', ') || '无',
      },
    ]

    return (
      <Table
        rowKey="path"
        columns={columns}
        dataSource={endpoints}
        pagination={false}
        size="small"
        expandable={{
          expandedRowRender: (record) => (
            <div>
              {record.example?.request && (
                <div style={{ marginBottom: 12 }}>
                  <Text strong>请求示例：</Text>
                  <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, marginTop: 4 }}>
                    {typeof record.example.request === 'string'
                      ? record.example.request
                      : JSON.stringify(record.example.request, null, 2)}
                  </pre>
                </div>
              )}
              {record.example?.response && (
                <div>
                  <Text strong>响应示例：</Text>
                  <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, marginTop: 4, maxHeight: 300, overflow: 'auto' }}>
                    {typeof record.example.response === 'string'
                      ? record.example.response
                      : JSON.stringify(record.example.response, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ),
        }}
      />
    )
  }

  return (
    <div style={{ padding: '16px 0' }}>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>
          <BookOutlined style={{ color: '#fa8c16' }} /> 接口说明
        </Title>
      </div>

      <Alert
        message="接口说明"
        description="本页列出交接单和价签相关的所有核心接口，包含请求方法、路径、参数、权限角色和示例。点击每行可展开查看请求响应示例。"
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Card loading={loading}>
        <Tabs defaultActiveKey="handover">
          {Object.entries(docs).map(([key, section]) => (
            <TabPane tab={section.title} key={key}>
              {renderEndpoints(section.endpoints || [])}
            </TabPane>
          ))}
        </Tabs>
      </Card>

      <Card title={<Space><CodeOutlined /> 演练中心专用接口</Space>} style={{ marginTop: 16 }}>
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="GET /api/drill/scenarios">获取演练场景列表</Descriptions.Item>
          <Descriptions.Item label="POST /api/drill/start">开始一次演练</Descriptions.Item>
          <Descriptions.Item label="GET /api/drill/sessions">演练历史列表</Descriptions.Item>
          <Descriptions.Item label="GET /api/drill/sessions/:id">演练详情（含步骤）</Descriptions.Item>
          <Descriptions.Item label="POST /api/drill/sessions/:id/steps/:key/execute">执行演练步骤</Descriptions.Item>
          <Descriptions.Item label="GET /api/drill/sessions/:id/timeline">演练时间线</Descriptions.Item>
          <Descriptions.Item label="POST /api/drill/sessions/:id/restart">重置演练</Descriptions.Item>
          <Descriptions.Item label="POST /api/drill/demo-data/import">导入演示数据</Descriptions.Item>
          <Descriptions.Item label="GET /api/drill/demo-data">演示数据列表</Descriptions.Item>
          <Descriptions.Item label="POST /api/drill/demo-data/:key/reset">重置演示数据</Descriptions.Item>
          <Descriptions.Item label="GET /api/drill/api-docs">接口文档</Descriptions.Item>
          <Descriptions.Item label="GET /api/drill/checklist">操作清单</Descriptions.Item>
          <Descriptions.Item label="GET /api/drill/export/acceptance/:id">导出验收记录</Descriptions.Item>
          <Descriptions.Item label="GET /api/drill/export/checklist/:scenario">导出操作清单</Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  )
}
