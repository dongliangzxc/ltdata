import { useState } from 'react'
import { Layout, Menu, Typography, Button, Dropdown } from 'antd'
import {
  UploadOutlined,
  DatabaseOutlined,
  ClearOutlined,
  ExportOutlined,
  ProfileOutlined,
  AppstoreAddOutlined,
  AimOutlined,
  UserOutlined,
  LogoutOutlined,
  FundOutlined,
  QuestionCircleOutlined,
  LinkOutlined,
  FilterOutlined,
  HistoryOutlined,
  TagsOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'

const { Sider, Header, Content } = Layout
const { Title, Text } = Typography

const menuItems = [
  { key: '/upload',     icon: <UploadOutlined />,        label: '数据上传' },
  { key: '/rawdata',    icon: <DatabaseOutlined />,      label: '原始数据' },
  { key: '/categories', icon: <TagsOutlined />,       label: '品类管理' },
  { key: '/metadata',   icon: <ProfileOutlined />,       label: '元数据管理' },
  { key: '/models',     icon: <AppstoreAddOutlined />,   label: '型号管理' },
  { key: '/url-mappings', icon: <LinkOutlined />,        label: 'URL映射管理' },
  { key: '/historical',   icon: <HistoryOutlined />,     label: '历史库' },
  { key: '/clean',      icon: <ClearOutlined />,         label: '数据清洗' },
  { key: '/rules',      icon: <FilterOutlined />,        label: '规则管理' },
  { key: '/match',      icon: <AimOutlined />,           label: '匹配确认' },
  { key: '/workbench',  icon: <FundOutlined />,            label: '查询工作台' },
  { key: '/export',     icon: <ExportOutlined />,          label: '数据导出' },
  { key: '/manual',     icon: <QuestionCircleOutlined />,  label: '使用手册' },
]

interface Props {
  children: React.ReactNode
}

export default function AppLayout({ children }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const username = localStorage.getItem('username') ?? '用户'

  const handleLogout = () => {
    localStorage.removeItem('token')
    localStorage.removeItem('username')
    navigate('/login', { replace: true })
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="dark"
        width={200}
      >
        <div style={{ padding: '16px 16px 8px', textAlign: 'center' }}>
          <Title level={5} style={{ color: '#fff', margin: 0, whiteSpace: 'nowrap', overflow: 'hidden' }}>
            {collapsed ? '洛图' : '洛图数据平台'}
          </Title>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{
          background: '#fff',
          padding: '0 24px',
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <Title level={4} style={{ margin: 0, color: '#1677ff' }}>
            {menuItems.find(m => m.key === location.pathname)?.label ?? '洛图数据处理平台'}
          </Title>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'logout',
                  icon: <LogoutOutlined />,
                  label: '退出登录',
                  danger: true,
                  onClick: handleLogout,
                },
              ],
            }}
            placement="bottomRight"
          >
            <Button type="text" icon={<UserOutlined />} style={{ color: '#595959' }}>
              <Text style={{ marginLeft: 4 }}>{username}</Text>
            </Button>
          </Dropdown>
        </Header>
        <Content style={{ margin: 24, minHeight: 280 }}>
          {children}
        </Content>
      </Layout>
    </Layout>
  )
}
