import { useMemo, useState } from 'react'
import {
  Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm,
  Select, Space, Switch, Table, Tabs, Tag, Typography, message,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  createCountry, createExchangeRate, deleteCountry, deleteExchangeRate,
  listCountries, listExchangeRates, updateCountry, updateExchangeRate,
  type CountryItem, type ExchangeRateItem,
} from '../../services/api'

const { Text } = Typography

type CountryForm = {
  code: string
  name_cn: string
  name_en?: string
  currency_code: string
  currency_symbol?: string
  region: 'domestic' | 'overseas'
  sort_order: number
  is_active: boolean
}

type RateForm = {
  country_code: string
  rate_to_cny: number
  remark?: string
}

export default function CountriesPage() {
  const [activeTab, setActiveTab] = useState('countries')
  const [countryModalOpen, setCountryModalOpen] = useState(false)
  const [editingCountry, setEditingCountry] = useState<CountryItem | null>(null)
  const [rateModalOpen, setRateModalOpen] = useState(false)
  const [editingRate, setEditingRate] = useState<ExchangeRateItem | null>(null)
  const [saving, setSaving] = useState(false)
  const [countryForm] = Form.useForm<CountryForm>()
  const [rateForm] = Form.useForm<RateForm>()

  const { data: countries, loading: countriesLoading, refresh: refreshCountries } = useRequest(
    () => listCountries().then(r => r.data)
  )
  const { data: rates, loading: ratesLoading, refresh: refreshRates } = useRequest(
    () => listExchangeRates().then(r => r.data)
  )

  const countryOptions = useMemo(
    () => (countries ?? [])
      .filter(country => country.is_active === 1)
      .map(country => ({
        value: country.code,
        label: `${country.name_cn}（${country.code} / ${country.currency_code}）`,
      })),
    [countries],
  )
  const configuredRateCodes = useMemo(
    () => new Set((rates ?? []).map(rate => rate.country_code)),
    [rates],
  )
  const availableRateCountryOptions = useMemo(
    () => countryOptions.filter(option => option.value !== 'CN' && !configuredRateCodes.has(option.value)),
    [countryOptions, configuredRateCodes],
  )

  const openCreateCountry = () => {
    setEditingCountry(null)
    countryForm.resetFields()
    countryForm.setFieldsValue({ region: 'overseas', sort_order: 100, is_active: true })
    setCountryModalOpen(true)
  }

  const openEditCountry = (country: CountryItem) => {
    setEditingCountry(country)
    countryForm.setFieldsValue({
      code: country.code,
      name_cn: country.name_cn,
      name_en: country.name_en || undefined,
      currency_code: country.currency_code,
      currency_symbol: country.currency_symbol || undefined,
      region: country.region,
      sort_order: country.sort_order,
      is_active: country.is_active === 1,
    })
    setCountryModalOpen(true)
  }

  const saveCountry = async () => {
    const values = await countryForm.validateFields()
    setSaving(true)
    try {
      if (editingCountry) {
        await updateCountry(editingCountry.code, {
          name_cn: values.name_cn,
          name_en: values.name_en || null,
          currency_code: values.currency_code,
          currency_symbol: values.currency_symbol || null,
          region: values.region,
          sort_order: values.sort_order,
          is_active: values.is_active ? 1 : 0,
        })
        message.success('国家已更新')
      } else {
        await createCountry({
          code: values.code,
          name_cn: values.name_cn,
          name_en: values.name_en || null,
          currency_code: values.currency_code,
          currency_symbol: values.currency_symbol || null,
          region: values.region,
          sort_order: values.sort_order,
          is_active: values.is_active ? 1 : 0,
        })
        message.success('国家已新增')
      }
      setCountryModalOpen(false)
      refreshCountries()
      refreshRates()
    } finally {
      setSaving(false)
    }
  }

  const disableCountry = async (country: CountryItem) => {
    await deleteCountry(country.code)
    message.success('国家已停用')
    refreshCountries()
    refreshRates()
  }

  const openCreateRate = () => {
    setEditingRate(null)
    rateForm.resetFields()
    setRateModalOpen(true)
  }

  const openEditRate = (rate: ExchangeRateItem) => {
    setEditingRate(rate)
    rateForm.setFieldsValue({
      country_code: rate.country_code,
      rate_to_cny: rate.rate_to_cny,
      remark: rate.remark || undefined,
    })
    setRateModalOpen(true)
  }

  const saveRate = async () => {
    const values = await rateForm.validateFields()
    setSaving(true)
    try {
      if (editingRate) {
        await updateExchangeRate(editingRate.id, {
          rate_to_cny: values.rate_to_cny,
          remark: values.remark,
        })
        message.success('汇率已更新')
      } else {
        await createExchangeRate({
          country_code: values.country_code,
          rate_to_cny: values.rate_to_cny,
          remark: values.remark,
        })
        message.success('汇率已新增')
      }
      setRateModalOpen(false)
      refreshRates()
    } finally {
      setSaving(false)
    }
  }

  const deleteRate = async (rate: ExchangeRateItem) => {
    await deleteExchangeRate(rate.id)
    message.success('汇率已删除')
    refreshRates()
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="仅 master 可维护国家和汇率；普通用户上传数据时只能选择这里启用的国家。汇率含义：1 单位该国币种 = N 元人民币。"
      />
      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          tabBarExtraContent={
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => { refreshCountries(); refreshRates() }}>
                刷新
              </Button>
              {activeTab === 'countries'
                ? <Button type="primary" icon={<PlusOutlined />} onClick={openCreateCountry}>新增国家</Button>
                : <Button type="primary" icon={<PlusOutlined />} onClick={openCreateRate}>新增汇率</Button>}
            </Space>
          }
          items={[
            {
              key: 'countries',
              label: `国家与币种（${countries?.length ?? 0}）`,
              children: (
                <Table<CountryItem>
                  rowKey="code"
                  size="small"
                  loading={countriesLoading}
                  dataSource={countries ?? []}
                  pagination={false}
                  scroll={{ x: 900 }}
                  columns={[
                    { title: '国家码', dataIndex: 'code', width: 90 },
                    { title: '中文名', dataIndex: 'name_cn', width: 140 },
                    { title: '英文名', dataIndex: 'name_en', width: 160, render: value => value || '-' },
                    { title: '币种', dataIndex: 'currency_code', width: 90 },
                    { title: '符号', dataIndex: 'currency_symbol', width: 80, render: value => value || '-' },
                    {
                      title: '地区', dataIndex: 'region', width: 100,
                      render: value => <Tag color={value === 'domestic' ? 'blue' : 'orange'}>{value === 'domestic' ? '国内' : '海外'}</Tag>,
                    },
                    {
                      title: '状态', dataIndex: 'is_active', width: 90,
                      render: value => value === 1 ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>,
                    },
                    { title: '排序', dataIndex: 'sort_order', width: 80 },
                    {
                      title: '操作', width: 150,
                      render: (_: unknown, record) => (
                        <Space size={4}>
                          <Button type="link" size="small" onClick={() => openEditCountry(record)}>编辑</Button>
                          {record.code !== 'CN' && record.is_active === 1 && (
                            <Popconfirm title="确认停用该国家？" onConfirm={() => disableCountry(record)}>
                              <Button type="link" size="small" danger>停用</Button>
                            </Popconfirm>
                          )}
                        </Space>
                      ),
                    },
                  ]}
                />
              ),
            },
            {
              key: 'rates',
              label: `汇率（${rates?.length ?? 0}）`,
              children: (
                <Table<ExchangeRateItem>
                  rowKey="id"
                  size="small"
                  loading={ratesLoading}
                  dataSource={rates ?? []}
                  pagination={false}
                  scroll={{ x: 900 }}
                  columns={[
                    { title: '国家', dataIndex: 'country_code', width: 100 },
                    { title: '国家名称', dataIndex: 'country_name', width: 140, render: value => value || '-' },
                    { title: '币种', dataIndex: 'currency_code', width: 90 },
                    {
                      title: '汇率（1 外币 = ? CNY）', dataIndex: 'rate_to_cny', width: 190,
                      render: (value: number) => <Text strong>{Number(value).toFixed(4)}</Text>,
                    },
                    { title: '备注', dataIndex: 'remark', ellipsis: true, render: value => value || '-' },
                    { title: '操作人', dataIndex: 'operator', width: 110, render: value => value || '-' },
                    { title: '更新时间', dataIndex: 'updated_at', width: 170, render: value => value || '-' },
                    {
                      title: '操作', width: 150,
                      render: (_: unknown, record) => (
                        <Space size={4}>
                          <Button type="link" size="small" onClick={() => openEditRate(record)}>编辑</Button>
                          <Popconfirm title="确认删除该汇率？" onConfirm={() => deleteRate(record)}>
                            <Button type="link" size="small" danger>删除</Button>
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={editingCountry ? `编辑国家：${editingCountry.name_cn}` : '新增国家'}
        open={countryModalOpen}
        onOk={saveCountry}
        onCancel={() => setCountryModalOpen(false)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={countryForm} layout="vertical">
          <Form.Item name="code" label="国家码（ISO 2 位）" rules={[{ required: true, message: '请输入国家码' }]}>
            <Input disabled={!!editingCountry} placeholder="如 US / DE / JP" maxLength={8} />
          </Form.Item>
          <Form.Item name="name_cn" label="中文名" rules={[{ required: true, message: '请输入中文名' }]}>
            <Input placeholder="如 美国" />
          </Form.Item>
          <Form.Item name="name_en" label="英文名">
            <Input placeholder="如 United States" />
          </Form.Item>
          <Space size={12} style={{ width: '100%' }}>
            <Form.Item name="currency_code" label="币种" rules={[{ required: true, message: '请输入币种' }]} style={{ width: 200 }}>
              <Input placeholder="如 USD / EUR / JPY" />
            </Form.Item>
            <Form.Item name="currency_symbol" label="币种符号" style={{ width: 160 }}>
              <Input placeholder="如 $ / €" />
            </Form.Item>
          </Space>
          <Space size={12} style={{ width: '100%' }}>
            <Form.Item name="region" label="地区" rules={[{ required: true }]} style={{ width: 200 }}>
              <Select options={[
                { value: 'domestic', label: '国内' },
                { value: 'overseas', label: '海外' },
              ]} />
            </Form.Item>
            <Form.Item name="sort_order" label="排序" style={{ width: 120 }}>
              <InputNumber min={0} max={9999} style={{ width: '100%' }} />
            </Form.Item>
            <Form.Item name="is_active" label="启用" valuePropName="checked" style={{ width: 100 }}>
              <Switch />
            </Form.Item>
          </Space>
        </Form>
      </Modal>

      <Modal
        title={editingRate ? `编辑汇率：${editingRate.country_name || editingRate.country_code}` : '新增汇率'}
        open={rateModalOpen}
        onOk={saveRate}
        onCancel={() => setRateModalOpen(false)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
        destroyOnClose
      >
        <Form form={rateForm} layout="vertical">
          <Form.Item name="country_code" label="国家" rules={[{ required: true, message: '请选择国家' }]}>
            <Select
              showSearch
              optionFilterProp="label"
              disabled={!!editingRate}
              placeholder="选择国家"
              options={editingRate ? countryOptions : availableRateCountryOptions}
            />
          </Form.Item>
          <Form.Item
            name="rate_to_cny"
            label="汇率（1 单位外币 = N 元人民币）"
            rules={[{ required: true, message: '请输入汇率' }]}
          >
            <InputNumber min={0.00000001} precision={8} style={{ width: '100%' }} placeholder="如 7.2" />
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </Space>
  )
}
