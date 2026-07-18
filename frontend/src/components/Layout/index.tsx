import { useState } from 'react'
import { Layout, Menu, Typography, Button, Dropdown } from 'antd'
import {
  UploadOutlined,
  DatabaseOutlined,
  ClearOutlined,
  ExportOutlined,
  ProfileOutlined,
  AppstoreAddOutlined,
  UserOutlined,
  LogoutOutlined,
  FundOutlined,
  QuestionCircleOutlined,
  LinkOutlined,
  FilterOutlined,
  HistoryOutlined,
  TagsOutlined,
  FunnelPlotOutlined,
  ShopOutlined,
  LineChartOutlined,
  FolderOutlined,
  ToolOutlined,
  ContainerOutlined,
  CheckSquareOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { hasPermission, type PermissionKey } from '../../auth/permissions'

const { Sider, Header, Content } = Layout
const { Title, Text } = Typography

type AppMenuItem = {
  key: string
  icon?: React.ReactNode
  label: React.ReactNode
  permission?: PermissionKey
  adminOnly?: boolean
  children?: AppMenuItem[]
}

const menuItems: AppMenuItem[] = [
  {
    key: 'data-management',
    icon: <FolderOutlined />,
    label: '数据管理',
    permission: 'data_management',
    children: [
      { key: '/upload',     icon: <UploadOutlined />,     label: '数据上传' },
      { key: '/dispatch',   icon: <FunnelPlotOutlined />, label: '数据分发' },
      { key: '/rawdata',    icon: <DatabaseOutlined />,   label: '原始数据' },
      { key: '/categories', icon: <TagsOutlined />,       label: '品类管理' },
    ],
  },
  {
    key: 'processing-workbench',
    icon: <ToolOutlined />,
    label: '处理工作台',
    permission: 'processing_workbench',
    children: [
      { key: '/metadata',     icon: <ProfileOutlined />,     label: '产品字段定义' },
      { key: '/models',       icon: <AppstoreAddOutlined />, label: '产品属性管理' },
      { key: '/brands',       icon: <ShopOutlined />,        label: '品牌管理' },
      { key: '/url-mappings', icon: <LinkOutlined />,        label: '映射管理' },
      { key: '/historical',       icon: <HistoryOutlined />,     label: '历史库' },
      { key: '/clean',            icon: <ClearOutlined />,       label: '清洗任务' },
      { key: '/match-results',    icon: <CheckSquareOutlined />, label: '匹配结果' },
      { key: '/rules',         icon: <FilterOutlined />,      label: '规则管理' },
    ],
  },
  {
    key: 'product-management',
    icon: <ContainerOutlined />,
    label: '成品管理',
    permission: 'product_management',
    children: [
      { key: '/dashboard', icon: <LineChartOutlined />, label: '数据看板' },
      { key: '/export',    icon: <ExportOutlined />,    label: '数据导出' },
      { key: '/workbench', icon: <FundOutlined />,      label: '查询工作台' },
    ],
  },
  { key: '/manual', icon: <QuestionCircleOutlined />, label: '使用手册' },
  { key: '/users', icon: <TeamOutlined />, label: '用户管理', adminOnly: true },
]

function filterMenuItems(items: AppMenuItem[], user: ReturnType<typeof useAuth>['user']): AppMenuItem[] {
  return items
    .filter(item => {
      if (item.adminOnly) return user?.is_admin === 1
      if (item.permission) return hasPermission(user, item.permission)
      return true
    })
    .map(item => {
      if (!item.children) return item
      return { ...item, children: filterMenuItems(item.children, user) }
    })
}

const pageTitles = new Map<string, string>()
menuItems.forEach(item => {
  if (item && 'children' in item && item.children) {
    item.children.forEach(child => {
      if (child && 'key' in child && 'label' in child) {
        pageTitles.set(String(child.key), String(child.label))
      }
    })
  } else if (item && 'key' in item && 'label' in item) {
    pageTitles.set(String(item.key), String(item.label))
  }
})
pageTitles.set('/match', '清洗任务详情')
pageTitles.set('/match-results', '匹配结果')

interface Props {
  children: React.ReactNode
}

export default function AppLayout({ children }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const { user, logout } = useAuth()
  const filteredMenuItems = filterMenuItems(menuItems, user)
  const username = user?.name || user?.username || '用户'

  const handleLogout = () => {
    logout()
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
          items={filteredMenuItems}
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
            {pageTitles.get(location.pathname) ?? '洛图数据处理平台'}
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
