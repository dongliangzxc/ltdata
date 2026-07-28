import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Col, Divider, Form, Input, InputNumber,
  Modal, Row, Select, Space, Switch, Typography, message,
} from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import {
  createMetadata,
  createModel,
  listBrands,
  type BrandItem,
  type CreateModelPayload,
  type MatchMetadataSpec,
  type MetadataSpecPayload,
  type ModelItem,
  type ModelSpecPayload,
} from '../services/api'
import CreateBrandModal from './CreateBrandModal'

const { Text } = Typography

type CreateModelFormValues = {
  brand_code: string
  model_code: string
  category_code?: string | null
  model_name?: string | null
  status?: string
  launch_year?: number | null
  launch_month?: number | null
  launch_week?: number | null
  launch_price?: number | null
  url?: string | null
  operator?: string | null
  spec_values?: Record<string, string | undefined>
}

type CategoryOption = {
  value: string
  label: string
}

type CreateModelModalProps = {
  open: boolean
  onCancel: () => void
  onCreated?: (model: ModelItem) => void
  defaultCategoryCode?: string | null
  defaultCategoryName?: string | null
  categoryOptions?: CategoryOption[]
  metadataSpecs?: MatchMetadataSpec[]
  brandSuggestion?: string | null
  onMetadataChanged?: () => Promise<void> | void
}

const trimOrNull = (value?: string | null) => {
  const trimmed = (value ?? '').trim()
  return trimmed || null
}

