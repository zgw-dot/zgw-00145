import React, { useState, useEffect } from 'react'
import {
  Card, Form, Input, InputNumber, Select, Switch, Button, Space,
  Typography, Row, Col, Tag, App as AntApp, Divider, List,
} from 'antd'
import {
  SettingOutlined, SaveOutlined, ReloadOutlined,
  PlusOutlined, MinusCircleOutlined,
} from '@ant-design/icons'
import api from '../utils/api.js'

const { Title, Paragraph, Text } = Typography
const { TextArea } = Input

export default function ConfigPage({ user }) {
  const { message } = AntApp.useApp()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const isAdmin = user?.role === 'admin'

  useEffect(() => { loadConfig() }, [])

  const loadConfig = async () => {
    setLoading(true)
    try {
      const res = await api.get('/config')
      const c = res.data
      form.setFieldsValue({
        discount_floor: parseFloat(c.discount_floor ?? 0.5),
        store_whitelist: c.store_whitelist ?? [],
        publish_window: c.publish_window ?? { enabled: true, start_hour: 9, end_hour: 18, weekdays_only: true },
        template_fields: JSON.stringify(c.template_fields ?? [], null, 2),
      })
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async (values) => {
    setSaving(true)
    try {
      let templateFields
      try {
        templateFields = JSON.parse(values.template_fields || '[]')
        if (!Array.isArray(templateFields)) throw new Error()
      } catch {
        message.error('模板字段必须是合法的 JSON 数组')
        setSaving(false)
        return
      }

      await api.put('/config', {
        discount_floor: values.discount_floor,
        store_whitelist: values.store_whitelist,
        publish_window: values.publish_window,
        template_fields: templateFields,
      })
      message.success('配置已保存')
      loadConfig()
    } catch (err) {
      message.error(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <div className="action-bar">
        <Title level={4} style={{ margin: 0 }}>
          <SettingOutlined /> 系统配置
        </Title>
        {!isAdmin && <Tag color="warning">仅管理员可修改配置</Tag>}
      </div>

      {!isAdmin ? (
        <Card>
          <Paragraph type="secondary" style={{ textAlign: 'center', padding: '40px 0' }}>
            当前账号无配置管理权限，请使用管理员账号登录
          </Paragraph>
        </Card>
      ) : (
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSave}
          disabled={loading}
        >
          <Row gutter={[24, 24]}>
            <Col xs={24} lg={12}>
              <Card title="价格规则" size="small">
                <Form.Item
                  name="discount_floor"
                  label={
                    <Space>
                      折扣下限
                      <Tooltip title="低于该折扣比例的价签将被校验拦截">
                        <Tag color="blue" style={{ margin: 0 }}>?</Tag>
                      </Tooltip>
                    </Space>
                  }
                  rules={[{ required: true, message: '请输入折扣下限' }]}
                  tooltip="促销价 / 原价 的最低比例，低于此值会校验失败"
                >
                  <InputNumber
                    style={{ width: '100%' }}
                    min={0}
                    max={1}
                    step={0.05}
                    precision={2}
                    addonAfter={<span>（1.0 = 不打折，0.5 = 最低5折）</span>}
                    placeholder="例如 0.5 表示最低5折"
                  />
                </Form.Item>
              </Card>

              <Card title="发布窗口" size="small" style={{ marginTop: 16 }}>
                <Form.Item
                  name={['publish_window', 'enabled']}
                  label="启用发布时间窗口"
                  valuePropName="checked"
                  tooltip="关闭后任何时间都可发布"
                >
                  <Switch />
                </Form.Item>
                <Row gutter={16}>
                  <Col xs={12}>
                    <Form.Item
                      name={['publish_window', 'start_hour']}
                      label="开始时间（小时）"
                      rules={[{ required: true, message: '请输入开始时间' }]}
                    >
                      <InputNumber min={0} max={23} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col xs={12}>
                    <Form.Item
                      name={['publish_window', 'end_hour']}
                      label="结束时间（小时）"
                      rules={[{ required: true, message: '请输入结束时间' }]}
                    >
                      <InputNumber min={0} max={23} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item
                  name={['publish_window', 'weekdays_only']}
                  label="仅工作日允许发布"
                  valuePropName="checked"
                >
                  <Switch />
                </Form.Item>
              </Card>
            </Col>

            <Col xs={24} lg={12}>
              <Card title="门店白名单" size="small" extra={<Tag color="green">仅白名单内的门店允许导入价签</Tag>}>
                <Form.List
                  name="store_whitelist"
                  rules={[
                    {
                      validator: async (_, v) => {
                        if (!v || v.length === 0) return Promise.reject(new Error('至少需要配置一个门店'))
                      },
                    },
                  ]}
                >
                  {(fields, { add, remove }, { errors }) => (
                    <>
                      <div
                        style={{
                          border: '1px solid #f0f0f0',
                          padding: 12,
                          borderRadius: 6,
                          maxHeight: 280,
                          overflowY: 'auto',
                        }}
                      >
                        {fields.length === 0 ? (
                          <Paragraph type="secondary" style={{ textAlign: 'center', margin: '20px 0' }}>
                            暂无门店，点击下方按钮添加
                          </Paragraph>
                        ) : (
                          fields.map(({ key, name, ...restField }) => (
                            <Space key={key} style={{ display: 'flex', marginBottom: 8, width: '100%' }} align="baseline">
                              <Tag color="blue">门店</Tag>
                              <Form.Item
                                {...restField}
                                name={name}
                                style={{ flex: 1, marginBottom: 0 }}
                                rules={[{ required: true, message: '门店名不能为空' }]}
                              >
                                <Input placeholder="例如：北京朝阳店" maxLength={50} />
                              </Form.Item>
                              <MinusCircleOutlined onClick={() => remove(name)} style={{ color: '#ff4d4f' }} />
                            </Space>
                          ))
                        )}
                      </div>
                      <Form.Item style={{ marginTop: 12, marginBottom: 0 }}>
                        <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />}>
                          添加门店
                        </Button>
                      </Form.Item>
                      <Form.ErrorList errors={errors} />
                    </>
                  )}
                </Form.List>
              </Card>

              <Card
                title="模板字段定义"
                size="small"
                style={{ marginTop: 16 }}
                extra={
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    JSON 数组格式
                  </Text>
                }
              >
                <Form.Item
                  name="template_fields"
                  rules={[{ required: true, message: '请输入模板字段配置' }]}
                  style={{ marginBottom: 0 }}
                >
                  <TextArea
                    rows={8}
                    placeholder='[{"key":"sku","label":"SKU编码","required":true}]'
                    style={{ fontFamily: 'monospace', fontSize: 12 }}
                  />
                </Form.Item>
              </Card>
            </Col>
          </Row>

          <Divider />

          <div style={{ textAlign: 'center' }}>
            <Space size={16}>
              <Button icon={<ReloadOutlined />} onClick={loadConfig} size="large">
                重置
              </Button>
              <Button type="primary" icon={<SaveOutlined />} htmlType="submit" size="large" loading={saving}>
                保存配置
              </Button>
            </Space>
          </div>
        </Form>
      )}
    </div>
  )
}
