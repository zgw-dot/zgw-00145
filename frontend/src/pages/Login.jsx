import React, { useState } from 'react'
import { Form, Input, Button, Card, App as AntApp, Typography } from 'antd'
import { UserOutlined, LockOutlined, LoginOutlined } from '@ant-design/icons'
import api from '../utils/api.js'

const { Paragraph, Text } = Typography

export default function Login({ onLogin }) {
  const [loading, setLoading] = useState(false)
  const { message } = AntApp.useApp()

  const handleSubmit = async (values) => {
    setLoading(true)
    try {
      const res = await api.post('/auth/login', values)
      message.success('登录成功')
      onLogin(res.data)
    } catch (err) {
      message.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-container">
      <Card className="login-box" variant="borderless">
        <div className="login-title">门店价签发布工作台</div>
        <div className="login-subtitle">Store Price Label Workbench</div>
        <Form
          name="login"
          onFinish={handleSubmit}
          autoComplete="off"
          layout="vertical"
        >
          <Form.Item
            name="username"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input
              size="large"
              prefix={<UserOutlined />}
              placeholder="用户名：admin / operator / clerk"
              allowClear
            />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password
              size="large"
              prefix={<LockOutlined />}
              placeholder="密码：对应账号+123"
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 16 }}>
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              loading={loading}
              icon={<LoginOutlined />}
            >
              登录
            </Button>
          </Form.Item>
        </Form>
        <div style={{ padding: '12px 0', borderTop: '1px solid #f0f0f0' }}>
          <Paragraph style={{ marginBottom: 4 }}>
            <Text strong>测试账号：</Text>
          </Paragraph>
          <Paragraph style={{ marginBottom: 2, fontSize: 13, color: '#8c8c8c' }}>
            管理员 admin / admin123（全权限，可配置系统）
          </Paragraph>
          <Paragraph style={{ marginBottom: 2, fontSize: 13, color: '#8c8c8c' }}>
            运营 operator / operator123（导入、提交、发布）
          </Paragraph>
          <Paragraph style={{ fontSize: 13, color: '#8c8c8c' }}>
            店员 clerk / clerk123（查看、打印）
          </Paragraph>
        </div>
      </Card>
    </div>
  )
}
