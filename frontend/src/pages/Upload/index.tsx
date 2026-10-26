import { useState, useRef, useEffect, useMemo } from 'react'
import {
  Card, Upload, Table, Tag, Button, Popconfirm, Select, Checkbox,
  message, Space, Typography, Spin, Alert, Tabs, Switch, Input,
  Modal, Form, InputNumber, Progress,
} from 'antd'
import {
  InboxOutlined, DeleteOutlined, ReloadOutlined,
  CheckCircleOutlined, EditOutlined, DownloadOutlined, QuestionCircleOutlined,
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  getUploadHeaders, confirmUpload, downloadUploadSample,
  listUploadFiles, deleteUploadFile, downloadUploadBatch, deleteUploadBatch,
  createUploadDownloadJob, listUploadDownloadJobs, getUploadDownloadJobUrl,
  listUploadTemplates,
  createUploadTemplate, updateUploadTemplate, deleteUploadTemplate,
  getUploadConfirmJob, listUploadConfirmJobs, cancelUploadConfirmJob, deleteUploadConfirmJob,
  listCountryOptions,
  type UploadConfirmJobResponse,
  type UploadDownloadJob,
  type CountryOption,
  type UploadFileItem,
  type UploadFilenameHints,
} from '../../services/api'
import ProgressModal from '../../components/ProgressModal'

const { Text } = Typography
const { Option } = Select

// ─── Standard field options ────────────────────────────────────
const STANDARD_FIELD_OPTIONS = [
  { value: 'item_id',       label: 'item_id（商品ID）',     required: true },
  { value: 'month',         label: 'month（月份）',          required: true },
  { value: 'platform',      label: 'platform（平台）',       required: true },
  { value: 'item_name',     label: 'item_name（商品名称）',   required: true },
  { value: 'sales_qty',     label: 'sales_qty（销量）',      required: true },
  { value: 'sales_amount',  label: 'sales_amount（销售额）',  required: true },
  { value: 'price',         label: 'price（价格）',          required: true },
  { value: 'category_lv0',  label: 'category_lv0' },
  { value: 'category_lv1',  label: 'category_lv1' },
  { value: 'category_lv2',  label: 'category_lv2' },
  { value: 'category_lv3',  label: 'category_lv3' },
  { value: 'category_lv4',  label: 'category_lv4' },
  { value: 'category_lv5',  label: 'category_lv5' },
  { value: 'brand_raw',     label: 'brand_raw（原始品牌）' },
  { value: 'shop_name',     label: 'shop_name（店铺名）' },
  { value: 'ref_price',     label: 'ref_price（参考价）' },
  { value: 'item_image',    label: 'item_image（图片URL）' },
  { value: 'item_url',      label: 'item_url（链接）' },
  { value: 'brand_std',     label: 'brand_std（标准品牌）' },
  { value: 'model_std',     label: 'model_std（标准机型）' },
  { value: '__ext__',       label: '存入 ext（extra_data）' },
]

const REQUIRED_FIELDS = new Set(['item_id', 'month', 'platform', 'item_name', 'sales_qty', 'sales_amount', 'price'])

const PLATFORM_LABEL: Record<string, string> = {
  JD: '京东', TM: '天猫', TB: '淘宝',
  jd: '京东', tmall: '天猫', taobao: '淘宝', suning: '苏宁', douyin: '抖音',
  AMAZON: '亚马逊', SHOPEE: '虾皮',
  amazon: '亚马逊', shopee: '虾皮',
  UNKNOWN: '未知平台',
}

const renderVal = (v: unknown) =>
  v == null || v === '' ? <Text type="secondary">-</Text> : String(v)

const uploadJobStatusTag = (status: string) => {
  if (status === 'done') return <Tag color="green">已完成</Tag>
  if (status === 'error') return <Tag color="red">失败</Tag>
  if (status === 'cancelled') return <Tag color="default">已取消</Tag>
  if (status === 'running') return <Tag color="processing">处理中</Tag>
  return <Tag>等待中</Tag>
}

type UploadHistoryRow = UploadFileItem & {
  is_batch?: boolean
  file_count?: number
}

const groupUploadHistory = (files: UploadFileItem[]): UploadHistoryRow[] => {
  const groups = new Map<string, UploadFileItem[]>()
  const order: string[] = []
  for (const file of files) {
    const key = file.batch_key ? `batch:${file.batch_key}` : `file:${file.id}`
    if (!groups.has(key)) {
      groups.set(key, [])
      order.push(key)
    }
    groups.get(key)!.push(file)
  }

  return order.map(key => {
    const group = groups.get(key)!
    if (!key.startsWith('batch:') || group.length <= 1) {
      return { ...group[0], is_batch: false }
    }
    const first = group[0]
    const platforms = Array.from(new Set(group.map(file => file.platform).filter(Boolean) as string[]))
    const monthRanges = Array.from(new Set(group.map(file => file.month_range).filter(Boolean) as string[]))
    const regions = Array.from(new Set(group.map(file => file.data_region).filter(Boolean) as string[]))
    const countries = Array.from(new Set(group.map(file => file.country_code).filter(Boolean) as string[]))
    const years = Array.from(new Set(group.map(file => file.data_year).filter((value): value is number => value != null)))
    const months = Array.from(new Set(group.map(file => file.data_month).filter((value): value is number => value != null)))
    return {
      ...first,
      id: first.id,
      filename: `批量上传（${group.length} 个文件）`,
      platform: platforms.length === 1 ? platforms[0] : platforms.join(' / '),
      month_range: monthRanges.length === 1 ? monthRanges[0] : monthRanges.join(' / '),
      row_count: group.reduce((sum, file) => sum + (file.row_count || 0), 0),
      status: group.every(file => file.status === 'done') ? 'done' : 'batch',
      data_region: regions.length === 1 ? regions[0] : null,
      country_code: countries.length === 1 ? countries[0] : null,
      data_year: years.length === 1 ? years[0] : null,
      data_month: months.length === 1 ? months[0] : null,
      is_batch: true,
      file_count: group.length,
    }
  })
}

