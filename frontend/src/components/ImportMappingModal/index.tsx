import { useState } from 'react'
import {
  Modal, Steps, Upload, Button, Select, Checkbox, Switch, Input,
  Table, Alert, Collapse, Space, Typography, Spin, message,
} from 'antd'
import { InboxOutlined } from '@ant-design/icons'
import type { UploadFile } from 'antd'
import CategorySelect from '../CategorySelect'

const { Dragger } = Upload
const { Text } = Typography
const { Panel } = Collapse

export interface FieldDef {
  value: string
  label: string
  required?: boolean
}

export interface Props {
  open: boolean
  module: 'model' | 'url' | 'attr'
  standardFields: FieldDef[]
  headersUrl: string
  confirmUrl: string
  onSuccess: (result: Record<string, unknown>) => void
  onClose: () => void
}

type Step = 'category' | 'mapping' | 'result'

interface HeadersResponse {
  temp_file_id: string
  filename: string
  columns: string[]
  suggested_template: {
    id: number
    name: string
    mapping: Record<string, string>
    ignore_columns: string[]
  } | null
  match_score: number
}

export default function ImportMappingModal({
  open, module, standardFields, headersUrl, confirmUrl, onSuccess, onClose,
}: Props) {
  const [step, setStep] = useState<Step>('category')
  const [categoryCode, setCategoryCode] = useState<string>('')
  const [uploading, setUploading] = useState(false)
  const [confirming, setConfirming] = useState(false)

  // Mapping state
  const [tempFileId, setTempFileId] = useState('')
  const [columns, setColumns] = useState<string[]>([])
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [ignoreColumns, setIgnoreColumns] = useState<Set<string>>(new Set())
  const [saveTemplate, setSaveTemplate] = useState(false)
  const [templateName, setTemplateName] = useState('')

  // Result state
  const [result, setResult] = useState<Record<string, unknown>>({})

  const reset = () => {
    setStep('category')
    setCategoryCode('')
    setTempFileId('')
    setColumns([])
    setMapping({})
    setIgnoreColumns(new Set())
    setSaveTemplate(false)
    setTemplateName('')
    setResult({})
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  // ── Step 1: upload file ─────────────────────────────────────────────────

  const handleUpload = async (file: File) => {
    if (!categoryCode) {
      message.warning('请先选择品类')
      return false
    }
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const resp = await fetch(`/api${headersUrl}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
        body: formData,
      })
      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || '上传失败')
      }
      const data: HeadersResponse = await resp.json()
      setTempFileId(data.temp_file_id)
      setColumns(data.columns)

      // Apply suggested template if any
      if (data.suggested_template && data.match_score >= 60) {
        setMapping(data.suggested_template.mapping)
        setIgnoreColumns(new Set(data.suggested_template.ignore_columns))
      } else {
        // Auto-map columns whose name exactly matches a standard field
        const autoMap: Record<string, string> = {}
        const fieldValues = new Set(standardFields.map(f => f.value))
        data.columns.forEach(col => {
          if (fieldValues.has(col)) autoMap[col] = col
        })
        setMapping(autoMap)
        setIgnoreColumns(new Set())
      }
      setStep('mapping')
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '上传失败')
    } finally {
      setUploading(false)
    }
    return false // prevent antd auto-upload
  }

  // ── Step 2: confirm mapping ──────────────────────────────────────────────

  const requiredFields = standardFields.filter(f => f.required).map(f => f.value)
  const mappedTargets = new Set(Object.values(mapping))
  const missingRequired = requiredFields.filter(f => !mappedTargets.has(f))
  const canConfirm = missingRequired.length === 0

  const handleConfirm = async () => {
    if (!canConfirm) return
    setConfirming(true)
    try {
      const payload: Record<string, unknown> = {
        temp_file_id: tempFileId,
        mapping,
        ignore_columns: Array.from(ignoreColumns),
        category_code: categoryCode,
      }
      if (saveTemplate && templateName.trim()) {
        payload.save_template_name = templateName.trim()
      }
      const resp = await fetch(`/api${confirmUrl}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify(payload),
      })
      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || '导入失败')
      }
      const data = await resp.json()
      setResult(data)
      setStep('result')
      onSuccess(data)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '导入失败')
    } finally {
      setConfirming(false)
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────

  const stepIndex = step === 'category' ? 0 : step === 'mapping' ? 1 : 2

  const mappingColumns = [
    {
      title: '原始列名',
      dataIndex: 'col',
      key: 'col',
      render: (col: string) => <Text code>{col}</Text>,
    },
    {
      title: '映射目标',
      dataIndex: 'col',
      key: 'target',
      render: (col: string) => {
        const target = mapping[col]
        const isRequired = target && requiredFields.includes(target)
        const isMissing = isRequired && !mappedTargets.has(target)
        return (
          <Select
            style={{ width: 200 }}
            value={mapping[col] || undefined}
            allowClear
            status={isMissing ? 'error' : undefined}
            placeholder="— 忽略 —"
            onChange={val => {
              if (val) {
                setMapping(prev => ({ ...prev, [col]: val }))
              } else {
                setMapping(prev => {
                  const next = { ...prev }
                  delete next[col]
                  return next
                })
              }
            }}
            options={standardFields.map(f => ({
              value: f.value,
              label: f.required ? `${f.label} *` : f.label,
            }))}
          />
        )
      },
    },
    {
      title: '忽略',
      dataIndex: 'col',
      key: 'ignore',
      render: (col: string) => (
        <Checkbox
          checked={ignoreColumns.has(col)}
          onChange={e => {
            const next = new Set(ignoreColumns)
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
            setIgnoreColumns(next)
          }}
        />
      ),
    },
  ]

  const errors = Array.isArray(result.errors) ? result.errors as string[] : []

  return (
    <Modal
      open={open}
      title="批量导入"
      width={700}
      footer={null}
      onCancel={handleClose}
      destroyOnClose
    >
      <Steps
        current={stepIndex}
        items={[
          { title: '选择品类 & 上传' },
          { title: '列映射确认' },
          { title: '导入结果' },
        ]}
        style={{ marginBottom: 24 }}
      />

      {/* Step 1: category + upload */}
      {step === 'category' && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text strong>品类（必填）</Text>
            <CategorySelect
              value={categoryCode}
              onChange={setCategoryCode}
              style={{ width: '100%', marginTop: 8 }}
            />
          </div>
          <Spin spinning={uploading}>
            <Dragger
              accept=".xlsx,.xls,.csv"
              showUploadList={false}
              beforeUpload={handleUpload}
              disabled={!categoryCode || uploading}
            >
              <p className="ant-upload-drag-icon"><InboxOutlined /></p>
              <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
              <p className="ant-upload-hint">支持 .xlsx / .xls / .csv</p>
            </Dragger>
          </Spin>
        </Space>
      )}

      {/* Step 2: mapping */}
      {step === 'mapping' && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          {missingRequired.length > 0 && (
            <Alert
              type="error"
              message={`必填字段未映射：${missingRequired.join('、')}`}
            />
          )}
          <Table
            dataSource={columns.map(col => ({ col, key: col }))}
            columns={mappingColumns}
            pagination={false}
            size="small"
            scroll={{ y: 300 }}
          />
          <Space>
            <Switch checked={saveTemplate} onChange={setSaveTemplate} />
            <Text>保存为模板</Text>
            {saveTemplate && (
              <Input
                placeholder="模板名称"
                value={templateName}
                onChange={e => setTemplateName(e.target.value)}
                style={{ width: 200 }}
              />
            )}
          </Space>
          <Space>
            <Button onClick={() => setStep('category')}>上一步</Button>
            <Button
              type="primary"
              disabled={!canConfirm}
              loading={confirming}
              onClick={handleConfirm}
            >
              确认入库
            </Button>
          </Space>
        </Space>
      )}

      {/* Step 3: result */}
      {step === 'result' && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert
            type={errors.length > 0 ? 'warning' : 'success'}
            message="导入完成"
            description={
              <Space direction="vertical">
                {typeof result.inserted === 'number' && <Text>新增：{result.inserted} 条</Text>}
                {typeof result.models_inserted === 'number' && <Text>新增型号：{result.models_inserted} 条</Text>}
                {typeof result.models_updated === 'number' && <Text>更新型号：{result.models_updated} 条</Text>}
                {typeof result.updated === 'number' && <Text>更新：{result.updated} 条</Text>}
                {typeof result.skipped === 'number' && <Text>跳过：{result.skipped} 条</Text>}
                {errors.length > 0 && <Text type="warning">异常：{errors.length} 条</Text>}
              </Space>
            }
          />
          {errors.length > 0 && (
            <Collapse>
              <Panel header={`查看异常详情（${Math.min(errors.length, 10)} / ${errors.length}）`} key="1">
                {errors.slice(0, 10).map((e, idx) => (
                  <div key={idx}><Text type="secondary">{e}</Text></div>
                ))}
                {errors.length > 10 && <Text type="secondary">… 仅显示前 10 条</Text>}
              </Panel>
            </Collapse>
          )}
          <Space>
            <Button type="primary" onClick={handleClose}>完成</Button>
            <Button onClick={reset}>继续导入</Button>
          </Space>
        </Space>
      )}
    </Modal>
  )
}
