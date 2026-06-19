import React, { useState, useEffect } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Layout, Menu, Dropdown, Avatar, Space, Badge, App as AntApp } from 'antd'
import {
  DashboardOutlined,
  ImportOutlined,
  UnorderedListOutlined,
  AuditOutlined,
  PrinterOutlined,
  HistoryOutlined,
  SettingOutlined,
  UserOutlined,
  LogoutOutlined,
  StopOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import ImportPage from './pages/ImportPage.jsx'
import ImportBatchDetail from './pages/ImportBatchDetail.jsx'
import LabelList from './pages/LabelList.jsx'
import LabelDetail from './pages/LabelDetail.jsx'
import ApprovalPage from './pages/ApprovalPage.jsx'
import PrintQueue from './pages/PrintQueue.jsx'
import RollbackHistoryPage from './pages/RollbackHistoryPage.jsx'
import RevocationLogPage from './pages/RevocationLogPage.jsx'
import RevocationApprovalPage from './pages/RevocationApprovalPage.jsx'
import ConfigPage from './pages/ConfigPage.jsx'
import HandoverSheetList from './pages/HandoverSheetList.jsx'
import HandoverSheetDetail from './pages/HandoverSheetDetail.jsx'
import HandoverLogPage from './pages/HandoverLogPage.jsx'
import api from './utils/api.js'

const { Header, Sider, Content } = Layout

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '工作台' },
  { key: '/import', icon: <ImportOutlined />, label: '导入批次' },
  { key: '/labels', icon: <UnorderedListOutlined />, label: '价签管理' },
  { key: '/approval', icon: <AuditOutlined />, label: '价签审批' },
  { key: '/revocation-approval', icon: <StopOutlined />, label: '撤销审批', roles: ['admin'] },
  { key: '/print-queue', icon: <PrinterOutlined />, label: '打印清单' },
  { key: '/handover-sheets', icon: <SwapOutlined />, label: '交接单管理' },
  { key: '/handover-logs', icon: <SwapOutlined />, label: '交接单日志' },
  { key: '/rollback-history', icon: <HistoryOutlined />, label: '回滚历史' },
  { key: '/revocation-logs', icon: <StopOutlined />, label: '撤销日志' },
  { key: '/config', icon: <SettingOutlined />, label: '系统配置', roles: ['admin'] },
]

function AppContent() {
  const location = useLocation()
  const navigate = useNavigate()
  const { message } = AntApp.useApp()
  const [user, setUser] = useState(null)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    const saved = localStorage.getItem('user')
    if (saved) {
      setUser(JSON.parse(saved))
    } else {
      api.get('/auth/me')
        .then((res) => {
          setUser(res.data)
          localStorage.setItem('user', JSON.stringify(res.data))
        })
        .catch(() => {
          if (location.pathname !== '/login') {
            navigate('/login')
          }
        })
    }
  }, [])

  const handleLogout = () => {
    api.post('/auth/logout')
      .then(() => {
        localStorage.removeItem('user')
        setUser(null)
        navigate('/login')
        message.success('已退出登录')
      })
      .catch((err) => message.error(err.message))
  }

  const visibleMenus = menuItems.filter((m) => {
    if (!m.roles) return true
    return user && m.roles.includes(user.role)
  })

  const roleLabel = { admin: '管理员', operator: '运营', clerk: '店员' }[user?.role] || user?.role

  const userMenu = {
    items: [
      { key: 'role', label: `角色：${roleLabel}`, disabled: true },
      { type: 'divider' },
      { key: 'logout', label: '退出登录', icon: <LogoutOutlined />, onClick: handleLogout },
    ],
  }

  if (!user && location.pathname !== '/login') {
    return <div style={{ padding: 40, textAlign: 'center' }}>加载中...</div>
  }

  if (location.pathname === '/login') {
    return <Login onLogin={(u) => { setUser(u); localStorage.setItem('user', JSON.stringify(u)); navigate('/dashboard') }} />
  }

  return (
    <Layout className="layout-container">
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark">
        <div className="logo">{collapsed ? '价签' : '价签发布工作台'}</div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={visibleMenus}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', boxShadow: '0 1px 4px rgba(0,0,0,0.08)' }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#1f1f1f' }}>
            {visibleMenus.find(m => m.key === location.pathname)?.label || '门店价签发布工作台'}
          </div>
          <Dropdown menu={userMenu} placement="bottomRight">
            <Space style={{ cursor: 'pointer' }}>
              <Avatar icon={<UserOutlined />} style={{ backgroundColor: '#1677ff' }} />
              <span style={{ color: '#1f1f1f' }}>{user?.username}</span>
              <Badge color={user?.role === 'admin' ? 'red' : user?.role === 'operator' ? 'blue' : 'green'} />
            </Space>
          </Dropdown>
        </Header>
        <Content>
          <div className="page-content">
            <Routes location={location}>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard user={user} />} />
              <Route path="/import" element={<ImportPage user={user} />} />
              <Route path="/import/:id" element={<ImportBatchDetail />} />
              <Route path="/labels" element={<LabelList user={user} />} />
              <Route path="/labels/:id" element={<LabelDetail user={user} />} />
              <Route path="/approval" element={<ApprovalPage user={user} />} />
              <Route path="/revocation-approval" element={<RevocationApprovalPage user={user} />} />
              <Route path="/print-queue" element={<PrintQueue user={user} />} />
              <Route path="/rollback-history" element={<RollbackHistoryPage />} />
              <Route path="/revocation-logs" element={<RevocationLogPage />} />
              <Route path="/handover-sheets" element={<HandoverSheetList user={user} />} />
              <Route path="/handover-sheets/:id" element={<HandoverSheetDetail user={user} />} />
              <Route path="/handover-logs" element={<HandoverLogPage />} />
              <Route path="/config" element={<ConfigPage user={user} />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </div>
        </Content>
      </Layout>
    </Layout>
  )
}

function App() {
  return <AppContent />
}

export default App
