import React, { useState, useEffect } from 'react'
import {
  Card, Typography, List, Tag, Space, Button, Alert,
  App as AntApp, Select,
} from 'antd'
import {
  FileTextOutlined, CheckCircleOutlined, ExclamationCircleOutlined,
  DownloadOutlined,
} from '@ant-design/icons'
import api from '../utils/api.js'

const { Title, Text, Paragraph } = Typography
const { Option } = Select

export default function DrillChecklistPage() {
  const { message } = AntApp.useApp()
  const [checklist, setChecklist] = useState(null)
  const [loading, setLoading] = useState(false)
  const [scenario, setScenario] = useState('handover_full_flow')

  useEffect(() => {
    loadChecklist(scenario)
  }, [scenario])

  const loadChecklist = async (scenarioKey) => {
    setLoading(true)
    try {
      const res = await api.get(`/drill/checklist?scenario=${scenarioKey}`)
      setChecklist(res.data)
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleExport = () => {
    window.open(`/api/drill/export/checklist/${scenario}`, '_blank')
    message.success('已开始导出操作清单')
  }

  return (
    <div style={{ padding: '16px 0' }}>
      <div className="action-bar">
        <Space>
          <Title level={4} style={{ margin: 0 }}>
            <FileTextOutlined style={{ color: '#722ed1' }} /> 操作清单
          </Title>
          <Select
            value={scenario}
            onChange={setScenario}
            style={{ width: 240 }}
          >
            <Option value="handover_full_flow">交接单完整流程演练</Option>
          </Select>
        </Space>
        <Button icon={<DownloadOutlined />} type="primary" onClick={handleExport}>
          导出操作清单
        </Button>
      </div>

      <Alert
        message="操作清单说明"
        description="照着这份清单就能完整复现所有操作，包含正常流程和异常分支。每一步都有详细的操作步骤和预期结果。"
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Card loading={loading} title={checklist?.scenario_name}>
        {checklist?.checklist?.length > 0 && (
          <List
            dataSource={checklist.checklist}
            renderItem={(item, index) => (
              <List.Item key={item.step_number}>
                <List.Item.Meta
                  avatar={
                    item.is_exception
                      ? <ExclamationCircleOutlined style={{ color: '#faad14', fontSize: 20 }} />
                      : <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 20 }} />
                  }
                  title={
                    <Space>
                      <Text strong>步骤 {index + 1}: {item.step_name}</Text>
                      {item.is_exception && <Tag color="orange">异常分支</Tag>}
                    </Space>
                  }
                  description={
                    <div>
                      <Paragraph style={{ marginBottom: 8 }}>
                        <Text type="secondary">{item.description}</Text>
                      </Paragraph>

                      {item.operation_steps?.length > 0 && (
                        <div style={{ marginBottom: 8 }}>
                          <Text strong>操作步骤：</Text>
                          <ol style={{ margin: '4px 0', paddingLeft: 24 }}>
                            {item.operation_steps.map((step, i) => (
                              <li key={i} style={{ marginBottom: 2 }}>
                                <Text>{step}</Text>
                              </li>
                            ))}
                          </ol>
                        </div>
                      )}

                      <div>
                        <Text strong>预期结果：</Text>
                        <Tag color="green">{item.expected_result}</Tag>
                      </div>

                      {item.exception_description && (
                        <div style={{ marginTop: 8 }}>
                          <Text type="warning">
                            <ExclamationCircleOutlined /> 异常说明：{item.exception_description}
                          </Text>
                        </div>
                      )}
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Card title="最短复现步骤" style={{ marginTop: 16 }} type="inner">
        <Alert
          message="快速验证步骤（最短路径）"
          description="如果只想快速验证核心功能，按以下5步操作即可"
          type="success"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <ol style={{ margin: 0, paddingLeft: 24 }}>
          <li style={{ marginBottom: 8 }}>
            <Text strong>登录管理员账号</Text>（admin / admin123）
          </li>
          <li style={{ marginBottom: 8 }}>
            <Text strong>进入演练中心</Text>，选择"交接单完整流程演练"，点击"开始演练"
          </li>
          <li style={{ marginBottom: 8 }}>
            <Text strong>依次执行前7步</Text>：导入数据 → 提交 → 审批 → 创建交接单 → 检查冲突 → 签收 → 作废
          </li>
          <li style={{ marginBottom: 8 }}>
            <Text strong>执行异常分支验证</Text>：重复导入拦截、作废单拦截、越权验证
          </li>
          <li style={{ marginBottom: 8 }}>
            <Text strong>查看日志和导出验收记录</Text>，确认所有操作留痕
          </li>
        </ol>
      </Card>
    </div>
  )
}
