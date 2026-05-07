import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Tabs, Card, Table, Button, Input, Select, Space, Popconfirm,
  Upload, Modal, Form, InputNumber, Tag, message, Alert,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, UploadOutlined,
  CheckCircleOutlined, StopOutlined,
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  listNoiseWords, createNoiseWord, toggleNoiseWord, deleteNoiseWord,
  listBrandAliases, createBrandAlias, importBrandAliases, deleteBrandAlias,
  listMatchRules, createMatchRule, updateMatchRule, deleteMatchRule,
  listFilteredItems, recoverFilteredItem, recoverFilteredItemsBatch,
  listCleanJobs, listModels,
} from '../../services/api'

// ══════════════════════════════════════════════
// Tab 1: 干扰词库
// ══════════════════════════════════════════════
function NoiseWordTab() {
  const [keyword, setKeyword] = useState('')
  const [matchField, setMatchField] = useState('item_name')
  const [adding, setAdding] = useState(false)
  const { data, loading, refresh } = useRequest(() => listNoiseWords().then(r => r.data))

  const handleAdd = async () => {
    if (!keyword.trim()) { message.warning('请输入关键词'); return }
    setAdding(true)
    try {
      await createNoiseWord({ keyword: keyword.trim(), match_field: matchField })
      message.success('添加成功')
      setKeyword('')
      refresh()
    } finally { setAdding(false) }
  }

  const columns = [
    { title: '关键词', dataIndex: 'keyword', ellipsis: true },
    { title: '匹配字段', dataIndex: 'match_field', width: 120,
      render: (v: string) => ({ item_name: '商品名称', shop_name: '店铺名称', brand_raw: '原始品牌' }[v] ?? v) },
    { title: '状态', dataIndex: 'is_active', width: 80,
      render: (v: number) => v ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag> },
    {
      title: '操作', width: 120,
      render: (_: unknown, row: { id: number; is_active: number }) => (
        <Space size={4}>
          <Button size="small" icon={row.is_active ? <StopOutlined /> : <CheckCircleOutlined />}
            onClick={async () => { await toggleNoiseWord(row.id); refresh() }}>
            {row.is_active ? '禁用' : '启用'}
          </Button>
          <Popconfirm title="确认删除？" onConfirm={async () => { await deleteNoiseWord(row.id); refresh() }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="info" showIcon message="命中干扰词的商品将被移入「干扰项存档」，不进入清洗数据。支持禁用（不删除），方便排查误过滤。" />
      <Space wrap>
        <Input placeholder="输入干扰关键词" value={keyword} onChange={e => setKeyword(e.target.value)}
          onPressEnter={handleAdd} style={{ width: 220 }} />
        <Select value={matchField} onChange={setMatchField} style={{ width: 130 }}
          options={[
            { value: 'item_name', label: '商品名称' },
            { value: 'shop_name', label: '店铺名称' },
            { value: 'brand_raw', label: '原始品牌' },
          ]} />
        <Button type="primary" icon={<PlusOutlined />} loading={adding} onClick={handleAdd}>添加</Button>
      </Space>
      <Table dataSource={data ?? []} columns={columns} rowKey="id" size="small" loading={loading}
        pagination={{ pageSize: 20, showTotal: (t: number) => `共 ${t} 条` }} />
    </Space>
  )
}

// ══════════════════════════════════════════════
// Tab 2: 品牌写法库
// ══════════════════════════════════════════════
function BrandAliasTab() {
  const [aliasName, setAliasName] = useState('')
  const [brandCode, setBrandCode] = useState('')
  const [adding, setAdding] = useState(false)
  const { data, loading, refresh } = useRequest(() => listBrandAliases().then(r => r.data))

  const handleAdd = async () => {
    if (!aliasName.trim() || !brandCode.trim()) { message.warning('请填写写法和品牌码'); return }
    setAdding(true)
    try {
      await createBrandAlias({ alias_name: aliasName.trim(), brand_code: brandCode.trim() })
      message.success('添加成功')
      setAliasName(''); setBrandCode('')
      refresh()
    } finally { setAdding(false) }
  }

  const handleImport = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await importBrandAliases(fd)
      message.success(`导入完成：${res.data.imported} 条，跳过 ${res.data.skipped} 条`)
      refresh()
    } catch { /* handled by interceptor */ }
    return false
  }

  const columns = [
    { title: '原始写法', dataIndex: 'alias_name' },
    { title: '标准品牌码', dataIndex: 'brand_code', width: 140 },
    {
      title: '操作', width: 80,
      render: (_: unknown, row: { id: number }) => (
        <Popconfirm title="确认删除？" onConfirm={async () => { await deleteBrandAlias(row.id); refresh() }}>
          <Button size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="info" showIcon message="清洗时 brand_raw 命中写法后自动替换为标准品牌码，提升后续匹配准确率。" />
      <Space wrap>
        <Input placeholder="原始写法（如：索尼）" value={aliasName} onChange={e => setAliasName(e.target.value)}
          style={{ width: 180 }} />
        <Input placeholder="标准品牌码（如：SONY）" value={brandCode} onChange={e => setBrandCode(e.target.value)}
          style={{ width: 180 }} onPressEnter={handleAdd} />
        <Button type="primary" icon={<PlusOutlined />} loading={adding} onClick={handleAdd}>添加</Button>
        <Upload beforeUpload={handleImport} showUploadList={false} accept=".xlsx,.xls">
          <Button icon={<UploadOutlined />}>Excel 批量导入</Button>
        </Upload>
      </Space>
      <Table dataSource={data ?? []} columns={columns} rowKey="id" size="small" loading={loading}
        pagination={{ pageSize: 20, showTotal: (t: number) => `共 ${t} 条` }} />
    </Space>
  )
}

// ══════════════════════════════════════════════
// Tab 3: 匹配规则
// ══════════════════════════════════════════════
function MatchRuleTab() {
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const { data, loading, refresh } = useRequest(() => listMatchRules().then(r => r.data))
  const { data: modelsData } = useRequest(() => listModels({ page: 1, page_size: 500 }).then(r => r.data))
  const modelOptions = (modelsData?.items ?? []).map((m: { id: number; brand_code: string; model_code: string; model_name: string | null }) => ({
    value: m.id,
    label: `[${m.brand_code}] ${m.model_code}${m.model_name ? ' ' + m.model_name : ''}`,
  }))

  const openCreate = () => { setEditingId(null); form.resetFields(); setModalOpen(true) }
  const openEdit = (row: { id: number; keyword: string; match_type: string; model_id: number; priority: number }) => {
    setEditingId(row.id)
    form.setFieldsValue({ keyword: row.keyword, match_type: row.match_type, model_id: row.model_id, priority: row.priority })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const vals = await form.validateFields()
    if (editingId) {
      await updateMatchRule(editingId, vals)
      message.success('更新成功')
    } else {
      await createMatchRule(vals)
      message.success('添加成功')
    }
    setModalOpen(false)
    refresh()
  }

  const columns = [
    { title: '优先级', dataIndex: 'priority', width: 80, sorter: (a: { priority: number }, b: { priority: number }) => a.priority - b.priority },
    { title: '关键词', dataIndex: 'keyword', ellipsis: true },
    { title: '匹配方式', dataIndex: 'match_type', width: 100,
      render: (v: string) => <Tag color={v === 'exact' ? 'blue' : 'cyan'}>{v === 'exact' ? '精准' : '包含'}</Tag> },
    { title: '品牌码', dataIndex: 'brand_code', width: 100 },
    { title: '型号码', dataIndex: 'model_code', width: 120 },
    { title: '状态', dataIndex: 'is_active', width: 80,
      render: (v: number) => v ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag> },
    {
      title: '操作', width: 130,
      render: (_: unknown, row: { id: number; keyword: string; match_type: string; model_id: number; priority: number; is_active: number }) => (
        <Space size={4}>
          <Button size="small" onClick={() => openEdit(row)}>编辑</Button>
          <Button size="small" onClick={async () => {
            await updateMatchRule(row.id, { is_active: row.is_active ? 0 : 1 }); refresh()
          }}>{row.is_active ? '禁用' : '启用'}</Button>
          <Popconfirm title="确认删除？" onConfirm={async () => { await deleteMatchRule(row.id); refresh() }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Alert type="info" showIcon
          message="S0.5 层：优先级数字越小越先执行。命中后直接出结果，跳过 S1-S4 算法。建议关键词长度 ≥ 5 字符（使用「精准」模式除外）。" />
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增规则</Button>
        <Table dataSource={data ?? []} columns={columns} rowKey="id" size="small" loading={loading}
          pagination={{ pageSize: 20, showTotal: (t: number) => `共 ${t} 条` }} />
      </Space>

      <Modal title={editingId ? '编辑规则' : '新增规则'} open={modalOpen}
        onOk={handleSubmit} onCancel={() => setModalOpen(false)} okText="保存" cancelText="取消">
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item label="关键词" name="keyword" rules={[{ required: true, message: '请输入关键词' }]}>
            <Input placeholder="在商品名称中匹配的关键词" />
          </Form.Item>
          <Form.Item label="匹配方式" name="match_type" initialValue="contains">
            <Select options={[{ value: 'contains', label: '包含（商品名称包含该词）' }, { value: 'exact', label: '精准（商品名称完全等于该词）' }]} />
          </Form.Item>
          <Form.Item label="目标型号" name="model_id" rules={[{ required: true, message: '请选择型号' }]}>
            <Select showSearch placeholder="搜索品牌/型号码" options={modelOptions}
              filterOption={(input, option) =>
                (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())} />
          </Form.Item>
          <Form.Item label="优先级" name="priority" initialValue={100}>
            <InputNumber min={1} max={9999} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

// ══════════════════════════════════════════════
// Tab 4: 干扰项存档
// ══════════════════════════════════════════════
function FilteredItemTab() {
  const [searchParams] = useSearchParams()
  const initialJobId = searchParams.get('job_id') ? Number(searchParams.get('job_id')) : undefined
  const [jobId, setJobId] = useState<number | undefined>(initialJobId)
  const [keyword, setKeyword] = useState('')
  const [page, setPage] = useState(1)
  const [selectedIds, setSelectedIds] = useState<number[]>([])

  const { data: jobsData } = useRequest(() => listCleanJobs().then(r => r.data))
  const { data, loading, refresh } = useRequest(
    () => listFilteredItems({ clean_job_id: jobId, keyword: keyword || undefined, page, page_size: 20 }).then(r => r.data),
    { refreshDeps: [jobId, keyword, page] }
  )

  const handleRecover = async (id: number) => {
    await recoverFilteredItem(id)
    message.success('已恢复')
    refresh()
  }

  const handleBatchRecover = async () => {
    if (!selectedIds.length) { message.warning('请先勾选数据'); return }
    await recoverFilteredItemsBatch(selectedIds)
    message.success(`已恢复 ${selectedIds.length} 条`)
    setSelectedIds([])
    refresh()
  }

  const columns = [
    { title: '商品名称', dataIndex: 'item_name', ellipsis: true },
    { title: '原始品牌', dataIndex: 'brand_raw', width: 120 },
    { title: '触发词', dataIndex: 'matched_keyword', width: 150 },
    { title: '清洗任务', dataIndex: 'clean_job_id', width: 90 },
    {
      title: '操作', width: 80,
      render: (_: unknown, row: { id: number }) => (
        <Button size="small" type="link" onClick={() => handleRecover(row.id)}>恢复</Button>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="warning" showIcon message="恢复后数据将重新进入清洗数据集，可在匹配页对其执行型号匹配。" />
      <Space wrap>
        <Select allowClear placeholder="筛选清洗任务" style={{ width: 200 }}
          value={jobId} onChange={(v: number | undefined) => { setJobId(v); setPage(1) }}
          options={(jobsData ?? []).map((j: { id: number; created_at: string }) => ({
            value: j.id, label: `任务 #${j.id}（${new Date(j.created_at).toLocaleDateString('zh-CN')}）`
          }))} />
        <Input.Search placeholder="搜索触发词" allowClear style={{ width: 200 }}
          onSearch={(v: string) => { setKeyword(v); setPage(1) }} />
        <Button onClick={handleBatchRecover} disabled={!selectedIds.length}>
          批量恢复（{selectedIds.length}）
        </Button>
      </Space>
      <Table
        dataSource={data?.items ?? []} columns={columns} rowKey="id" size="small" loading={loading}
        rowSelection={{ selectedRowKeys: selectedIds, onChange: (keys: React.Key[]) => setSelectedIds(keys as number[]) }}
        pagination={{ current: page, total: data?.total ?? 0, pageSize: 20,
          onChange: setPage, showTotal: (t: number) => `共 ${t} 条` }}
      />
    </Space>
  )
}

// ══════════════════════════════════════════════
// 主页面
// ══════════════════════════════════════════════
export default function RulesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') ?? 'noise')

  return (
    <Card>
      <Tabs
        activeKey={activeTab}
        onChange={(key) => {
          setActiveTab(key)
          setSearchParams(key !== 'noise' ? { tab: key } : {})
        }}
        items={[
          { key: 'noise',    label: '干扰词库',   children: <NoiseWordTab /> },
          { key: 'brand',    label: '品牌写法库', children: <BrandAliasTab /> },
          { key: 'rules',    label: '匹配规则',   children: <MatchRuleTab /> },
          { key: 'filtered', label: '干扰项存档', children: <FilteredItemTab /> },
        ]}
      />
    </Card>
  )
}
