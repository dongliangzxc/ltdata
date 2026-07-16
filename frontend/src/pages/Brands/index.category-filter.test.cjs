const assert = require('node:assert/strict')
const fs = require('node:fs')
const Module = require('node:module')
const esbuild = require('esbuild')

require.extensions['.ts'] = require.extensions['.tsx'] = (module, filename) => {
  const source = fs.readFileSync(filename, 'utf8')
  const { code } = esbuild.transformSync(source, {
    loader: filename.endsWith('.tsx') ? 'tsx' : 'ts',
    format: 'cjs',
    target: 'es2020',
    jsx: 'automatic',
  })
  module._compile(code, filename)
}

const brands = [
  {
    brand_code: 'SONY',
    brand_name: '索尼',
    original_brand_name: 'Sony Upload',
    category_codes: ['HEADPHONE'],
    model_count: 2,
    alias_count: 0,
  },
  {
    brand_code: 'BOSE',
    brand_name: '博士',
    original_brand_name: 'Bose Upload',
    category_codes: ['SPEAKER'],
    model_count: 1,
    alias_count: 0,
  },
  {
    brand_code: 'EMPTY',
    brand_name: '无品类',
    original_brand_name: 'Empty Upload',
    category_codes: [],
    model_count: 0,
    alias_count: 0,
  },
]

let states = []
let stateIndex = 0
let currentTree = null
let RootComponent = null

const flatten = value => Array.isArray(value) ? value.flat(Infinity).filter(Boolean) : [value].filter(Boolean)

const MiniReact = {
  Fragment: Symbol('Fragment'),
  createElement(type, props, ...children) {
    const nextProps = { ...(props || {}) }
    if (children.length > 0) nextProps.children = flatten(children)
    return { type, props: nextProps }
  },
  useMemo(factory) {
    return factory()
  },
  useState(initialValue) {
    const index = stateIndex
    if (states[index] === undefined) {
      states[index] = typeof initialValue === 'function' ? initialValue() : initialValue
    }
    const setState = nextValue => {
      states[index] = typeof nextValue === 'function' ? nextValue(states[index]) : nextValue
      renderRoot()
    }
    stateIndex += 1
    return [states[index], setState]
  },
}

const jsxRuntime = {
  Fragment: MiniReact.Fragment,
  jsx: (type, props) => MiniReact.createElement(type, props),
  jsxs: (type, props) => MiniReact.createElement(type, props),
}

function resolveNode(node) {
  if (node == null || typeof node === 'boolean') return null
  if (typeof node === 'string' || typeof node === 'number') return node
  if (Array.isArray(node)) return node.map(resolveNode).filter(Boolean)
  if (node.type === MiniReact.Fragment) return resolveNode(node.props.children)
  if (typeof node.type === 'function') return resolveNode(node.type(node.props || {}))
  return {
    ...node,
    props: {
      ...(node.props || {}),
      children: resolveNode((node.props || {}).children),
    },
  }
}

function renderRoot() {
  stateIndex = 0
  currentTree = resolveNode(MiniReact.createElement(RootComponent))
}

function render(component) {
  RootComponent = component
  states = []
  renderRoot()
}

function textContent(node) {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textContent).join('')
  return textContent((node.props || {}).children)
}

function findNode(node, predicate) {
  if (node == null || typeof node === 'string' || typeof node === 'number') return null
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findNode(child, predicate)
      if (found) return found
    }
    return null
  }
  if (predicate(node)) return node
  return findNode((node.props || {}).children, predicate)
}

const screen = {
  getByTestId(testId) {
    const node = findNode(currentTree, item => (item.props || {})['data-testid'] === testId)
    assert.ok(node, `Unable to find test id ${testId}`)
    return Object.defineProperty(node, 'textContent', { get: () => textContent(node), configurable: true })
  },
  getByLabelText(label) {
    const node = findNode(currentTree, item => (item.props || {})['aria-label'] === label)
    assert.ok(node, `Unable to find label ${label}`)
    return node
  },
}

const fireEvent = {
  change(node, event) {
    assert.equal(typeof node.props.onChange, 'function')
    node.props.onChange(event)
  },
}