export default function CreateModelModal({
  open,
  onCancel,
  onCreated,
  defaultCategoryCode,
  defaultCategoryName,
  categoryOptions = [],
  metadataSpecs = [],
  brandSuggestion,
  onMetadataChanged,
}: CreateModelModalProps) {
  const [form] = Form.useForm<CreateModelFormValues>()
  const [metadataForm] = Form.useForm<MetadataSpecPayload>()
  const [brands, setBrands] = useState<BrandItem[]>([])
  const [brandsLoading, setBrandsLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [brandModalOpen, setBrandModalOpen] = useState(false)
  const [specSearch, setSpecSearch] = useState('')
  const [metadataModalOpen, setMetadataModalOpen] = useState(false)
  const [metadataSaving, setMetadataSaving] = useState(false)

  const selectedBrandCode = Form.useWatch('brand_code', form)
  const selectedBrand = useMemo(
    () => brands.find(brand => brand.brand_code === selectedBrandCode),
    [brands, selectedBrandCode]
  )

  const currentCategoryCode = defaultCategoryCode?.trim() || undefined
  const canManageMetadata = Boolean(currentCategoryCode && onMetadataChanged)

  const filteredMetadataSpecs = useMemo(() => {
    const keyword = specSearch.trim().toLowerCase()
    if (!keyword) return metadataSpecs
    return metadataSpecs.filter(spec => spec.spec_name.toLowerCase().includes(keyword))
  }, [metadataSpecs, specSearch])

  const requiredSpecs = useMemo(
    () => filteredMetadataSpecs.filter(spec => spec.required),
    [filteredMetadataSpecs]
  )
  const optionalSpecs = useMemo(
    () => filteredMetadataSpecs.filter(spec => !spec.required),
    [filteredMetadataSpecs]
  )

  const loadBrands = async (keyword?: string) => {
    setBrandsLoading(true)
    try {
      const res = await listBrands({ keyword: keyword?.trim() || undefined, page_size: 50 })
      setBrands(res.data.items)
    } finally {
      setBrandsLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    form.resetFields()
    form.setFieldsValue({ status: 'active', spec_values: {} })
    loadBrands()
  }, [form, open])

  const handleCreatedBrand = (brand: BrandItem) => {
    setBrands(prev => {
      const exists = prev.some(item => item.brand_code === brand.brand_code)
      return exists ? prev : [...prev, brand].sort((a, b) => a.brand_code.localeCompare(b.brand_code))
    })
    form.setFieldsValue({ brand_code: brand.brand_code })
    setBrandModalOpen(false)
  }

  const openMetadataModal = () => {
    if (!currentCategoryCode) {
      message.warning('当前记录缺少品类，无法新建字段要求')
      return
    }
    if (!onMetadataChanged) {
      message.warning('当前上下文无法新建字段要求')
      return
    }
    metadataForm.resetFields()
    metadataForm.setFieldsValue({
      category_code: currentCategoryCode,
      spec_type: '文本型',
      required: false,
      single_select: true,
      decimal_places: null,
      spec_values: null,
    })
    setMetadataModalOpen(true)
  }

  const handleCreateMetadata = async () => {
    if (!currentCategoryCode) {
      message.warning('当前记录缺少品类，无法新建字段要求')
      return
    }
    if (!onMetadataChanged) {
      message.warning('当前上下文无法新建字段要求')
      return
    }
    const values = await metadataForm.validateFields()
    const payload: MetadataSpecPayload = {
      category_code: currentCategoryCode,
      spec_name: values.spec_name.trim(),
      spec_type: values.spec_type,
      spec_values: trimOrNull(values.spec_values),
      required: Boolean(values.required),
      decimal_places: values.decimal_places ?? null,
      single_select: values.single_select ?? true,
    }
    setMetadataSaving(true)
    try {
      await createMetadata(payload)
      message.success('字段要求已新建')
      setMetadataModalOpen(false)
      await onMetadataChanged?.()
      setSpecSearch('')
    } finally {
      setMetadataSaving(false)
    }
  }

  const handleOk = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const specs: ModelSpecPayload[] = Object.entries(values.spec_values ?? {})
        .map(([specName, specValue]) => ({ spec_name: specName, spec_value: trimOrNull(specValue) }))
        .filter(spec => spec.spec_value)

      const selectedCategoryCode = defaultCategoryCode || values.category_code || null
      const payload: CreateModelPayload = {
        brand_code: values.brand_code,
        brand_name: selectedBrand?.brand_name ?? null,
        model_code: values.model_code.trim(),
        model_name: trimOrNull(values.model_name),
        category_code: selectedCategoryCode,
        status: values.status || 'active',
        launch_year: values.launch_year ?? null,
        launch_month: values.launch_month ?? null,
        launch_week: values.launch_week ?? null,
        launch_price: values.launch_price ?? null,
        url: trimOrNull(values.url),
        operator: trimOrNull(values.operator),
        specs,
      }
      const res = await createModel(payload)
      message.success('型号已创建')
      onCreated?.(res.data)
      form.resetFields()
    } catch {
      // errors shown by axios interceptor
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Modal
        title="新建型号"
        open={open}
        onOk={handleOk}
        confirmLoading={saving}
        onCancel={() => { form.resetFields(); onCancel() }}
        okText="创建"
        cancelText="取消"
        width={720}
        destroyOnClose
      >
        <Form form={form} layout="vertical" style={{ marginTop: 8 }}>
          <Divider orientation="left" plain style={{ fontSize: 13, color: '#666' }}>品牌信息</Divider>
          {brandSuggestion && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={`当前商品原始品牌：${brandSuggestion}。可作为品牌名称参考，但不会自动生成品牌码。`}
            />
          )}
          <Row gutter={12} align="bottom">
            <Col flex="auto">
              <Form.Item label="品牌" name="brand_code" rules={[{ required: true, message: '请先选择或新建品牌' }]}>
                <Select
                  showSearch
                  placeholder="搜索并选择品牌"
                  loading={brandsLoading}
                  options={brands.map(brand => ({
                    value: brand.brand_code,
                    label: `${brand.brand_name || brand.brand_code}（${brand.brand_code}）`,
                  }))}
                  filterOption={false}
                  onSearch={loadBrands}
                />
              </Form.Item>
            </Col>
            <Col>
              <Form.Item label=" ">
                <Button icon={<PlusOutlined />} onClick={() => setBrandModalOpen(true)}>
                  新建品牌
                </Button>
              </Form.Item>
            </Col>
          </Row>

          <Divider orientation="left" plain style={{ fontSize: 13, color: '#666' }}>型号信息</Divider>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="型号码" name="model_code" rules={[{ required: true, message: '请填写型号码' }]}>
                <Input placeholder="如 OSMO-ACTION-4" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="型号名称" name="model_name">
                <Input placeholder="如 Osmo Action 4" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              {defaultCategoryCode ? (
                <Form.Item label="品类">
                  <Input value={defaultCategoryName || defaultCategoryCode} disabled />
                </Form.Item>
              ) : (
                <Form.Item label="品类" name="category_code">
                  <Select
                    allowClear
                    showSearch
                    placeholder="请选择品类"
                    options={categoryOptions}
                    filterOption={(input, option) => String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
                  />
                </Form.Item>
              )}
            </Col>
            <Col span={12}>
              <Form.Item label="状态" name="status" initialValue="active">
                <Select options={[{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }]} />
              </Form.Item>
            </Col>
          </Row>

          <Divider orientation="left" plain style={{ fontSize: 13, color: '#666' }}>品类属性 / 品类字段要求</Divider>
          <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder="搜索字段要求"
              value={specSearch}
              onChange={event => setSpecSearch(event.target.value)}
            />
            <Button icon={<PlusOutlined />} onClick={openMetadataModal} disabled={!canManageMetadata}>
              新建字段要求
            </Button>
          </Space.Compact>
          {filteredMetadataSpecs.length === 0 ? (
            <Text type="secondary">当前品类没有匹配的字段要求。</Text>
          ) : (
            <>
              <Text type="secondary" style={{ fontSize: 12 }}>必填</Text>
              {requiredSpecs.length === 0 ? (
                <div style={{ marginTop: 4, marginBottom: 12 }}>
                  <Text type="secondary">当前品类无必填规格属性。</Text>
                </div>
              ) : (
                <Row gutter={12} style={{ marginTop: 4 }}>
                  {requiredSpecs.map(spec => (
                    <Col span={12} key={spec.id}>
                      <Form.Item
                        label={spec.spec_name}
                        name={['spec_values', spec.spec_name]}
                        rules={[{ required: true, message: `请填写${spec.spec_name}` }]}
                      >
                        <Input placeholder={`请填写${spec.spec_name}`} />
                      </Form.Item>
                    </Col>
                  ))}
                </Row>
              )}
              <Text type="secondary" style={{ fontSize: 12 }}>选填</Text>
              {optionalSpecs.length === 0 ? (
                <div style={{ marginTop: 4, marginBottom: 12 }}>
                  <Text type="secondary">当前品类无选填规格属性。</Text>
                </div>
              ) : (
                <Row gutter={12} style={{ marginTop: 4 }}>
                  {optionalSpecs.map(spec => (
                    <Col span={12} key={spec.id}>
                      <Form.Item label={spec.spec_name} name={['spec_values', spec.spec_name]}>
                        <Input placeholder="不填写也可创建" />
                      </Form.Item>
                    </Col>
                  ))}
                </Row>
              )}
            </>
          )}

          <Divider orientation="left" plain style={{ fontSize: 13, color: '#666' }}>上市信息</Divider>
          <Row gutter={12}>
            <Col span={6}><Form.Item label="上市年" name="launch_year"><InputNumber style={{ width: '100%' }} min={2000} max={2099} /></Form.Item></Col>
            <Col span={6}><Form.Item label="上市月" name="launch_month"><InputNumber style={{ width: '100%' }} min={1} max={12} /></Form.Item></Col>
            <Col span={6}><Form.Item label="上市周" name="launch_week"><InputNumber style={{ width: '100%' }} min={1} max={53} /></Form.Item></Col>
            <Col span={6}><Form.Item label="上市价格" name="launch_price"><InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" /></Form.Item></Col>
          </Row>
          <Form.Item label="网址" name="url"><Input placeholder="https://..." /></Form.Item>
          <Form.Item label="操作人" name="operator"><Input placeholder="如 alice" /></Form.Item>
        </Form>
      </Modal>

      <Modal
        title="新建字段要求"
        open={metadataModalOpen}
        onOk={handleCreateMetadata}
        onCancel={() => setMetadataModalOpen(false)}
        confirmLoading={metadataSaving}
        okText="新建"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={metadataForm} layout="vertical">
          <Form.Item label="当前品类" name="category_code">
            <Input disabled />
          </Form.Item>
          <Form.Item
            label="字段名称"
            name="spec_name"
            rules={[{ required: true, whitespace: true, message: '请输入字段名称' }]}
          >
            <Input placeholder="例如：佩戴方式" />
          </Form.Item>
          <Form.Item label="字段类型" name="spec_type" rules={[{ required: true, message: '请选择字段类型' }]}>
            <Select
              options={[
                { value: '文本型', label: '文本型' },
                { value: '数值型', label: '数值型' },
                { value: '枚举型', label: '枚举型' },
              ]}
            />
          </Form.Item>
          <Form.Item label="可选值" name="spec_values">
            <Input.TextArea rows={3} placeholder="多个值用逗号分隔" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="小数位" name="decimal_places">
                <InputNumber style={{ width: '100%' }} min={0} max={6} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="是否单选" name="single_select" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="是否必填" name="required" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <CreateBrandModal
        open={brandModalOpen}
        initialBrandName={brandSuggestion}
        onCancel={() => setBrandModalOpen(false)}
        onCreated={handleCreatedBrand}
      />
    </>
  )
}
