import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Tabs, Card, Table, Button, Input, Select, Space, Popconfirm,
  Upload, Modal, Form, InputNumber, Tag, message, Alert, Switch,
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
  listAttrRuleCategories, listAttrRules, createAttrRule,
  updateAttrRule, deleteAttrRule,
  listCorrectionRules, createCorrectionRule, updateCorrectionRule, deleteCorrectionRule,
} from '../../services/api'
import { useCategoryOptions } from '../../hooks/useCategoryOptions'

// ══════════════════════════════════════════════
// Tab 1: 干扰词库
// ══════════════════════════════════════════════
function NoiseWordTab() {
  const [keyword, setKeyword] = useState('')
  const [matchField, setMatchField] = useState('item_name')
  const [adding, setAdding] = useState(false)
  const [categoryCode, setCategoryCode] = useState<string | undefined>()
  const [addCategoryCode, setAddCategoryCode] = useState<string | undefined>()
  const { options: categoryOptions } = useCategoryOptions()
  const { data, loading, refresh } = useRequest(
    () => listNoiseWords(categoryCode ? { category_code: categoryCode } : undefined).then(r => r.data),
    { refreshDeps: [categoryCode] }
  )

  const handleAdd = async () => {
    if (!keyword.trim()) { message.warning('请输入关键词'); return }
    setAdding(true)
    try {
      await createNoiseWord({ keyword: keyword.trim(), match_field: matchField, category_code: addCategoryCode || null })
      message.success('添加成功')
      setKeyword('')
      setAddCategoryCode(undefined)
      refresh()
    } finally { setAdding(false) }
  }

  const columns = [
    { title: '关键词', dataIndex: 'keyword', ellipsis: true },
    { title: '匹配字段', dataIndex: 'match_field', width: 120,
      render: (v: string) => ({ item_name: '商品名称', shop_name: '店铺名称', brand_raw: '原始品牌' }[v] ?? v) },
    { title: '品类', dataIndex: 'category_code', width: 120,
      render: (v: string | null) => v ?? '-' },
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
        <Select
          placeholder="品类（可选）"
          allowClear
          style={{ width: 140 }}
          options={categoryOptions}
          value={addCategoryCode}
          onChange={v => setAddCategoryCode(v)}
        />
        <Button type="primary" icon={<PlusOutlined />} loading={adding} onClick={handleAdd}>添加</Button>
        <Select
          placeholder="品类筛选"
          allowClear
          style={{ width: 140 }}
          options={categoryOptions}
          onChange={v => setCategoryCode(v)}
        />
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
// Tab 5: 属性规则
// ══════════════════════════════════════════════
function AttrRuleTab() {
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Record<string, unknown> | null>(null)
  const [filterCategory, setFilterCategory] = useState<string | undefined>(undefined)
  const [form] = Form.useForm()

  const { data: categories } = useRequest(() =>
    listAttrRuleCategories().then(r => r.data as { code: string; name: string }[])
  )
  const { data, loading, refresh } = useRequest(
    () => listAttrRules(filterCategory ? { category_code: filterCategory } : undefined).then(r => r.data),
    { refreshDeps: [filterCategory] }
  )

  const openAdd = () => { setEditing(null); form.resetFields(); setModalOpen(true) }
  const openEdit = (row: Record<string, unknown>) => {
    setEditing(row)
    form.setFieldsValue({ ...row, category_code: row.category_code ?? undefined })
    setModalOpen(true)
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    values.category_code = values.category_code || null
    if (editing) {
      await updateAttrRule(editing.id as number, values)
      message.success('更新成功')
    } else {
      await createAttrRule(values)
      message.success('添加成功')
    }
    setModalOpen(false)
    refresh()
  }

  const categoryOptions = [
    { value: '', label: '全部' },
    { value: '__global__', label: '全局（无品类限制）' },
    ...(categories ?? []).map(c => ({ value: c.code, label: c.name })),
  ]

  const columns = [
    { title: '品类', dataIndex: 'category_code', width: 120,
      render: (v: string | null) => {
        if (!v) return <Tag color="blue">全局</Tag>
        const cat = (categories ?? []).find(c => c.code === v)
        return <Tag>{cat ? cat.name : v}</Tag>
      } },
    { title: '关键词', dataIndex: 'keyword', ellipsis: true },
    { title: '匹配方式', dataIndex: 'match_type', width: 90,
      render: (v: string) => v === 'exact' ? '精准' : '包含' },
    { title: '属性名', dataIndex: 'attr_name', width: 120 },
    { title: '属性值', dataIndex: 'attr_value', ellipsis: true },
    { title: '优先级', dataIndex: 'priority', width: 80 },
    { title: '状态', dataIndex: 'is_active', width: 80,
      render: (v: number) => v ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag> },
    {
      title: '操作', width: 150,
      render: (_: unknown, row: Record<string, unknown>) => (
        <Space size={4}>
          <Button size="small" onClick={() => openEdit(row)}>编辑</Button>
          <Button size="small" icon={row.is_active ? <StopOutlined /> : <CheckCircleOutlined />}
            onClick={async () => { await updateAttrRule(row.id as number, { is_active: row.is_active ? 0 : 1 }); refresh() }}>
            {row.is_active ? '禁用' : '启用'}
          </Button>
          <Popconfirm title="确认删除？" onConfirm={async () => { await deleteAttrRule(row.id as number); refresh() }}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const modalCategoryOptions = [
    { value: '', label: '全局（不限品类）' },
    ...(categories ?? []).map(c => ({ value: c.code, label: c.name })),
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="info" showIcon
        message="属性规则在型号确认后自动触发，根据商品名称中的关键词自动打属性标签（如屏幕尺寸、声道数等）。品类规则优先于全局规则。" />
      <Space wrap>
        <Select
          placeholder="按品类筛选"
          allowClear
          style={{ width: 160 }}
          options={categoryOptions}
          value={filterCategory}
          onChange={v => setFilterCategory(v || undefined)}
        />
        <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>添加规则</Button>
      </Space>
      <Table dataSource={data ?? []} columns={columns} rowKey="id" size="small" loading={loading}
        pagination={{ pageSize: 20, showTotal: (t: number) => `共 ${t} 条` }} />

      <Modal
        title={editing ? '编辑属性规则' : '新增属性规则'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        destroyOnClose
      >
        <Form form={form} layout="vertical">
          <Form.Item label="品类（留空=全局生效）" name="category_code">
            <Select allowClear placeholder="选择品类（不选=全局）" options={modalCategoryOptions} />
          </Form.Item>
          <Form.Item label="关键词" name="keyword" rules={[{ required: true, message: '请输入关键词' }]}>
            <Input placeholder="如：65英寸" />
          </Form.Item>
          <Form.Item label="匹配方式" name="match_type" initialValue="contains">
            <Select options={[{ value: 'contains', label: '包含' }, { value: 'exact', label: '精准' }]} />
          </Form.Item>
          <Form.Item label="属性名" name="attr_name" rules={[{ required: true, message: '请输入属性名' }]}>
            <Input placeholder="如：屏幕尺寸" />
          </Form.Item>
          <Form.Item label="属性值" name="attr_value" rules={[{ required: true, message: '请输入属性值' }]}>
            <Input placeholder="如：65英寸" />
          </Form.Item>
          <Form.Item label="优先级（数字越小越先执行）" name="priority" initialValue={100}>
            <InputNumber min={1} max={9999} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}

// ══════════════════════════════════════════════
// Tab 6: 修正规则
// ══════════════════════════════════════════════
interface CorrectionRule {
  id: number
  name: string
  category_code: string | null
  brand_code: string | null
  model_id: number | null
  attr_name: string | null
  attr_value: string | null
  target: string
  rule_type: string
  value: number
  priority: number
  is_active: boolean
}

function CorrectionRulesTab() {
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const [filterCategory, setFilterCategory] = useState<string | undefined>()
  const { options: categoryOptions } = useCategoryOptions()
  const { data, loading, refresh } = useRequest(
    () => listCorrectionRules(filterCategory ? { category_code: filterCategory } : undefined).then(r => r.data),
    { refreshDeps: [filterCategory] }
  )

  const openCreate = () => {
    setEditingId(null)
    form.resetFields()
    form.setFieldsValue({ priority: 100, is_active: true })
    setModalOpen(true)
  }

  const openEdit = (row: CorrectionRule) => {
    setEditingId(row.id)
    form.setFieldsValue({
      name: row.name,
      category_code: row.category_code ?? undefined,
      brand_code: row.brand_code ?? undefined,
      model_id: row.model_id ?? undefined,
      attr_name: row.attr_name ?? undefined,
      attr_value: row.attr_value ?? undefined,
      target: row.target,
      rule_type: row.rule_type,
      value: row.value,
      priority: row.priority,
      is_active: row.is_active,
    })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const vals = await form.validateFields()
    // convert empty strings to null for optional fields
    const payload: Record<string, unknown> = {
      ...vals,
      category_code: vals.category_code || null,
      brand_code: vals.brand_code || null,
      model_id: vals.model_id ?? null,
      attr_name: vals.attr_name || null,
      attr_value: vals.attr_value || null,
    }
    if (editingId) {
      await updateCorrectionRule(editingId, payload)
      message.success('更新成功')
    } else {
      await createCorrectionRule(payload)
      message.success('添加成功')
    }
    setModalOpen(false)
    refresh()
  }

  const targetLabel = (v: string) =>
    ({ sales_qty: '销量', sales_amount: '销售额', both: '销量+销售额' }[v] ?? v)

  const ruleTypeLabel = (v: string) =>
    ({ multiply: '乘系数', offset: '加偏移' }[v] ?? v)

  const columns = [
    { title: '名称', dataIndex: 'name', ellipsis: true },
    { title: '品类', dataIndex: 'category_code', width: 100,
      render: (v: string | null) => v ? <Tag>{v}</Tag> : <Tag color="blue">全局</Tag> },
    { title: '品牌', dataIndex: 'brand_code', width: 100,
      render: (v: string | null) => v ?? '—' },
    { title: '型号ID', dataIndex: 'model_id', width: 80,
      render: (v: number | null) => v ?? '—' },
    { title: '属性(name=value)', width: 160,
      render: (_: unknown, row: CorrectionRule) =>
        row.attr_name ? `${row.attr_name}=${row.attr_value ?? ''}` : '—' },
    { title: '目标', dataIndex: 'target', width: 110,
      render: (v: string) => targetLabel(v) },
    { title: '类型', dataIndex: 'rule_type', width: 90,
      render: (v: string) => ruleTypeLabel(v) },
    { title: '值', dataIndex: 'value', width: 80 },
    { title: '优先级', dataIndex: 'priority', width: 80,
      sorter: (a: CorrectionRule, b: CorrectionRule) => a.priority - b.priority },
    { title: '启用', dataIndex: 'is_active', width: 70,
      render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag color="default">禁用</Tag> },
    {
      title: '操作', width: 120,
      render: (_: unknown, row: CorrectionRule) => (
        <Space size={4}>
          <Button size="small" onClick={() => openEdit(row)}>编辑</Button>
          <Popconfirm title="确认删除？" onConfirm={async () => { await deleteCorrectionRule(row.id); refresh() }}>
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
          message="修正规则在发布前对匹配结果的销量/销售额执行系数乘法或偏移量加减。优先级数字越小越先执行，可按品类/品牌/型号/属性组合精细匹配。" />
        <Space wrap>
          <Select
            placeholder="品类筛选"
            allowClear
            style={{ width: 140 }}
            options={categoryOptions}
            value={filterCategory}
            onChange={v => setFilterCategory(v || undefined)}
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增规则</Button>
        </Space>
        <Table
          dataSource={data ?? []}
          columns={columns}
          rowKey="id"
          size="small"
          loading={loading}
          pagination={{ pageSize: 20, showTotal: (t: number) => `共 ${t} 条` }}
        />
      </Space>

      <Modal
        title={editingId ? '编辑修正规则' : '新增修正规则'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入规则名称' }]}>
            <Input placeholder="规则名称，便于识别" />
          </Form.Item>
          <Form.Item label="品类（留空=全局）" name="category_code">
            <Select
              allowClear
              placeholder="选择品类（留空=全局）"
              options={categoryOptions}
            />
          </Form.Item>
          <Form.Item label="品牌码（留空=不限）" name="brand_code">
            <Input placeholder="如：SONY" />
          </Form.Item>
          <Form.Item label="型号ID（留空=不限）" name="model_id">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="精确匹配某个型号ID" />
          </Form.Item>
          <Form.Item label="属性名（留空=不限）" name="attr_name">
            <Input placeholder="如：屏幕尺寸" />
          </Form.Item>
          <Form.Item label="属性值（留空=不限）" name="attr_value">
            <Input placeholder="如：65英寸" />
          </Form.Item>
          <Form.Item label="目标字段" name="target" initialValue="both" rules={[{ required: true }]}>
            <Select options={[
              { value: 'sales_qty', label: '销量' },
              { value: 'sales_amount', label: '销售额' },
              { value: 'both', label: '销量 + 销售额' },
            ]} />
          </Form.Item>
          <Form.Item label="规则类型" name="rule_type" initialValue="multiply" rules={[{ required: true }]}>
            <Select options={[
              { value: 'multiply', label: '乘系数（value × 系数）' },
              { value: 'offset', label: '加偏移（value + 偏移量）' },
            ]} />
          </Form.Item>
          <Form.Item label="值（系数或偏移量）" name="value" rules={[{ required: true, message: '请输入数值' }]}>
            <InputNumber style={{ width: '100%' }} placeholder="如：0.9 或 -100" step={0.01} />
          </Form.Item>
          <Form.Item label="优先级（数字越小越先执行）" name="priority" initialValue={100}>
            <InputNumber min={1} max={9999} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="启用" name="is_active" valuePropName="checked" initialValue={true}>
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
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
          { key: 'noise',      label: '干扰词库',   children: <NoiseWordTab /> },
          { key: 'brand',      label: '品牌写法库', children: <BrandAliasTab /> },
          { key: 'rules',      label: '匹配规则',   children: <MatchRuleTab /> },
          { key: 'filtered',   label: '干扰项存档', children: <FilteredItemTab /> },
          { key: 'attr',       label: '属性规则',   children: <AttrRuleTab /> },
          { key: 'correction', label: '修正规则',   children: <CorrectionRulesTab /> },
        ]}
      />
    </Card>
  )
}