// ─── Upload history table columns ────────────────────────────
const historyColumns = (
  onDelete: (id: number) => void,
  startDownloadJob: (id: number) => void,
  downloadJobsByFileId: Record<number, UploadDownloadJob>,
  onBatchDownload: (batchKey: string) => void,
  onBatchDelete: (batchKey: string) => void,
  batchDownloadingKey: string | null,
) => [
  { title: 'ID', dataIndex: 'id', width: 60 },
  {
    title: '文件名',
    dataIndex: 'filename',
    width: 420,
    render: (v: string) => <span style={{ whiteSpace: 'nowrap' }}>{v}</span>,
  },
  {
    title: '平台', dataIndex: 'platform', width: 80,
    render: (v: string) => <Tag color="blue">{PLATFORM_LABEL[v] ?? v}</Tag>,
  },
  { title: '月份范围', dataIndex: 'month_range', width: 130 },
  {
    title: '国内/海外',
    dataIndex: 'data_region',
    width: 90,
    render: (v: string | null) =>
      v === 'domestic' ? <Tag color="blue">国内</Tag>
      : v === 'overseas' ? <Tag color="orange">海外</Tag>
      : <span style={{ color: '#ccc' }}>—</span>,
  },
  {
    title: '国家',
    dataIndex: 'country_code',
    width: 90,
    render: (v: string | null) => v ? <Tag color="purple">{v}</Tag> : <span style={{ color: '#ccc' }}>—</span>,
  },
  {
    title: '年份',
    dataIndex: 'data_year',
    width: 70,
    render: (v: number | null) => v ?? '—',
  },
  { title: '数据量', dataIndex: 'row_count', width: 80 },
  {
    title: '状态', dataIndex: 'status', width: 100,
    render: (v: string, row: UploadHistoryRow) => row.is_batch
      ? <Tag color="blue">{row.file_count} 个文件</Tag>
      : <Tag color={v === 'done' ? 'green' : 'orange'}>{v === 'done' ? '已完成' : v}</Tag>,
  },
  {
    title: '上传时间', dataIndex: 'uploaded_at', width: 170,
    render: (v: string) => v || '—',
  },
  {
    title: '下载状态',
    width: 180,
    render: (_: unknown, row: UploadHistoryRow) => {
      if (row.is_batch) return <span style={{ color: '#999' }}>整批下载</span>
      const job = downloadJobsByFileId[row.id]
      if (!job) return <span style={{ color: '#999' }}>未开始</span>
      if (job.status === 'done') {
        return <Button type="link" size="small" href={getUploadDownloadJobUrl(job.job_id)}>下载文件</Button>
      }
      if (job.status === 'error') {
        return <Typography.Text type="danger">{job.error_msg || '下载准备失败'}</Typography.Text>
      }
      return <Progress percent={job.progress} size="small" status="active" />
    },
  },
  {
    title: '操作', width: 150,
    render: (_: unknown, row: UploadHistoryRow) => {
      if (row.is_batch) {
        return (
          <Space size="small">
            <Button
              type="link"
              icon={<DownloadOutlined />}
              size="small"
              loading={batchDownloadingKey === row.batch_key}
              onClick={() => row.batch_key && onBatchDownload(row.batch_key)}
            >
              下载整批
            </Button>
            <Popconfirm
              title={`确认删除整批 ${row.file_count} 个文件？`}
              description="整批文件及其原始数据会一起删除，且不可恢复。"
              onConfirm={() => row.batch_key && onBatchDelete(row.batch_key)}
              okText="删除整批"
              cancelText="取消"
            >
              <Button type="link" danger icon={<DeleteOutlined />} size="small">删除整批</Button>
            </Popconfirm>
          </Space>
        )
      }
      const job = downloadJobsByFileId[row.id]
      const preparing = job?.status === 'pending' || job?.status === 'running'
      return (
        <Space size="small">
        <Button
          type="link"
          icon={<DownloadOutlined />}
          size="small"
          disabled={preparing}
          onClick={() => startDownloadJob(row.id)}
        >
          {job?.status === 'error' ? '重试' : '下载'}
        </Button>
        <Popconfirm
          title="确认删除该文件记录？"
          onConfirm={() => onDelete(row.id)}
          okText="删除"
          cancelText="取消"
        >
          <Button type="link" danger icon={<DeleteOutlined />} size="small">删除</Button>
        </Popconfirm>
        </Space>
      )
    },
  },
]

// ─── Types ────────────────────────────────────────────────────
type HeadersResult = {
  temp_file_id: string
  filename: string
  columns: string[]
  suggested_template: {
    id: number
    name: string
    platform: string | null
    mapping: Record<string, string>
    ignore_columns: string[]
  } | null
  match_score: number
  filename_hints?: UploadFilenameHints
}

type PendingUploadFile = {
  uid: string
  filename: string
  status: 'uploading' | 'ready' | 'error'
  headersResult?: HeadersResult
  countryCode?: string
  templateId?: number
  templateOverride?: TemplateRow
  filenameHints?: UploadFilenameHints
  error?: string
}

const inferredFieldSet = (headersResult: HeadersResult): Set<string> => {
  const inferred = new Set<string>()
  if (headersResult.filename_hints?.month != null) inferred.add('month')
  if (headersResult.filename_hints?.platform) inferred.add('platform')
  return inferred
}

const buildAutoMapping = (headersResult: HeadersResult, overrideTemplate?: TemplateRow | null) => {
  const columns = headersResult.columns
  const standardFields = new Set(STANDARD_FIELD_OPTIONS.map(option => option.value))
  const mapping: Record<string, string> = {}
  for (const col of columns) {
    if (standardFields.has(col)) mapping[col] = col
  }
  const template = overrideTemplate ?? headersResult.suggested_template
  if (template) {
    for (const col of columns) {
      const target = template.mapping[col]
      if (target && target !== '__ext__') mapping[col] = target
    }
  }
  const targets = new Set(Object.values(mapping))
  const inferred = inferredFieldSet(headersResult)
  const missing = [...REQUIRED_FIELDS].filter(field => !targets.has(field) && !inferred.has(field))
  return {
    mapping,
    ignoreColumns: template?.ignore_columns ?? [],
    missing,
  }
}

type BatchConfirmItem = {
  uid: string
  filename: string
  status: 'pending' | 'running' | 'done' | 'error'
  progress: number
  message?: string
}

type TemplateRow = {
  id: number
  name: string
  platform: string | null
  col_fingerprint: string | null
  mapping: Record<string, string>
  ignore_columns: string[] | null
  is_builtin: number
  updated_at: string | null
}

