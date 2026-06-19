import React, { useState, useEffect } from 'react'
import { Row, Col, Card, Statistic, Typography, Tag, Button, Space, App as AntApp, List } from 'antd'
import {
  FileDoneOutlined,
  FileSyncOutlined,
  CheckCircleOutlined,
  UndoOutlined,
  PrinterOutlined,
  HistoryOutlined,
  ClockCircleOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../utils/api.js'

const { Title, Paragraph } = Typography

export default function Dashboard() {
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [stats, setStats] = useState(null)
  const [recentBatches, setRecentBatches] = useState([])

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      const [sRes, bRes] = await Promise.all([
        api.get('/stats/overview'),
        api.get('/import/batches?page=1&size=5'),
      ])
      setStats(sRes.data)
      setRecentBatches(bRes.data.list)
    } catch (err) {
      message.error(err.message)
    }
  }

  const StatCard = ({ title, value, icon, color, path }) => (
    <Card
      className="stat-card"
      hoverable
      onClick={path ? () => navigate(path) : undefined}
      styles={{ body: { padding: '24px 16px' } }}
    >
      <Space size={16} align="center">
        <div
          style={{
            width: 56, height: 56, borderRadius: 12,
            background: `${color}15`, color,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 28,
          }}
        >
          {icon}
        </div>
        <div style={{ textAlign: 'left', flex: 1 }}>
          <div style={{ fontSize: 13, color: '#8c8c8c', marginBottom: 4 }}>{title}</div>
          <div style={{ fontSize: 28, fontWeight: 600, color: '#1f1f1f' }}>{value ?? '-'}</div>
        </div>
        {path && <ArrowRightOutlined style={{ color: '#bfbfbf' }} />}
      </Space>
    </Card>
  )

  return (
    <div>
      <Title level={4} style={{ marginTop: 0 }}>数据概览</Title>
      {stats && (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
            <Col xs={24} sm={12} md={8} lg={6}>
              <StatCard title="价签总数" value={stats.total} color="#1677ff" icon={<FileDoneOutlined />} path="/labels" />
            </Col>
            <Col xs={24} sm={12} md={8} lg={6}>
              <StatCard title="待提交(草稿)" value={stats.draft} color="#faad14" icon={<FileSyncOutlined />} path="/labels?status=draft" />
            </Col>
            <Col xs={24} sm={12} md={8} lg={6}>
              <StatCard title="待审批" value={stats.pending_approval} color="#722ed1" icon={<ClockCircleOutlined />} path="/approval" />
            </Col>
            <Col xs={24} sm={12} md={8} lg={6}>
              <StatCard title="已发布" value={stats.published} color="#52c41a" icon={<CheckCircleOutlined />} path="/labels?status=published" />
            </Col>
            <Col xs={24} sm={12} md={8} lg={6}>
              <StatCard title="已回滚" value={stats.rolled_back} color="#ff4d4f" icon={<UndoOutlined />} path="/labels?status=rolled_back" />
            </Col>
            <Col xs={24} sm={12} md={8} lg={6}>
              <StatCard title="待打印" value={stats.pending_print} color="#13c2c2" icon={<PrinterOutlined />} path="/print-queue" />
            </Col>
            <Col xs={24} sm={12} md={8} lg={6}>
              <StatCard title="回滚次数" value={stats.rollback_count} color="#eb2f96" icon={<HistoryOutlined />} path="/rollback-history" />
            </Col>
            <Col xs={24} sm={12} md={8} lg={6}>
              <Card
                className="stat-card"
                styles={{ body: { padding: '24px 16px' } }}
                style={{ cursor: 'default' }}
              >
                <Space size={16} align="center">
                  <div
                    style={{
                      width: 56, height: 56, borderRadius: 12,
                      background: `${stats.in_publish_window ? '#52c41a' : '#ff4d4f'}15`,
                      color: stats.in_publish_window ? '#52c41a' : '#ff4d4f',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 28,
                    }}
                  >
                    <ClockCircleOutlined />
                  </div>
                  <div style={{ textAlign: 'left', flex: 1 }}>
                    <div style={{ fontSize: 13, color: '#8c8c8c', marginBottom: 4 }}>发布窗口</div>
                    <Tag color={stats.in_publish_window ? 'success' : 'error'} style={{ margin: 0, fontSize: 14, padding: '2px 12px' }}>
                      {stats.in_publish_window ? '当前可发布' : '非发布时段'}
                    </Tag>
                  </div>
                </Space>
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={16}>
              <Card
                title="最近导入批次"
                extra={<Button type="link" onClick={() => navigate('/import')}>查看全部</Button>}
              >
                {recentBatches.length === 0 ? (
                  <Paragraph type="secondary" style={{ textAlign: 'center', padding: '40px 0' }}>
                    暂无导入记录，去 <a onClick={() => navigate('/import')}>导入价签</a>
                  </Paragraph>
                ) : (
                  <List
                    dataSource={recentBatches}
                    renderItem={(item) => (
                      <List.Item
                        actions={[
                          <Button type="link" size="small" onClick={() => navigate(`/import/${item.id}`)}>
                            查看校验详情
                          </Button>,
                        ]}
                      >
                        <List.Item.Meta
                          title={
                            <Space>
                              <span style={{ fontWeight: 500 }}>{item.filename}</span>
                              <Tag color="blue">{item.batch_no}</Tag>
                            </Space>
                          }
                          description={
                            <Space size={16} style={{ fontSize: 12, color: '#8c8c8c' }}>
                              <span>共 {item.total_rows} 行</span>
                              <Tag color="success">通过 {item.valid_rows}</Tag>
                              <Tag color="error">失败 {item.invalid_rows}</Tag>
                              <span>{item.created_at?.replace('T', ' ').slice(0, 19)}</span>
                            </Space>
                          }
                        />
                      </List.Item>
                    )}
                  />
                )}
              </Card>
            </Col>
            <Col xs={24} lg={8}>
              <Card title="快捷操作">
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  <Button type="primary" size="large" block icon={<FileSyncOutlined />} onClick={() => navigate('/import')}>
                    导入新价签 CSV
                  </Button>
                  <Button size="large" block icon={<CheckCircleOutlined />} onClick={() => navigate('/approval')}>
                    处理待审批价签
                  </Button>
                  <Button size="large" block icon={<PrinterOutlined />} onClick={() => navigate('/print-queue')}>
                    查看待打印清单
                  </Button>
                  <Button size="large" block icon={<HistoryOutlined />} onClick={() => navigate('/rollback-history')}>
                    查看回滚历史
                  </Button>
                </Space>
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  )
}
