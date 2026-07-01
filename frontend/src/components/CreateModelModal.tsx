import { useEffect, useMemo, useState } from 'react'
import {
  Alert, Button, Col, Collapse, Divider, Form, Input, InputNumber,
  Modal, Row, Select, Typography, message,
} from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import {
  createModel,
  listBrands,
  type BrandItem,
  type CreateModelPayload,
  type MatchMetadataSpec,
  type ModelItem,
  type ModelSpecPayload,
} from '../services/api'
import CreateBrandModal from './CreateBrandModal'

const { Text } = Typography

type CreateModelFormValues = {
  brand_code: string
  model_code: string
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

type CreateModelModalProps = {
  open: boolean
  onCancel: () => void
  onCreated?: (model: ModelItem) => void
  defaultCategoryCode?: string | null
  defaultCategoryName?: string | null
  metadataSpecs?: MatchMetadataSpec[]
  brandSuggestion?: string | null
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
  metadataSpecs = [],
  brandSuggestion,
}: CreateModelModalProps) {
  const [form] = Form.useForm<CreateModelFormValues>()
  const [brands, setBrands] = useState<BrandItem[]>([])
  const [brandsLoading, setBrandsLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [brandModalOpen, setBrandModalOpen] = useState(false)

  const selectedBrandCode = Form.useWatch('brand_code', form)
  const selectedBrand = useMemo(
    () => brands.find(brand => brand.brand_code === selectedBrandCode),
    [brands, selectedBrandCode]
  )

  const loadBrands = async () => {
    setBrandsLoading(true)
    try {
      const res = await listBrands()
      setBrands(res.data)
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

  const handleOk = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const specs: ModelSpecPayload[] = Object.entries(values.spec_values ?? {})
        .map(([specName, specValue]) => ({ spec_name: specName, spec_value: trimOrNull(specValue) }))
        .filter(spec => spec.spec_value)

      const payload: CreateModelPayload = {
        brand_code: values.brand_code,
        brand_name: selectedBrand?.brand_name ?? null,
        model_code: values.model_code.trim(),
        model_name: trimOrNull(values.model_name),
        category_code: defaultCategoryCode || null,
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
                  filterOption={(input, option) => String(option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
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
              <Form.Item label="品类">
                <Input value={defaultCategoryName || defaultCategoryCode || '未识别品类'} disabled />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="状态" name="status" initialValue="active">
                <Select options={[{ value: 'active', label: '启用' }, { value: 'inactive', label: '停用' }]} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={6}><Form.Item label="上市年" name="launch_year"><InputNumber style={{ width: '100%' }} min={2000} max={2099} /></Form.Item></Col>
            <Col span={6}><Form.Item label="上市月" name="launch_month"><InputNumber style={{ width: '100%' }} min={1} max={12} /></Form.Item></Col>
            <Col span={6}><Form.Item label="上市周" name="launch_week"><InputNumber style={{ width: '100%' }} min={1} max={53} /></Form.Item></Col>
            <Col span={6}><Form.Item label="上市价格" name="launch_price"><InputNumber style={{ width: '100%' }} min={0} precision={2} prefix="¥" /></Form.Item></Col>
          </Row>
          <Form.Item label="网址" name="url"><Input placeholder="https://..." /></Form.Item>
          <Form.Item label="操作人" name="operator"><Input placeholder="如 alice" /></Form.Item>

          <Collapse
            size="small"
            items={[{
              key: 'specs',
              label: '规格属性（选填）',
              children: metadataSpecs.length > 0 ? (
                <Row gutter={12}>
                  {metadataSpecs.map(spec => (
                    <Col span={12} key={spec.id}>
                      <Form.Item label={spec.spec_name} name={['spec_values', spec.spec_name]}>
                        <Input placeholder="不填写也可创建" />
                      </Form.Item>
                    </Col>
                  ))}
                </Row>
              ) : (
                <Text type="secondary">选择品类后可填写规格属性；当前没有可用字段定义。</Text>
              ),
            }]}
          />
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
