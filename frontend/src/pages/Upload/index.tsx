import { useState, useRef, useEffect } from 'react'
import {
  Card, Upload, Table, Tag, Button, Popconfirm, Select, Checkbox,
  message, Space, Typography, Spin, Alert, Tabs, Switch, Input,
  Modal, Form, InputNumber, Progress,
} from 'antd'
import {
  InboxOutlined, DeleteOutlined, ReloadOutlined,
  CheckCircleOutlined, EditOutlined, DownloadOutlined,
} from '@ant-design/icons'
import { useRequest } from 'ahooks'
import {
  getUploadHeaders, confirmUpload,
  listUploadFiles, deleteUploadFile,
  createUploadDownloadJob, listUploadDownloadJobs, getUploadDownloadJobUrl,
  listUploadTemplates,
  updateUploadTemplate, deleteUploadTemplate,
  getUploadConfirmJob, listUploadConfirmJobs, cancelUploadConfirmJob, deleteUploadConfirmJob,
  type UploadConfirmJobResponse,
  type UploadDownloadJob,
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
  jd: '京东', tmall: '天猫', taobao: '淘宝', suning: '苏宁',
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

// ─── Upload history table columns ────────────────────────────
const historyColumns = (
  onDelete: (id: number) => void,
  startDownloadJob: (id: number) => void,
  downloadJobsByFileId: Record<number, UploadDownloadJob>,
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
    title: '年份',
    dataIndex: 'data_year',
    width: 70,
    render: (v: number | null) => v ?? '—',
  },
  { title: '数据量', dataIndex: 'row_count', width: 80 },
  {
    title: '状态', dataIndex: 'status', width: 80,
    render: (v: string) => (
      <Tag color={v === 'done' ? 'green' : 'orange'}>{v === 'done' ? '已完成' : v}</Tag>
    ),
  },
  {
    title: '上传时间', dataIndex: 'uploaded_at', width: 170,
    render: (v: string) => v || '—',
  },
  {
    title: '下载状态',
    width: 180,
    render: (_: unknown, row: { id: number }) => {
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
    render: (_: unknown, row: { id: number; filename: string }) => {
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
  dataRegion,
  dataYear,
  onJobUpdate,
}: {
  headersResult: HeadersResult
  templates: TemplateRow[]
  onSuccess: (result: Record<string, unknown>) => void
  onCancel: () => void
  dataRegion?: string
  dataYear?: number
  onJobUpdate?: () => void
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

  const allRequiredMapped = [...REQUIRED_FIELDS].every(f =>
    Object.values(mapping).includes(f)
  )

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
        data_region: dataRegion,
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
          onJobUpdate?.()
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
  const [headersResult, setHeadersResult] = useState<HeadersResult | null>(null)
  const [previewData, setPreviewData] = useState<Record<string, unknown>[]>([])
  const [previewInfo, setPreviewInfo] = useState<{
    filename: string
    row_count: number
    platform: string
    month_range: string
    inserted: number
    skipped: number
  } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [activeJob, setActiveJob] = useState<UploadConfirmJobResponse | null>(null)
  const [jobProgressVisible, setJobProgressVisible] = useState(false)

  const [dataRegion, setDataRegion] = useState<string | undefined>(undefined)
  const [dataYear, setDataYear] = useState<number>(new Date().getFullYear())

  const [filterRegion, setFilterRegion] = useState<string | undefined>(undefined)
  const [filterYear, setFilterYear] = useState<number | undefined>(undefined)

  const { data: filesData, loading: filesLoading, run: runFilesQuery } = useRequest(
    (params?: { data_region?: string; data_year?: number }) =>
      listUploadFiles(params).then(r => r.data),
    { manual: true }
  )
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

  const handleUpload = async (file: File) => {
    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res = await getUploadHeaders(formData)
      setHeadersResult(res.data)
      setStep('mapping')
    } catch {
      // handled by interceptor
    } finally {
      setUploading(false)
    }
    return false
  }

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
    })
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
            multiple={false}
            beforeUpload={handleUpload}
            showUploadList={false}
            disabled={uploading}
          >
            <p className="ant-upload-drag-icon">
              {uploading ? <Spin /> : <InboxOutlined />}
            </p>
            <p className="ant-upload-text">
              {uploading ? '正在读取文件表头…' : '点击或拖拽 Excel / CSV 文件至此上传'}
            </p>
            <p className="ant-upload-hint">
              支持 .xlsx / .xls / .csv 格式，系统将自动推荐列映射模板
            </p>
          </Dragger>
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
      {step === 'mapping' && headersResult && (
        <>
          <Card style={{ marginBottom: 12 }}>
            <Space size="large">
              <span style={{ fontWeight: 500 }}>数据维度</span>
              <Select
                placeholder="国内 / 海外"
                value={dataRegion}
                onChange={setDataRegion}
                style={{ width: 120 }}
                options={[
                  { value: 'domestic', label: '国内' },
                  { value: 'overseas', label: '海外' },
                ]}
                allowClear
              />
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
            headersResult={headersResult}
            templates={templates}
            onSuccess={handleMappingSuccess}
            onCancel={() => setStep('upload')}
            dataRegion={dataRegion}
            dataYear={dataYear}
            onJobUpdate={refreshUploadJobs}
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
                    dataSource={(filesData as { id: number; filename: string }[] | undefined) ?? []}
                    columns={historyColumns(handleDelete, startDownloadJob, downloadJobsByFileId)}
                    rowKey="id"
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
    </Space>
  )
}