// ─── MappingCard: Step 2 ─────────────────────────────────────
function MappingCard({
  headersResult,
  templates,
  onSuccess,
  onCancel,
  countryCode,
  dataYear,
  onJobUpdate,
  onTemplateSaved,
}: {
  headersResult: HeadersResult
  templates: TemplateRow[]
  onSuccess: (result: Record<string, unknown>) => void
  onCancel: () => void
  countryCode?: string
  dataYear?: number
  onJobUpdate?: () => void
  onTemplateSaved?: (template: TemplateRow) => void
}) {
  const { columns, suggested_template, match_score, temp_file_id, filename } = headersResult

  const [mapping, setMapping] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {}
    if (suggested_template) {
      for (const col of columns) {
        const target = suggested_template.mapping[col]
        if (target) init[col] = target
      }
    }
    return init
  })

  const [ignoreSet, setIgnoreSet] = useState<Set<string>>(() =>
    new Set(suggested_template?.ignore_columns ?? [])
  )

  const [saveSwitch, setSaveSwitch] = useState(false)
  const [saveName, setSaveName] = useState(suggested_template?.name ?? '')
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | undefined>(
    suggested_template?.id
  )
  const [confirming, setConfirming] = useState(false)
  const [savingTemplate, setSavingTemplate] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadError, setUploadError] = useState('')
  const [uploadProgressVisible, setUploadProgressVisible] = useState(false)
  const [currentJob, setCurrentJob] = useState<UploadConfirmJobResponse | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const applyTemplate = (tmpl: TemplateRow) => {
    const newMap: Record<string, string> = {}
    for (const col of columns) {
      const target = tmpl.mapping[col]
      if (target) newMap[col] = target
    }
    setMapping(newMap)
    setIgnoreSet(new Set(tmpl.ignore_columns ?? []))
    setSelectedTemplateId(tmpl.id)
    setSaveName(tmpl.name)
  }

  const inferredFields = inferredFieldSet(headersResult)
  const allRequiredMapped = [...REQUIRED_FIELDS]
    .filter(field => !inferredFields.has(field))
    .every(field => Object.values(mapping).includes(field))

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  useEffect(() => {
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [])

  const handleSaveTemplate = async () => {
    const name = saveName.trim()
    if (!name) {
      message.warning('请先填写模板名称')
      return
    }
    setSavingTemplate(true)
    try {
      const selected = templates.find(t => t.id === selectedTemplateId)
      const existingByName = templates.find(t => t.name === name && t.is_builtin === 0)
      const target = selected && selected.is_builtin === 0 ? selected : existingByName
      if (!target && templates.some(t => t.name === name)) {
        message.warning('模板名称已存在，请换一个名称')
        return
      }
      let templateId: number
      if (target) {
        const res = await updateUploadTemplate(target.id, {
          name,
          platform: target.platform,
          mapping,
          ignore_columns: [...ignoreSet],
        })
        templateId = (res.data as { id: number }).id
      } else {
        const res = await createUploadTemplate({
          name,
          platform: null,
          mapping,
          ignore_columns: [...ignoreSet],
        })
        templateId = (res.data as { id: number }).id
      }
      message.success('模板已保存，已设为批量入库模板')
      onTemplateSaved?.({
        id: templateId,
        name,
        platform: target?.platform ?? null,
        col_fingerprint: null,
        mapping,
        ignore_columns: [...ignoreSet],
        is_builtin: 0,
        updated_at: null,
      })
      onCancel()
    } finally {
      setSavingTemplate(false)
    }
  }

  const handleConfirm = async () => {
    if (pollRef.current) return
    if (!allRequiredMapped) {
      message.warning('还有必填字段未完成映射')
      return
    }
    setConfirming(true)
    setUploadProgress(0)
    setUploadError('')
    setCurrentJob(null)
    setUploadProgressVisible(true)
    try {
      const res = await confirmUpload({
        temp_file_id,
        mapping,
        ignore_columns: [...ignoreSet],
        save_template_name: saveSwitch && saveName ? saveName : undefined,
        template_id: selectedTemplateId,
        country_code: countryCode,
        data_year: dataYear,
      })
      const { job_id } = res.data as { job_id: number }

      let pollFailCount = 0
      pollRef.current = setInterval(async () => {
        try {
          const jobRes = await getUploadConfirmJob(job_id)
          const job = jobRes.data
          setCurrentJob(job)
          const { status, progress, error_msg } = job
          pollFailCount = 0  // reset on success
          setUploadProgress(progress)
          if (status === 'done') {
            stopPoll()
            setUploadProgress(100)
            onJobUpdate?.()
            setTimeout(() => {
              setUploadProgressVisible(false)
              setConfirming(false)
              onSuccess(job as Record<string, unknown>)
            }, 600)
          } else if (status === 'error') {
            stopPoll()
            onJobUpdate?.()
            setUploadError(error_msg || '处理失败，请重试')
            setConfirming(false)
          }
        } catch {
          pollFailCount++
          if (pollFailCount >= 10) {
            stopPoll()
            setUploadError('网络异常，请刷新后重试')
            setConfirming(false)
          }
        }
      }, 1000)
    } catch {
      setUploadProgressVisible(false)
      setConfirming(false)
    }
  }

  const mappingTableCols = [
    {
      title: '原始列名',
      dataIndex: 'col',
      width: 200,
      render: (col: string) => (
        <Text strong={!!(mapping[col] && REQUIRED_FIELDS.has(mapping[col]))}>{col}</Text>
      ),
    },
    {
      title: '映射到',
      dataIndex: 'col',
      key: 'target',
      render: (col: string) => {
        const isIgnored = ignoreSet.has(col)
        const val = mapping[col]
        return (
          <Select
            value={isIgnored ? undefined : val}
            placeholder={isIgnored ? '（已忽略）' : '请选择…'}
            disabled={isIgnored}
            style={{ width: '100%' }}
            allowClear
            onChange={(v: string) => setMapping(prev => ({ ...prev, [col]: v }))}
            showSearch
            filterOption={(input, opt) =>
              String(opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
            }
            status={!isIgnored && !val ? 'error' : undefined}
          >
            {STANDARD_FIELD_OPTIONS.map(o => (
              <Option key={o.value} value={o.value} label={o.label}>
                <span style={{ color: o.required ? '#cf1322' : undefined }}>
                  {o.required ? '✦ ' : ''}{o.label}
                </span>
              </Option>
            ))}
          </Select>
        )
      },
    },
    {
      title: '忽略',
      dataIndex: 'col',
      key: 'ignore',
      width: 70,
      render: (col: string) => (
        <Checkbox
          checked={ignoreSet.has(col)}
          onChange={e => {
            const next = new Set(ignoreSet)
            if (e.target.checked) {
              next.add(col)
              setMapping(prev => {
                const m = { ...prev }
                delete m[col]
                return m
              })
            } else {
              next.delete(col)
            }
            setIgnoreSet(next)
          }}
        />
      ),
    },
  ]

  return (
    <>
      <Card
        title={
          <Space>
            <span>列映射确认：{filename}</span>
            {match_score < 70 && (
              <Tag color="warning">未找到高度匹配的模板，请仔细核对映射</Tag>
            )}
          </Space>
        }
        extra={
          <Space>
            <Text type="secondary">切换模板：</Text>
            <Select
              value={selectedTemplateId}
              style={{ width: 200 }}
              allowClear
              placeholder="选择已有模板…"
              onChange={(id: number) => {
                const tmpl = templates.find(t => t.id === id)
                if (tmpl) applyTemplate(tmpl)
              }}
            >
              {templates.map(t => (
                <Option key={t.id} value={t.id}>
                  {t.is_builtin ? '★ ' : ''}{t.name}
                </Option>
              ))}
            </Select>
          </Space>
        }
      >
        <Table
          dataSource={columns.map(col => ({ col }))}
          columns={mappingTableCols}
          rowKey="col"
          size="small"
          pagination={false}
          scroll={{ y: 400 }}
        />

        <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
          <Switch checked={saveSwitch} onChange={setSaveSwitch} />
          <Text>保存为模板</Text>
          {saveSwitch && (
            <Input
              value={saveName}
              onChange={e => setSaveName(e.target.value)}
              placeholder="模板名称"
              style={{ width: 200 }}
            />
          )}
          <div style={{ marginLeft: 'auto' }}>
            <Space>
              <Button onClick={handleSaveTemplate} loading={savingTemplate} disabled={!saveName.trim()}>
                保存模板并返回
              </Button>
              <Button onClick={onCancel}>取消</Button>
              <Button
                type="primary"
                onClick={handleConfirm}
                loading={confirming}
                disabled={!allRequiredMapped}
              >
                确认入库
              </Button>
            </Space>
          </div>
        </div>
      </Card>
      <ProgressModal
        visible={uploadProgressVisible}
        title="正在处理文件..."
        progress={uploadProgress}
        errorMsg={uploadError}
        stageLabel={currentJob?.stage_label}
        totalRows={currentJob?.total_rows}
        processedRows={currentJob?.processed_rows}
        insertedRows={currentJob?.inserted_rows}
        skippedRows={currentJob?.skipped_rows}
      />
    </>
  )
}

// ─── TemplatesTab ─────────────────────────────────────────────
function TemplatesTab({
  templates,
  loading,
  refresh,
}: {
  templates: TemplateRow[]
  loading: boolean
  refresh: () => void
}) {
  const [editTarget, setEditTarget] = useState<TemplateRow | null>(null)
  const [editMapping, setEditMapping] = useState<Record<string, string>>({})
  const [editIgnore, setEditIgnore] = useState<string[]>([])
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)

  const openEdit = (t: TemplateRow) => {
    setEditTarget(t)
    setEditMapping({ ...t.mapping })
    setEditIgnore(t.ignore_columns ?? [])
    form.setFieldsValue({ name: t.name, platform: t.platform })
  }

  const handleSave = async () => {
    const values = await form.validateFields()
    if (!editTarget) return
    setSaving(true)
    try {
      await updateUploadTemplate(editTarget.id, {
        name: values.name,
        platform: values.platform ?? null,
        mapping: editMapping,
        ignore_columns: editIgnore,
      })
      message.success('模板已保存')
      setEditTarget(null)
      refresh()
    } catch {
      // handled by interceptor
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteUploadTemplate(id)
      message.success('已删除')
      refresh()
    } catch {
      // handled
    }
  }

  const cols = [
    { title: '模板名', dataIndex: 'name', ellipsis: true },
    {
      title: '平台', dataIndex: 'platform', width: 100,
      render: (v: string) =>
        v ? <Tag>{PLATFORM_LABEL[v] ?? v}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: '列数', dataIndex: 'mapping', width: 70,
      render: (m: Record<string, string>) => Object.keys(m).length,
    },
    {
      title: '内置', dataIndex: 'is_builtin', width: 70,
      render: (v: number) => v ? <Tag color="purple">内置</Tag> : null,
    },
    {
      title: '最后更新', dataIndex: 'updated_at', width: 170,
      render: (v: string) => v || '-',
    },
    {
      title: '操作', width: 120,
      render: (_: unknown, row: TemplateRow) => (
        <Space>
          <Button
            type="link"
            icon={<EditOutlined />}
            size="small"
            onClick={() => openEdit(row)}
          >
            编辑
          </Button>
          <Popconfirm
            title="确认删除该模板？"
            onConfirm={() => handleDelete(row.id)}
            okText="删除"
            cancelText="取消"
            disabled={!!row.is_builtin}
          >
            <Button type="link" danger size="small" disabled={!!row.is_builtin}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Table
        dataSource={templates}
        columns={cols}
        rowKey="id"
        size="small"
        loading={loading}
        pagination={false}
      />

      <Modal
        title={`编辑模板：${editTarget?.name}`}
        open={!!editTarget}
        onCancel={() => setEditTarget(null)}
        onOk={handleSave}
        confirmLoading={saving}
        width={700}
        okText="保存"
        cancelText="取消"
      >
        {editTarget && (
          <>
            <Form form={form} layout="inline" style={{ marginBottom: 16 }}>
              <Form.Item name="name" label="模板名" rules={[{ required: true }]}>
                <Input />
              </Form.Item>
              <Form.Item name="platform" label="平台">
                <Select allowClear style={{ width: 120 }} placeholder="不限">
                  <Option value="jd">京东</Option>
                  <Option value="tmall">天猫</Option>
                  <Option value="taobao">淘宝</Option>
                  <Option value="suning">苏宁</Option>
                  <Option value="amazon">亚马逊</Option>
                  <Option value="shopee">虾皮</Option>
                </Select>
              </Form.Item>
            </Form>
            <Table
              dataSource={Object.keys(editTarget.mapping).map(col => ({ col }))}
              rowKey="col"
              size="small"
              pagination={false}
              scroll={{ y: 320 }}
              columns={[
                { title: '原始列名', dataIndex: 'col', width: 200 },
                {
                  title: '映射到',
                  dataIndex: 'col',
                  key: 'target',
                  render: (col: string) => (
                    <Select
                      value={editMapping[col]}
                      style={{ width: '100%' }}
                      allowClear
                      onChange={(v: string) =>
                        setEditMapping(prev => ({ ...prev, [col]: v }))
                      }
                      showSearch
                    >
                      {STANDARD_FIELD_OPTIONS.map(o => (
                        <Option key={o.value} value={o.value}>{o.label}</Option>
                      ))}
                    </Select>
                  ),
                },
                {
                  title: '忽略',
                  dataIndex: 'col',
                  key: 'ignore',
                  width: 70,
                  render: (col: string) => (
                    <Checkbox
                      checked={editIgnore.includes(col)}
                      onChange={e => {
                        if (e.target.checked) {
                          setEditIgnore(prev => [...prev, col])
                        } else {
                          setEditIgnore(prev => prev.filter(c => c !== col))
                        }
                      }}
                    />
                  ),
                },
              ]}
            />
          </>
        )}
      </Modal>
    </>
  )
}

// ─── Main Upload Page ─────────────────────────────────────────
export default function UploadPage() {
  const [step, setStep] = useState<'upload' | 'mapping' | 'preview'>('upload')
  const [pendingFiles, setPendingFiles] = useState<PendingUploadFile[]>([])
  const [activeFileId, setActiveFileId] = useState<string | null>(null)
  const [batchCountry, setBatchCountry] = useState<string | undefined>(undefined)
  const [previewData, setPreviewData] = useState<Record<string, unknown>[]>([])
  const [previewInfo, setPreviewInfo] = useState<{
    filename: string
    row_count: number
    platform: string
    month_range: string
    inserted: number
    skipped: number
    country_code?: string
  } | null>(null)
  const [uploadingCount, setUploadingCount] = useState(0)
  const [batchConfirming, setBatchConfirming] = useState(false)
  const [batchModalOpen, setBatchModalOpen] = useState(false)
  const [namingHelpOpen, setNamingHelpOpen] = useState(false)
  const [batchItems, setBatchItems] = useState<BatchConfirmItem[]>([])
  const [bulkTemplateId, setBulkTemplateId] = useState<number | undefined>(undefined)
  const [activeJob, setActiveJob] = useState<UploadConfirmJobResponse | null>(null)
  const [jobProgressVisible, setJobProgressVisible] = useState(false)

  const [dataYear, setDataYear] = useState<number>(new Date().getFullYear())

  const [filterRegion, setFilterRegion] = useState<string | undefined>(undefined)
  const [filterYear, setFilterYear] = useState<number | undefined>(undefined)

  const { data: filesData, loading: filesLoading, run: runFilesQuery } = useRequest(
    (params?: { data_region?: string; data_year?: number }) =>
      listUploadFiles(params).then(r => r.data),
    { manual: true }
  )
  const historyRows = useMemo(
    () => groupUploadHistory(((filesData as UploadFileItem[] | undefined) ?? [])),
    [filesData]
  )
  const [batchDownloadingKey, setBatchDownloadingKey] = useState<string | null>(null)
  const [downloadJobsByFileId, setDownloadJobsByFileId] = useState<Record<number, UploadDownloadJob>>({})
  const downloadJobsPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const visibleUploadFileIds = ((filesData as { id: number }[] | undefined) ?? []).map(file => file.id)

  const refreshDownloadJobs = async () => {
    if (visibleUploadFileIds.length === 0) {
      setDownloadJobsByFileId({})
      return
    }
    const response = await listUploadDownloadJobs({ file_ids: visibleUploadFileIds })
    const next: Record<number, UploadDownloadJob> = {}
    response.data.forEach(job => {
      if (!(job.file_id in next)) next[job.file_id] = job
    })
    setDownloadJobsByFileId(next)
  }

  useEffect(() => {
    runFilesQuery({ data_region: filterRegion, data_year: filterYear })
  }, [filterRegion, filterYear])

  useEffect(() => {
    refreshDownloadJobs().catch(() => undefined)
    if (downloadJobsPollRef.current) clearInterval(downloadJobsPollRef.current)
    downloadJobsPollRef.current = setInterval(() => {
      refreshDownloadJobs().catch(() => undefined)
    }, 15000)
    return () => {
      if (downloadJobsPollRef.current) {
        clearInterval(downloadJobsPollRef.current)
        downloadJobsPollRef.current = null
      }
    }
  }, [visibleUploadFileIds.join(',')])

  const { data: templatesData, loading: templatesLoading, refresh: refreshTemplates } = useRequest(
    () => listUploadTemplates().then(r => r.data),
    { refreshDeps: [] }
  )

  const { data: countryOptionsData } = useRequest(
    () => listCountryOptions().then(r => r.data),
    { refreshDeps: [] }
  )
  const countryOptions: CountryOption[] = countryOptionsData ?? []
  const countryName = (code?: string) => {
    const item = countryOptions.find(option => option.code === code)
    return item ? `${item.name_cn}（${item.currency_code}）` : code || '-'
  }

  const { data: uploadJobsData, refresh: refreshUploadJobs } = useRequest(
    () => listUploadConfirmJobs({ limit: 20 }).then(r => r.data),
    { pollingInterval: 3000 }
  )

  const templates: TemplateRow[] = (templatesData as TemplateRow[] | undefined) ?? []
  const uploadJobs: UploadConfirmJobResponse[] = (uploadJobsData ?? []).filter(job => (
    Boolean(job.filename) && ['pending', 'running', 'error'].includes(job.status)
  ))

  useEffect(() => {
    if (!activeJob) return
    const latest = uploadJobs.find(job => job.job_id === activeJob.job_id)
    if (latest) setActiveJob(latest)
  }, [uploadJobsData, activeJob?.job_id])

  const updateBatchItem = (uid: string, patch: Partial<BatchConfirmItem>) => {
    setBatchItems(prev => prev.map(item => item.uid === uid ? { ...item, ...patch } : item))
  }

  const waitForConfirmJob = async (jobId: number, uid: string) => {
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      const job = (await getUploadConfirmJob(jobId)).data
      updateBatchItem(uid, { progress: job.progress ?? 0, message: job.stage_label ?? undefined })
      if (job.status === 'done') return { ok: true as const, job }
      if (job.status === 'error' || job.status === 'cancelled') {
        return { ok: false as const, error: job.error_msg || '处理失败' }
      }
    }
  }

  const handleBatchConfirm = async () => {
    const readyFiles = pendingFiles.filter(item => item.status === 'ready' && item.headersResult)
    if (readyFiles.length === 0) {
      message.warning('没有可批量入库的文件')
      return
    }
    const missingCountry = readyFiles.filter(item => !item.countryCode)
    if (missingCountry.length > 0) {
      message.warning(`请先为 ${missingCountry.length} 个文件选择国家`)
      return
    }
    const items: BatchConfirmItem[] = readyFiles.map(item => ({
      uid: item.uid,
      filename: item.filename,
      status: 'pending',
      progress: 0,
      message: '等待处理',
    }))
    const batchKey = `batch-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
    setBatchItems(items)
    setBatchModalOpen(true)
    setBatchConfirming(true)
    let successCount = 0
    let failedCount = 0

    try {
      for (const item of readyFiles) {
        const headers = item.headersResult!
        const selectedTemplate = item.templateOverride ?? templates.find(template => template.id === item.templateId)
        let auto = buildAutoMapping(headers, selectedTemplate)
        if (auto.missing.length > 0 && selectedTemplate && headers.suggested_template) {
          const fallback = buildAutoMapping(headers, null)
          if (fallback.missing.length === 0) auto = fallback
        }
        if (auto.missing.length > 0) {
          failedCount += 1
          updateBatchItem(item.uid, {
            status: 'error',
            progress: 100,
            message: `缺少必填字段：${auto.missing.join(', ')}，请手动映射`,
          })
          continue
        }
        updateBatchItem(item.uid, { status: 'running', progress: 0, message: '正在提交' })
        try {
          const res = await confirmUpload({
            temp_file_id: headers.temp_file_id,
            mapping: auto.mapping,
            ignore_columns: auto.ignoreColumns,
            template_id: selectedTemplate?.id ?? headers.suggested_template?.id,
            country_code: item.countryCode,
            batch_key: batchKey,
            data_year: dataYear,
          })
          const { job_id } = res.data as { job_id: number }
          const result = await waitForConfirmJob(job_id, item.uid)
          if (!result.ok) {
            failedCount += 1
            updateBatchItem(item.uid, { status: 'error', progress: 100, message: result.error })
            continue
          }
          successCount += 1
          updateBatchItem(item.uid, { status: 'done', progress: 100, message: '已完成' })
          setPendingFiles(prev => prev.filter(file => file.uid !== item.uid))
        } catch (error) {
          failedCount += 1
          const detail = (error as { response?: { data?: { detail?: string; message?: string } } })?.response?.data
          updateBatchItem(item.uid, {
            status: 'error',
            progress: 100,
            message: detail?.detail || detail?.message || (error instanceof Error ? error.message : '处理失败'),
          })
        }
      }
    } finally {
      setBatchConfirming(false)
      runFilesQuery({ data_region: filterRegion, data_year: filterYear })
      refreshTemplates()
      refreshUploadJobs()
    }

    if (failedCount === 0) {
      message.success(`批量入库完成，共 ${successCount} 个文件`)
    } else {
      message.warning(`批量入库完成：成功 ${successCount} 个，失败 ${failedCount} 个`)
    }
  }

  const handleDownloadSample = async () => {
    const res = await downloadUploadSample()
    const blob = new Blob([res.data], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '数据上传示例.xlsx'
    link.click()
    URL.revokeObjectURL(url)
  }

  const handleAddFile = async (file: File) => {
    const uid = `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2)}`
    setPendingFiles(prev => [...prev, { uid, filename: file.name, status: 'uploading' }])
    setUploadingCount(count => count + 1)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await getUploadHeaders(formData)
      setPendingFiles(prev => prev.map(item => item.uid === uid
        ? {
            ...item,
            status: 'ready',
            headersResult: res.data as HeadersResult,
            templateId: (res.data as HeadersResult).suggested_template?.id,
            filenameHints: (res.data as HeadersResult).filename_hints,
            countryCode: (res.data as HeadersResult).filename_hints?.country_code ?? item.countryCode,
          }
        : item))
    } catch {
      setPendingFiles(prev => prev.map(item => item.uid === uid
        ? { ...item, status: 'error', error: '表头读取失败' }
        : item))
    } finally {
      setUploadingCount(count => Math.max(0, count - 1))
    }
    return false
  }

  const updatePendingCountry = (uid: string, countryCode: string) => {
    setPendingFiles(prev => prev.map(item => item.uid === uid ? { ...item, countryCode } : item))
  }

  const updatePendingTemplate = (uid: string, templateId?: number) => {
    const template = templateId ? templates.find(item => item.id === templateId) : undefined
    setPendingFiles(prev => prev.map(item => item.uid === uid
      ? { ...item, templateId, templateOverride: template }
      : item))
  }

  const applyBulkTemplate = () => {
    if (!bulkTemplateId) return
    const template = templates.find(item => item.id === bulkTemplateId)
    setPendingFiles(prev => prev.map(item => item.status === 'ready'
      ? { ...item, templateId: bulkTemplateId, templateOverride: template }
      : item))
  }

  const applyBatchCountry = () => {
    if (!batchCountry) return
    setPendingFiles(prev => prev.map(item => item.status === 'ready' ? { ...item, countryCode: batchCountry } : item))
  }

  const removePendingFile = (uid: string) => {
    setPendingFiles(prev => prev.filter(item => item.uid !== uid))
    if (activeFileId === uid) {
      setActiveFileId(null)
      setStep('upload')
    }
  }

  const activeFile = pendingFiles.find(item => item.uid === activeFileId)

  const handleMappingSuccess = (result: Record<string, unknown>) => {
    const preview = result.preview as Record<string, unknown>[]
    setPreviewData(preview)
    setPreviewInfo({
      filename: String(result.filename),
      row_count: Number(result.row_count),
      platform: String(result.platform),
      month_range: String(result.month_range),
      inserted: Number(result.inserted ?? result.row_count),
      skipped: Number(result.skipped ?? 0),
      country_code: result.country_code as string | undefined,
    })
    if (activeFileId) {
      setPendingFiles(prev => prev.filter(item => item.uid !== activeFileId))
    }
    setActiveFileId(null)
    setStep('preview')
    runFilesQuery({ data_region: filterRegion, data_year: filterYear })
    refreshTemplates()
    refreshUploadJobs()
  }

  const previewColumns = [
    { title: '平台', dataIndex: 'platform', width: 100, ellipsis: true, render: renderVal },
    { title: '月份', dataIndex: 'month', width: 90, render: renderVal },
    { title: '品牌', dataIndex: 'brand_std', width: 100, render: renderVal },
    { title: '机型', dataIndex: 'model_std', width: 120, render: renderVal },
    { title: '宝贝名称', dataIndex: 'item_name', ellipsis: true, render: renderVal },
    { title: '销量', dataIndex: 'sales_qty', width: 80, render: renderVal },
    {
      title: '销售额', dataIndex: 'sales_amount', width: 110,
      render: (v: number) =>
        v != null ? `¥${Number(v).toLocaleString()}` : <Text type="secondary">-</Text>,
    },
    {
      title: '价格', dataIndex: 'price', width: 90,
      render: (v: number) =>
        v != null ? `¥${Number(v).toFixed(2)}` : <Text type="secondary">-</Text>,
    },
  ]

  const handleBatchDownload = async (batchKey: string) => {
    setBatchDownloadingKey(batchKey)
    try {
      const res = await downloadUploadBatch(batchKey)
      const blob = new Blob([res.data], { type: 'application/zip' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `批量上传_${batchKey.slice(0, 8)}.zip`
      link.click()
      URL.revokeObjectURL(url)
    } finally {
      setBatchDownloadingKey(null)
    }
  }

  const handleBatchDelete = async (batchKey: string) => {
    await deleteUploadBatch(batchKey)
    message.success('整批已删除')
    runFilesQuery({ data_region: filterRegion, data_year: filterYear })
  }

  const handleDelete = async (id: number) => {
    try {
      await deleteUploadFile(id)
      message.success('已删除')
      runFilesQuery({ data_region: filterRegion, data_year: filterYear })
    } catch {
      // handled
    }
  }

  const startDownloadJob = async (id: number) => {
    try {
      const response = await createUploadDownloadJob(id)
      setDownloadJobsByFileId(prev => ({ ...prev, [response.data.file_id]: response.data }))
      refreshDownloadJobs().catch(() => undefined)
    } catch {
      // handled by API interceptor
    }
  }

  const handleCancelJob = async (jobId: number) => {
    await cancelUploadConfirmJob(jobId)
    message.success('已取消任务')
    refreshUploadJobs()
  }

  const handleDeleteJob = async (jobId: number) => {
    await deleteUploadConfirmJob(jobId)
    message.success('已删除任务')
    if (activeJob?.job_id === jobId) {
      setActiveJob(null)
      setJobProgressVisible(false)
    }
    refreshUploadJobs()
  }

  const Dragger = Upload.Dragger

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* Step 1: Upload zone */}
      {step === 'upload' && (
        <Card>
          <Dragger
            accept=".xlsx,.xls,.csv"
            multiple
            beforeUpload={handleAddFile}
            showUploadList={false}
            disabled={uploadingCount > 0}
          >
            <p className="ant-upload-drag-icon">
              {uploadingCount > 0 ? <Spin /> : <InboxOutlined />}
            </p>
            <p className="ant-upload-text">
              {uploadingCount > 0 ? '正在读取文件表头…' : '点击或拖拽多个 Excel / CSV 文件至此上传'}
            </p>
            <p className="ant-upload-hint">
              支持一次选择多个文件；文件读取完成后，在下方逐个选择国家
            </p>
          </Dragger>
          <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
            <Space>
              <Button icon={<QuestionCircleOutlined />} onClick={() => setNamingHelpOpen(true)}>
                文件名命名说明
              </Button>
              <Button icon={<DownloadOutlined />} onClick={handleDownloadSample}>
                下载示例 Excel
              </Button>
            </Space>
          </div>
          {countryOptions.length === 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 12 }}
              message="尚未配置国家，请联系 master 在「国家与汇率」页面先添加国家。"
            />
          )}
        </Card>
      )}

      {step === 'upload' && pendingFiles.length > 0 && (
        <Card
          title="待处理文件"
          size="small"
          extra={
            <Space wrap>
              <Text type="secondary">批量设置国家</Text>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="选择国家"
                style={{ width: 200 }}
                value={batchCountry}
                onChange={setBatchCountry}
                options={countryOptions.map(option => ({
                  value: option.code,
                  label: `${option.name_cn}（${option.currency_code}）`,
                }))}
              />
              <Button onClick={applyBatchCountry} disabled={!batchCountry}>应用到未入库文件</Button>
              <Text type="secondary">批量设置模板</Text>
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="可选"
                style={{ width: 200 }}
                value={bulkTemplateId}
                onChange={setBulkTemplateId}
                options={templates.map(template => ({
                  value: template.id,
                  label: `${template.is_builtin ? '★ ' : ''}${template.name}`,
                }))}
              />
              <Button onClick={applyBulkTemplate} disabled={!bulkTemplateId}>应用模板到未入库文件</Button>
              <Button
                type="primary"
                loading={batchConfirming}
                onClick={handleBatchConfirm}
                disabled={!pendingFiles.some(item => item.status === 'ready' && item.headersResult)}
              >
                批量确认入库
              </Button>
            </Space>
          }
        >
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message="批量确认会使用推荐模板或标准列名自动映射；标记为「需手动」的文件请点「配置映射」处理。"
          />
          <Table<PendingUploadFile>
            rowKey="uid"
            size="small"
            dataSource={pendingFiles}
            pagination={false}
            columns={[
              { title: '文件名', dataIndex: 'filename', ellipsis: true },
              {
                title: '推荐模板', width: 180, ellipsis: true,
                render: (_: unknown, row) => row.headersResult?.suggested_template?.name || '-',
              },
              {
                title: '列数', width: 70,
                render: (_: unknown, row) => row.headersResult?.columns.length ?? '-',
              },
              {
                title: '模板', width: 220,
                render: (_: unknown, row) => (
                  <Select
                    allowClear
                    showSearch
                    optionFilterProp="label"
                    placeholder="自动/推荐"
                    style={{ width: '100%' }}
                    value={row.templateId}
                    onChange={value => updatePendingTemplate(row.uid, value)}
                    options={templates.map(template => ({
                      value: template.id,
                      label: `${template.is_builtin ? '★ ' : ''}${template.name}`,
                    }))}
                  />
                ),
              },
              {
                title: '自动映射', width: 110,
                render: (_: unknown, row) => {
                  if (!row.headersResult) return '-'
                  const selectedTemplate = row.templateOverride ?? templates.find(template => template.id === row.templateId)
                  const auto = buildAutoMapping(row.headersResult, selectedTemplate)
                  return auto.missing.length === 0
                    ? <Tag color="green">可批量</Tag>
                    : <Tag color="orange">需手动</Tag>
                },
              },
              {
                title: '识别月份', width: 100,
                render: (_: unknown, row) => {
                  const hints = row.filenameHints
                  if (hints?.month_ambiguous) return <Tag color="orange">歧义</Tag>
                  return hints?.month != null ? <Tag color="green">{hints.month}</Tag> : <Tag>需映射</Tag>
                },
              },
              {
                title: '识别平台', width: 110,
                render: (_: unknown, row) => {
                  const hints = row.filenameHints
                  if (hints?.platform_ambiguous) return <Tag color="orange">歧义</Tag>
                  return hints?.platform
                    ? <Tag color="green">{PLATFORM_LABEL[hints.platform] ?? hints.platform}</Tag>
                    : <Tag>需映射</Tag>
                },
              },
              {
                title: '识别品类', width: 150,
                render: (_: unknown, row) => {
                  const hints = row.filenameHints
                  if (hints?.category_ambiguous) return <Tag color="orange">歧义</Tag>
                  const label = hints?.category_name || hints?.category_code
                  return label ? <Tag color="green">{label}</Tag> : <Tag>未识别</Tag>
                },
              },
              {
                title: '国家', width: 220,
                render: (_: unknown, row) => (
                  <Space direction="vertical" size={2} style={{ width: '100%' }}>
                    <Select
                      showSearch
                      optionFilterProp="label"
                      placeholder="请选择国家"
                      style={{ width: '100%' }}
                      value={row.countryCode}
                      onChange={value => updatePendingCountry(row.uid, value)}
                      options={countryOptions.map(option => ({
                        value: option.code,
                        label: `${option.name_cn}（${option.currency_code}）`,
                      }))}
                    />
                    {row.filenameHints?.country_ambiguous && (
                      <Tag color="orange">文件名国家有歧义</Tag>
                    )}
                  </Space>
                ),
              },
              {
                title: '状态', width: 100,
                render: (_: unknown, row) => row.status === 'uploading'
                  ? <Tag color="processing">读取中</Tag>
                  : row.status === 'error'
                    ? <Tag color="red">{row.error || '失败'}</Tag>
                    : <Tag color="green">待入库</Tag>,
              },
              {
                title: '操作', width: 160,
                render: (_: unknown, row) => (
                  <Space size={4}>
                    <Button
                      type="link"
                      size="small"
                      disabled={row.status !== 'ready' || !row.countryCode}
                      onClick={() => { setActiveFileId(row.uid); setStep('mapping') }}
                    >
                      配置映射
                    </Button>
                    <Button type="link" size="small" danger onClick={() => removePendingFile(row.uid)}>
                      移除
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}

      {uploadJobs.length > 0 && (
        <Card title="上传处理任务" size="small">
          <Table<UploadConfirmJobResponse>
            rowKey="job_id"
            size="small"
            dataSource={uploadJobs}
            pagination={false}
            columns={[
              { title: '文件名', dataIndex: 'filename', ellipsis: true, render: (v: string | null) => v || '-' },
              { title: '状态', dataIndex: 'status', width: 90, render: uploadJobStatusTag },
              { title: '阶段', dataIndex: 'stage_label', width: 130, render: (v: string | null) => v || '-' },
              {
                title: '进度',
                dataIndex: 'progress',
                width: 160,
                render: (v: number) => (
                  <Progress percent={v ?? 0} size="small" status={v >= 100 ? 'success' : 'active'} />
                ),
              },
              {
                title: '处理行数',
                width: 130,
                render: (_: unknown, row) => (
                  row.total_rows != null
                    ? `${row.processed_rows ?? 0} / ${row.total_rows}`
                    : row.processed_rows != null ? `${row.processed_rows}` : '-'
                ),
              },
              {
                title: '插入/跳过',
                width: 120,
                render: (_: unknown, row) => (
                  row.inserted_rows != null || row.skipped_rows != null
                    ? `${row.inserted_rows ?? 0} / ${row.skipped_rows ?? 0}`
                    : '-'
                ),
              },
              {
                title: '操作',
                width: 140,
                render: (_: unknown, row) => (
                  <Space size={4}>
                    <Button
                      type="link"
                      size="small"
                      onClick={() => { setActiveJob(row); setJobProgressVisible(true) }}
                    >
                      查看进度
                    </Button>
                    {['pending', 'running'].includes(row.status) && (
                      <Popconfirm
                        title="确认取消该上传处理任务？"
                        description="取消后需要重新上传文件。"
                        onConfirm={() => handleCancelJob(row.job_id)}
                      >
                        <Button type="link" size="small" danger>取消</Button>
                      </Popconfirm>
                    )}
                    {['error', 'cancelled'].includes(row.status) && (
                      <Popconfirm
                        title="确认删除该上传处理任务？"
                        description="删除后该任务记录将不再显示。"
                        onConfirm={() => handleDeleteJob(row.job_id)}
                      >
                        <Button type="link" size="small" danger>删除</Button>
                      </Popconfirm>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        </Card>
      )}

      {/* Step 2: Mapping confirmation */}
      {step === 'mapping' && activeFile?.headersResult && (
        <>
          <Card style={{ marginBottom: 12 }}>
            <Space size="large">
              <span style={{ fontWeight: 500 }}>数据维度</span>
              <Tag color="blue">国家：{countryName(activeFile.countryCode)}</Tag>
              {activeFile.filenameHints?.month != null && (
                <Tag color="green">识别月份：{activeFile.filenameHints.month}</Tag>
              )}
              {activeFile.filenameHints?.platform && (
                <Tag color="green">识别平台：{PLATFORM_LABEL[activeFile.filenameHints.platform] ?? activeFile.filenameHints.platform}</Tag>
              )}
              {(activeFile.filenameHints?.category_name || activeFile.filenameHints?.category_code) && (
                <Tag color="green">识别品类：{activeFile.filenameHints.category_name || activeFile.filenameHints.category_code}</Tag>
              )}
              {(activeFile.filenameHints?.month_ambiguous || activeFile.filenameHints?.platform_ambiguous || activeFile.filenameHints?.category_ambiguous) && (
                <Tag color="orange">文件名有歧义，请手动映射</Tag>
              )}
              <InputNumber
                placeholder="年份"
                value={dataYear}
                onChange={(v) => v !== null && v !== undefined && setDataYear(v)}
                min={2020}
                max={2099}
                style={{ width: 100 }}
              />
            </Space>
          </Card>
          <MappingCard
            headersResult={activeFile.headersResult}
            templates={templates}
            onSuccess={handleMappingSuccess}
            onCancel={() => setStep('upload')}
            countryCode={activeFile.countryCode}
            dataYear={dataYear}
            onJobUpdate={refreshUploadJobs}
            onTemplateSaved={(template) => {
              if (activeFileId) {
                setPendingFiles(prev => prev.map(item => item.uid === activeFileId
                  ? { ...item, templateId: template.id, templateOverride: template }
                  : item))
              }
              refreshTemplates()
            }}
          />
        </>
      )}

      {/* Step 3: Ingestion preview */}
      {step === 'preview' && previewInfo && (
        <Card
          title={
            <Space>
              <CheckCircleOutlined style={{ color: '#52c41a' }} />
              {`数据预览：${previewInfo.filename}`}
            </Space>
          }
          extra={
            <Space>
              <Tag color="blue">{PLATFORM_LABEL[previewInfo.platform] ?? previewInfo.platform}</Tag>
              <Tag color="purple">{countryName(previewInfo.country_code)}</Tag>
              <Tag color="geekblue">{previewInfo.month_range}</Tag>
              <Text type="secondary">共 {previewInfo.row_count} 条，展示前 50 行</Text>
              <Button onClick={() => setStep('upload')}>继续上传</Button>
            </Space>
          }
        >
          <Alert
            type="info"
            showIcon
            message={`文件已成功入库，写入 ${previewInfo.inserted} 条数据${previewInfo.skipped > 0 ? `，跳过重复 ${previewInfo.skipped} 条` : ''}。`}
            style={{ marginBottom: 12 }}
          />
          <Table
            dataSource={previewData}
            columns={previewColumns}
            rowKey={(_r, i) => String(i)}
            size="small"
            scroll={{ x: 900 }}
            pagination={false}
          />
        </Card>
      )}

      {/* History + Templates tabs */}
      <Card>
        <Tabs
          defaultActiveKey="history"
          tabBarExtraContent={
            <Button
              icon={<ReloadOutlined />}
              onClick={() => { runFilesQuery({ data_region: filterRegion, data_year: filterYear }); refreshTemplates(); refreshUploadJobs() }}
            >
              刷新
            </Button>
          }
          items={[
            {
              key: 'history',
              label: '上传历史',
              children: (
                <>
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Select
                      placeholder="国内 / 海外"
                      value={filterRegion}
                      onChange={setFilterRegion}
                      style={{ width: 120 }}
                      options={[
                        { value: 'domestic', label: '国内' },
                        { value: 'overseas', label: '海外' },
                      ]}
                      allowClear
                    />
                    <InputNumber
                      placeholder="年份"
                      value={filterYear}
                      onChange={(v) => setFilterYear(v ?? undefined)}
                      min={2020}
                      max={2099}
                      style={{ width: 100 }}
                    />
                    <Button onClick={() => { setFilterRegion(undefined); setFilterYear(undefined) }}>
                      重置
                    </Button>
                  </Space>
                  <Table
                    dataSource={historyRows}
                    columns={historyColumns(
                      handleDelete,
                      startDownloadJob,
                      downloadJobsByFileId,
                      handleBatchDownload,
                      handleBatchDelete,
                      batchDownloadingKey,
                    )}
                    rowKey={(row) => row.is_batch ? `batch-${row.batch_key}` : `file-${row.id}`}
                    size="small"
                    loading={filesLoading}
                    pagination={{ pageSize: 10 }}
                    scroll={{ x: 1200 }}
                  />
                </>
              ),
            },
            {
              key: 'templates',
              label: '列模板',
              children: (
                <TemplatesTab
                  templates={templates}
                  loading={templatesLoading}
                  refresh={refreshTemplates}
                />
              ),
            },
          ]}
        />
      </Card>

      <ProgressModal
        visible={jobProgressVisible}
        title={`上传任务：${activeJob?.filename ?? ''}`}
        progress={activeJob?.progress ?? 0}
        errorMsg={activeJob?.error_msg ?? undefined}
        stageLabel={activeJob?.stage_label}
        totalRows={activeJob?.total_rows}
        processedRows={activeJob?.processed_rows}
        insertedRows={activeJob?.inserted_rows}
        skippedRows={activeJob?.skipped_rows}
        onClose={() => setJobProgressVisible(false)}
      />

      <Modal
        title="文件名命名说明"
        open={namingHelpOpen}
        onCancel={() => setNamingHelpOpen(false)}
        footer={<Button onClick={() => setNamingHelpOpen(false)}>知道了</Button>}
        width={720}
      >
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="文件名可以自动识别月份、平台、国家、品类；识别不到时仍可在列映射中手动指定。"
          />
          <div>
            <Text strong>格式一：品类写在最后</Text>
            <div><Text code>YYYYMM_平台_国家_品类.xlsx</Text></div>
            <Text type="secondary">示例：202609_amazon_US_运动相机.xlsx</Text>
          </div>
          <div>
            <Text strong>格式二：带描述时用品类方括号</Text>
            <div><Text code>YYYYMM_平台_国家_[品类]_描述.xlsx</Text></div>
            <Text type="secondary">示例：202609_amazon_US_[运动相机]_Fryers.xlsx</Text>
          </div>
          <div>
            <Text strong>平台</Text>
            <div>amazon / amz / 亚马逊；shopee / 虾皮 / 西皮</div>
          </div>
          <div>
            <Text strong>国家</Text>
            <div>ISO 国家码或中文名，如 US、美国、MX、墨西哥；必须是「国家与汇率」里已启用的国家。</div>
          </div>
          <div>
            <Text strong>月份</Text>
            <div>202609 或 2026-09。</div>
          </div>
          <div>
            <Text strong>品类</Text>
            <div>中文名或品类码都可以，如 运动相机、action_cameras；多个方括号或匹配不到时视为未识别。</div>
          </div>
          <Alert
            type="warning"
            showIcon
            message="文件名识别出的月份、平台会覆盖 Excel 中的同名字段。文件名中出现多个候选值时视为歧义，不会自动识别，需要在列映射中手动指定。"
          />
        </Space>
      </Modal>

      <Modal
        title="批量确认入库"
        open={batchModalOpen}
        onCancel={() => { if (!batchConfirming) setBatchModalOpen(false) }}
        footer={batchConfirming ? null : <Button onClick={() => setBatchModalOpen(false)}>关闭</Button>}
        closable={!batchConfirming}
        maskClosable={false}
        width={760}
      >
        <Table<BatchConfirmItem>
          rowKey="uid"
          size="small"
          dataSource={batchItems}
          pagination={false}
          columns={[
            { title: '文件名', dataIndex: 'filename', ellipsis: true },
            {
              title: '状态', dataIndex: 'status', width: 90,
              render: (status: BatchConfirmItem['status']) => {
                if (status === 'done') return <Tag color="green">完成</Tag>
                if (status === 'error') return <Tag color="red">失败</Tag>
                if (status === 'running') return <Tag color="processing">处理中</Tag>
                return <Tag>等待</Tag>
              },
            },
            {
              title: '进度', dataIndex: 'progress', width: 160,
              render: (value: number) => <Progress percent={value} size="small" status={value >= 100 ? 'normal' : 'active'} />,
            },
            { title: '说明', dataIndex: 'message', ellipsis: true, render: (value?: string) => value || '-' },
          ]}
        />
      </Modal>
    </Space>
  )
}
