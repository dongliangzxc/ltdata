import { Anchor, Typography, Tag, Alert, Divider, Row, Col, Card, Steps } from 'antd'
import {
  UploadOutlined, DatabaseOutlined, ProfileOutlined, AppstoreAddOutlined,
  ClearOutlined, AimOutlined, FundOutlined, ExportOutlined, QuestionCircleOutlined,
} from '@ant-design/icons'

const { Title, Paragraph, Text } = Typography

const S = ({ children }: { children: React.ReactNode }) => (
  <Text strong>{children}</Text>
)

export default function ManualPage() {
  return (
    <Row gutter={24} style={{ minHeight: '100%' }}>
      {/* 右侧锚点导航 */}
      <Col flex="180px" style={{ position: 'sticky', top: 24, alignSelf: 'flex-start' }}>
        <Anchor
          offsetTop={24}
          items={[
            { key: 'flow',     href: '#flow',     title: '整体流程' },
            { key: 'upload',   href: '#upload',   title: '数据上传' },
            { key: 'rawdata',  href: '#rawdata',  title: '原始数据' },
            { key: 'metadata', href: '#metadata', title: '元数据管理' },
            { key: 'models',   href: '#models',   title: '型号管理' },
            { key: 'clean',    href: '#clean',    title: '数据清洗' },
            { key: 'match',    href: '#match',    title: '匹配确认' },
            { key: 'workbench',href: '#workbench',title: '查询工作台' },
            { key: 'export',   href: '#export',   title: '数据导出' },
            { key: 'faq',      href: '#faq',      title: '常见问题' },
          ]}
        />
      </Col>

      {/* 主内容区 */}
      <Col flex="auto" style={{ maxWidth: 860 }}>
        <Typography>
          <Title level={2}>洛图数据处理平台 · 使用手册</Title>
          <Paragraph type="secondary">适用对象：运营、数据分析等业务人员</Paragraph>

          {/* ── 整体流程 ── */}
          <Title level={3} id="flow">整体工作流程</Title>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="建议按以下顺序操作，首次使用需先完成「准备工作」"
          />
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={12}>
              <Card size="small" title="准备工作（一次性）" style={{ background: '#fafafa' }}>
                <Paragraph style={{ margin: 0 }}>
                  <Tag color="purple">1</Tag> 在「元数据管理」导入规格字段定义<br />
                  <Tag color="purple">2</Tag> 在「型号管理」导入品牌型号数据
                </Paragraph>
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" title="每批数据处理流程" style={{ background: '#fafafa' }}>
                <Steps
                  direction="vertical"
                  size="small"
                  style={{ marginTop: 4 }}
                  items={[
                    { title: '数据上传', icon: <UploadOutlined /> },
                    { title: '数据清洗', icon: <ClearOutlined /> },
                    { title: '匹配确认', icon: <AimOutlined /> },
                    { title: '数据导出 / 查询工作台', icon: <ExportOutlined /> },
                  ]}
                />
              </Card>
            </Col>
          </Row>

          <Divider />

          {/* ── 数据上传 ── */}
          <Title level={3} id="upload"><UploadOutlined /> 数据上传</Title>
          <Paragraph>
            将原始销售数据 Excel（<Text code>.xlsx / .xls</Text>）拖拽到上传区域或点击选择文件。
            系统自动识别平台（京东 / 天猫 / 淘宝）和月份范围，上传成功后展示前 50 行预览。
          </Paragraph>
          <Paragraph>
            <S>上传历史</S>：页面下方列出所有已上传文件，支持删除（删除后对应原始数据一并移除）。
          </Paragraph>
          <Alert type="warning" showIcon style={{ marginBottom: 16 }}
            message="同一商品（相同 item_id）同月份同平台已存在时自动跳过，不会重复入库。" />

          <Divider />

          {/* ── 原始数据 ── */}
          <Title level={3} id="rawdata"><DatabaseOutlined /> 原始数据查看</Title>
          <Paragraph>
            用于浏览和核查已上传数据。支持按平台、月份、品牌、关键词筛选，仅供查阅，不做任何修改。
          </Paragraph>

          <Divider />

          {/* ── 元数据管理 ── */}
          <Title level={3} id="metadata"><ProfileOutlined /> 元数据管理</Title>
          <Paragraph>
            元数据定义商品规格字段（如声道数、输出功率），决定最终导出 Excel 中有哪些规格列。
            <S>唯一键：品类码 + 规格名称</S>，重复导入自动更新，不产生重复记录。
          </Paragraph>
          <Title level={5}>Excel 批量导入（推荐）</Title>
          <Paragraph>
            点击「Excel 导入」→ 系统解析文件并弹出<S>预览确认窗口</S>，展示行数统计、错误/警告列表、前 10 条预览。
            确认无误后点「确认导入」正式写入；点「取消」不产生任何修改。
          </Paragraph>
          <Alert type="info" showIcon style={{ marginBottom: 8 }}
            message={<span>Excel 格式要求：Sheet 名称必须为「元数据」，必须包含列：<Text code>规格名称</Text>、<Text code>规格类型</Text>（数值型/文本型/布尔型）</span>} />
          <Paragraph>
            其他可选列：品类码、规格值（逗号分隔可选项）、必填、单选、保留几位小数。
          </Paragraph>

          <Divider />

          {/* ── 型号管理 ── */}
          <Title level={3} id="models"><AppstoreAddOutlined /> 型号管理</Title>
          <Paragraph>
            型号库是匹配的核心数据源，存放所有在管型号及其规格参数。
            <S>唯一键：品牌码 + 型号码</S>，重复导入自动更新。
          </Paragraph>
          <Title level={5}>Excel 批量导入（推荐）</Title>
          <Paragraph>
            流程同元数据：上传 → 预览确认 → 导入。Excel 需包含两个 Sheet：
          </Paragraph>
          <Paragraph>
            <Tag>Sheet「型号」</Tag>必须包含：<Text code>品牌码</Text>（或「品牌」）、<Text code>型号码</Text>（或「型号」）；
            可选：品类、品牌名称、型号名称、上市年、上市月、上市周、上市价格、网址。
          </Paragraph>
          <Paragraph>
            <Tag>Sheet「型号规格」</Tag>必须包含：品牌码、型号码、<Text code>规格名称</Text>、规格值。
          </Paragraph>
          <Paragraph>
            <S>展开规格明细</S>：点击列表每行左侧「▶」可查看该型号的规格参数。
          </Paragraph>

          <Divider />

          {/* ── 数据清洗 ── */}
          <Title level={3} id="clean"><ClearOutlined /> 数据清洗</Title>
          <Paragraph>
            对原始数据进行标准化处理，生成供后续匹配使用的干净数据集。
          </Paragraph>
          <Paragraph>
            <S>操作步骤</S>：勾选一个或多个已上传文件（可跨平台合并）→ 选择是否开启去重 → 点「开始清洗」。
          </Paragraph>
          <Paragraph>
            <Tag color="blue">去重</Tag> 同一商品（相同 item_id）在同月份同店铺只保留第一条，避免重复计算。
          </Paragraph>
          <Alert type="info" showIcon style={{ marginBottom: 16 }}
            message="清洗结果独立保存，不影响原始数据，同一批文件可反复清洗。清洗完成后点「执行匹配」跳转到匹配页面。" />

          <Divider />

          {/* ── 匹配确认 ── */}
          <Title level={3} id="match"><AimOutlined /> 匹配确认</Title>
          <Paragraph>
            将清洗后数据与型号库自动匹配，识别每条销售记录对应的品牌型号。
          </Paragraph>
          <Title level={5}>第一步：执行自动匹配</Title>
          <Paragraph>
            选择清洗任务 → 点「执行匹配」→ 实时进度条展示速度、预计剩余时间和已匹配条数 → 完成后显示统计面板。
          </Paragraph>
          <Title level={5}>匹配统计说明</Title>
          <Paragraph>
            <Tag color="green">自动匹配</Tag> 系统自动识别出型号的数量&emsp;
            <Tag color="orange">待确认</Tag> 需人工处理&emsp;
            <Tag color="blue">已人工确认</Tag> 手动指定型号&emsp;
            <Tag color="red">已排除</Tag> 不在分析范围内
          </Paragraph>
          <Title level={5}>第二步：人工处理待确认条目</Title>
          <Paragraph>
            在「待确认条目」列表中，查看宝贝名称和原始品牌 → 在「指定型号」下拉框搜索并选择型号（支持品牌码、型号码、型号名搜索）→ 点「确认」；确实不属于分析范围则点「排除」。
          </Paragraph>
          <Title level={5}>第三步：发布到分析库</Title>
          <Paragraph>
            匹配完成后，点「发布到分析库」将已匹配数据写入分析数据库，发布后可在「查询工作台」查询。
          </Paragraph>

          <Divider />

          {/* ── 查询工作台 ── */}
          <Title level={3} id="workbench"><FundOutlined /> 查询工作台</Title>
          <Alert type="warning" showIcon style={{ marginBottom: 12 }}
            message="前提：已完成匹配并点击「发布到分析库」" />
          <Paragraph>
            对已发布数据进行多维度查询。支持按月份、平台、品牌、型号、品类、关键词筛选。
            设置条件后点「查询」，点「导出 Excel」可将当前筛选结果全量导出（不限页数）。
          </Paragraph>

          <Divider />

          {/* ── 数据导出 ── */}
          <Title level={3} id="export"><ExportOutlined /> 数据导出</Title>
          <Paragraph>
            将匹配结果导出为含规格参数的 Excel 报告（按品类分 Sheet）。
          </Paragraph>
          <Paragraph>
            <S>操作步骤</S>：选择清洗任务 → 填写文件名前缀（如「Soundbar 7-8月已处理」）→ 点「提交导出任务」。
            任务立即提交，<S>无需等待</S>，在下方「导出历史」列表中查看进度，完成后点「下载」。
          </Paragraph>
          <Paragraph>
            <Tag color="default">排队中</Tag>&ensp;
            <Tag color="processing">生成中</Tag>&ensp;
            <Tag color="success">已完成 → 可下载</Tag>&ensp;
            <Tag color="error">失败 → 悬浮查看原因</Tag>
          </Paragraph>
          <Alert type="info" showIcon style={{ marginBottom: 16 }}
            message={<span>导出文件结构：每个品类一个 Sheet，列包含平台、月份、销量、销售额、品牌、型号，以及「元数据管理」中定义的所有规格列；待确认商品单独放在「待确认」Sheet。</span>} />

          <Divider />

          {/* ── 常见问题 ── */}
          <Title level={3} id="faq"><QuestionCircleOutlined /> 常见问题</Title>

          <Title level={5}>Q：上传后数据量和文件行数不一样？</Title>
          <Paragraph>
            系统会跳过表头、合计行等无效行，并自动跳过重复记录（同 item_id + 月份 + 平台已存在的）。以页面提示的「写入条数」为准。
          </Paragraph>

          <Title level={5}>Q：执行匹配后匹配率很低怎么办？</Title>
          <Paragraph>
            常见原因：① <S>型号库缺少对应品类数据</S>——前往「型号管理」补充；② <S>品牌名称不统一</S>——完善型号库中的 brand_name 字段（系统会尝试从宝贝名称中识别英文品牌码）；③ 部分数据本身不属于目标品类，可在「匹配确认」中选「排除」。
          </Paragraph>

          <Title level={5}>Q：Excel 导入时提示格式错误？</Title>
          <Paragraph>
            预览弹窗中「错误」折叠面板会精确指出哪一行有问题。常见原因：
            缺少必要列名；元数据 Sheet 名不是「元数据」；型号 Sheet 名不是「型号」/「型号规格」。
          </Paragraph>

          <Title level={5}>Q：导出的 Excel 规格列全是空的？</Title>
          <Paragraph>
            检查「元数据管理」中是否已导入规格定义。规格列名称来自元数据，若元数据为空则导出文件没有规格列。
          </Paragraph>

          <Title level={5}>Q：发布后查询工作台看不到数据？</Title>
          <Paragraph>
            确认：① 已执行匹配且匹配率 &gt; 0；② 在「匹配确认」页面点击了「发布到分析库」并成功；③ 回到查询工作台后点「查询」按钮（首次进入不会自动加载）。
          </Paragraph>

          <Title level={5}>Q：导出任务一直显示「排队中」？</Title>
          <Paragraph>
            点右上角「刷新」手动刷新状态。若长时间无响应，请联系管理员检查服务状态。
          </Paragraph>
        </Typography>
      </Col>
    </Row>
  )
}