const stubAntd = {
  Card: ({ title, extra, children }) => MiniReact.createElement('section', null, title, extra, children),
  Table: ({ dataSource }) => MiniReact.createElement(
    'table',
    { 'data-testid': 'brand-table' },
    MiniReact.createElement(
      'tbody',
      null,
      dataSource.map(record => MiniReact.createElement(
        'tr',
        { key: record.brand_code },
        MiniReact.createElement('td', null, record.brand_code),
        MiniReact.createElement('td', null, record.original_brand_name || '-'),
        MiniReact.createElement('td', null, record.brand_name || '-'),
        MiniReact.createElement('td', null, (record.category_codes || []).join(',')),
        MiniReact.createElement('td', null, String(record.model_count)),
        MiniReact.createElement('td', null, String(record.alias_count)),
      )),
    ),
  ),
  Button: ({ children, onClick }) => MiniReact.createElement('button', { onClick }, children),
  Space: ({ children }) => MiniReact.createElement('div', null, children),
  Popconfirm: ({ children }) => MiniReact.createElement(MiniReact.Fragment, null, children),
  Tag: ({ children }) => MiniReact.createElement('span', null, children),
  Form: Object.assign(
    ({ children }) => MiniReact.createElement('form', null, children),
    {
      useForm: () => [{ setFieldsValue() {}, resetFields() {}, validateFields: async () => ({}) }],
      Item: ({ children }) => MiniReact.createElement('div', null, children),
    },
  ),
  Modal: ({ children }) => MiniReact.createElement('div', null, children),
  Input: Object.assign(
    ({ value, onChange, placeholder }) => MiniReact.createElement('input', { value, onChange, placeholder }),
    {
      Search: ({ value, onChange, placeholder }) => MiniReact.createElement('input', {
        'aria-label': placeholder,
        value,
        onChange,
        placeholder,
      }),
    },
  ),
  Select: ({
    value,
    onChange,
    placeholder,
    options = [],
    allowClear,
    showSearch,
    optionFilterProp,
  }) => {
    assert.equal(showSearch, true)
    assert.equal(optionFilterProp, 'label')
    return MiniReact.createElement(
      'select',
      {
        'aria-label': placeholder,
        value: value || '',
        onChange: event => onChange(event.target.value || undefined),
      },
      [
        allowClear ? MiniReact.createElement('option', { key: '', value: '' }, '') : null,
        ...options.map(option => MiniReact.createElement('option', { key: option.value, value: option.value }, option.label)),
      ],
    )
  },
  message: { success() {}, error() {} },
}

const originalLoad = Module._load
Module._load = function patchedLoad(request, parent, isMain) {
  if (request === 'react') return MiniReact
  if (request === 'react/jsx-runtime') return jsxRuntime
  if (request === 'antd') return stubAntd
  if (request === '@ant-design/icons') {
    return {
      PlusOutlined: () => null,
      DeleteOutlined: () => null,
      EditOutlined: () => null,
    }
  }
  if (request === 'ahooks') {
    return { useRequest: () => ({ data: brands, loading: false, refresh() {} }) }
  }
  if (request.endsWith('/services/api') || request.endsWith('services/api')) {
    return {
      listBrands: async () => ({ data: brands }),
      listBrandAliasesByCode: async () => ({ data: [] }),
      createBrandAliasForCode: async () => ({ data: {} }),
      deleteBrandAliasById: async () => ({}),
      updateBrand: async () => ({ data: brands[0] }),
      createBrand: async () => ({ data: brands[0] }),
      fetchCategories: async () => [],
    }
  }
  if (request.endsWith('/hooks/useCategoryOptions') || request.endsWith('hooks/useCategoryOptions')) {
    return {
      useCategoryOptions: () => ({
        loading: false,
        options: [
          { label: '耳机', value: 'HEADPHONE' },
          { label: '音箱', value: 'SPEAKER' },
        ],
      }),
    }
  }
  if (request.endsWith('/components/CreateBrandModal') || request.endsWith('components/CreateBrandModal')) {
    return { default: () => null }
  }
  return originalLoad.apply(this, arguments)
}

try {
  const BrandsPage = require('./index.tsx').default
  render(BrandsPage)

  let table = screen.getByTestId('brand-table')
  assert.match(table.textContent, /SONY/)
  assert.match(table.textContent, /BOSE/)
  assert.match(table.textContent, /EMPTY/)

  fireEvent.change(screen.getByLabelText('筛选品类'), { target: { value: 'HEADPHONE' } })
  table = screen.getByTestId('brand-table')
  assert.match(table.textContent, /SONY/)
  assert.doesNotMatch(table.textContent, /BOSE/)
  assert.doesNotMatch(table.textContent, /EMPTY/)

  fireEvent.change(screen.getByLabelText('搜索品牌码 / 上传时品牌名称 / 修改后名称'), { target: { value: 'bose' } })
  table = screen.getByTestId('brand-table')
  assert.doesNotMatch(table.textContent, /SONY/)
  assert.doesNotMatch(table.textContent, /BOSE/)

  fireEvent.change(screen.getByLabelText('筛选品类'), { target: { value: '' } })
  table = screen.getByTestId('brand-table')
  assert.match(table.textContent, /BOSE/)
  assert.doesNotMatch(table.textContent, /SONY/)

  console.log('Brand category filter behavior passed')
} finally {
  Module._load = originalLoad
}
