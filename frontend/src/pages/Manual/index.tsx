import { Anchor, Typography, Tag, Alert, Divider, Row, Col, Card, Steps } from 'antd'
import {
  UploadOutlined, DatabaseOutlined, ProfileOutlined, AppstoreAddOutlined,
  ClearOutlined, AimOutlined, FundOutlined, ExportOutlined, QuestionCircleOutlined,
  LinkOutlined, FilterOutlined, HistoryOutlined,
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
            { key: 'flow',        href: '#flow',        title: '整体流程' },
            { key: 'upload',      href: '#upload',      title: '数据上传' },
            { key: 'rawdata',     href: '#rawdata',     title: '原始数据' },
            { key: 'metadata',    href: '#metadata',    title: '元数据管理' },
            { key: 'models',      href: '#models',      title: '型号管理' },
            { key: 'url-mapping', href: '#url-mapping', title: 'URL映射管理' },
            { key: 'historical',  href: '#historical',  title: '历史库' },
            { key: 'clean',       href: '#clean',       title: '数据清洗' },
            { key: 'rules',       href: '#rules',       title: '规则管理' },
            { key: 'match',       href: '#match',       title: '匹配确认' },
            { key: 'workbench',   href: '#workbench',   title: '查询工作台' },
            { key: 'export',      href: '#export',      title: '数据导出' },
            { key: 'faq',         href: '#faq',         title: '常见问题' },
          ]}
        />
      </Col>

      {/* 主内容区 */}
      <Col flex="auto" style={{ maxWidth: 860 }}>
        <Typography>
          <Title level={2}>洛图数据处理平台 · 使用手册</Title>
          <Paragraph type="secondary">适用对象：运营、数据分析等业务人员 &nbsp;|&nbsp; 版本：规则引擎三期</Paragraph>

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
                  <Tag color="purple">2</Tag> 在「型号管理」导入品牌型号数据<br />
                  <Tag color="purple">3</Tag> 在「规则管理」配置干扰词、品牌写法、匹配规则<br />
                  <Tag color="purple">4</Tag>（可选）在「URL映射管理」配置精确URL→型号映射<br />
                  <Tag color="purple">5</Tag>（可选）在「历史库」导入历史确认对照表
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
                    { title: '发布 → 查询工作台 / 导出', icon: <ExportOutlined /> },
                  ]}
                />
              </Card>
            </Col>
          </Row>
          <Card size="small" title="匹配阶段优先级（自动，无需手动干预）" style={{ marginBottom: 16 }}>
            <Paragraph style={{ margin: 0 }}>
              <Tag color="blue">S0</Tag> URL精确映射 &nbsp;→&nbsp;
              <Tag color="purple">S0.2</Tag> 历史库精确匹配 &nbsp;→&nbsp;
              <Tag color="cyan">S0.5</Tag> 显式关键词规则 &nbsp;→&nbsp;
              <Tag color="green">S1-S4</Tag> 算法匹配 &nbsp;→&nbsp;
              <Tag color="orange">待确认</Tag> 人工处理
            </Paragraph>
          </Card>

          <Divider />

          {/* ── 数据上传 ── */}
          <Title level={3} id="upload"><UploadOutlined /> 数据上传</Title>
          <Paragraph>
            将原始销售数据 Excel（<Text code>.xlsx / .xls</Text>）拖拽到上传区域或点击选择文件。
            系统自动识别平台（京东 / 天猫 / 淘宝 / 苏宁）和月份范围，上传成功后展示前 50 行预览。
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

          {/* ── URL映射管理 ── */}
          <Title level={3} id="url-mapping"><LinkOutlined /> URL映射管理（S0 精确映射）</Title>
          <Paragraph>
            针对"已知某个电商URL固定对应某型号"的场景，配置后匹配阶段优先命中，准确率 100%，不走算法。
          </Paragraph>
          <Title level={5}>使用场景</Title>
          <Paragraph>
            例如京东商品 <Text code>item_id=12345678</Text> 始终是 SONY HT-A7000，配置一条映射后，
            后续所有包含该 item_id 的数据无论宝贝名称如何变化，均自动匹配到指定型号。
          </Paragraph>
          <Title level={5}>操作方式</Title>
          <Paragraph>
            ① <S>手动新增</S>：点「新增」，填写平台、商品ID、型号（搜索选择）、参考价（可选）；<br />
            ② <S>Excel 批量导入</S>：文件需包含列 <Text code>platform</Text>、<Text code>item_id</Text>、<Text code>model_code</Text>，可选 <Text code>price</Text>；<br />
            ③ <S>编辑/删除</S>：已有映射支持行内编辑和单条删除。
          </Paragraph>
          <Alert type="info" showIcon style={{ marginBottom: 16 }}
            message="platform 字段大小写不敏感，导入时自动转为小写（jd/tmall/taobao/suning）。" />

          <Divider />

          {/* ── 历史库 ── */}
          <Title level={3} id="historical"><HistoryOutlined /> 历史库（S0.2 历史精确匹配）</Title>
          <Paragraph>
            历史库用于将过去人工确认过的「商品→型号」对照关系导入系统，后续遇到相同平台+商品ID时自动命中，
            无需重复人工确认。优先级仅次于 URL映射（S0），高于所有算法。
          </Paragraph>
          <Title level={5}>Tab 1：导入历史对照表</Title>
          <Paragraph>
            <S>Excel 格式</S>（每行一条映射关系）：
          </Paragraph>
          <Paragraph>
            <Tag>platform</Tag> 平台，jd/tmall/taobao/suning（自动转小写）<br />
            <Tag>item_id</Tag> 商品 ID（与原始数据一致）<br />
            <Tag>model_code</Tag> 型号编码（必须存在于型号库中，否则该行报错跳过）
          </Paragraph>
          <Paragraph>
            拖拽或点击上传 Excel → 系统解析后显示导入结果：成功 N 条、失败 M 条（含失败行号和原因）。
            已导入的批次列表显示在下方，支持<S>整批删除</S>（撤销本次导入）。
          </Paragraph>
          <Alert type="info" showIcon style={{ marginBottom: 8 }}
            message={<span><S>重复导入（upsert）</S>：同一平台+商品ID 再次导入时，型号映射更新为最新批次，不产生重复记录。</span>} />
          <Alert type="warning" showIcon style={{ marginBottom: 16 }}
            message="注意：若商品 X 在批次A中导入，后来在批次B中以不同型号再次导入，则删除批次B时，商品 X 的映射将一并被删除（因已被批次B覆盖）。" />
          <Title level={5}>Tab 2：映射管理</Title>
          <Paragraph>
            可按平台、导入批次筛选所有历史映射，支持单条删除。
          </Paragraph>

          <Divider />

          {/* ── 数据清洗 ── */}
          <Title level={3} id="clean"><ClearOutlined /> 数据清洗</Title>
          <Paragraph>
            对原始数据进行标准化处理，生成供后续匹配使用的干净数据集。清洗会自动应用「规则管理」中配置的干扰词过滤和品牌写法标准化。
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

          {/* ── 规则管理 ── */}
          <Title level={3} id="rules"><FilterOutlined /> 规则管理（规则引擎）</Title>
          <Paragraph>
            规则管理提供 5 类配置，在清洗和匹配阶段自动生效，无需对每批数据手动操作。
          </Paragraph>

          <Title level={5}>Tab 1：干扰词库</Title>
          <Paragraph>
            配置需要从商品名称中过滤掉的干扰词（如"【秒杀】""官方旗舰店"等）。
            清洗时自动去除，减少噪声对后续匹配的干扰。支持指定匹配字段（商品名称/店铺名称/两者）。
          </Paragraph>

          <Title level={5}>Tab 2：品牌写法库</Title>
          <Paragraph>
            将各种品牌别名/拼写变体映射到统一的品牌码。例如：「索尼」「SONY官方」→ <Text code>SONY</Text>。
            支持 Excel 批量导入（列：<Text code>alias_name</Text>、<Text code>brand_code</Text>）。
          </Paragraph>

          <Title level={5}>Tab 3：匹配规则（S0.5 显式规则）</Title>
          <Paragraph>
            针对"商品名称包含某关键词时固定对应某型号"的规则。优先于算法，仅次于 URL映射和历史库。
            <br />配置字段：关键词、匹配方式（包含/精确/开头/结尾）、目标型号、优先级（数值越大越先匹配）。
          </Paragraph>
          <Alert type="info" showIcon style={{ marginBottom: 8 }}
            message="匹配规则按优先级从高到低逐条执行，命中第一条即停止，不继续匹配后续规则。" />

          <Title level={5}>Tab 4：过滤存档</Title>
          <Paragraph>
            清洗时被干扰词过滤掉的条目会存入此处。若某条目被误过滤，可在此恢复（恢复后重新运行清洗即可）。
          </Paragraph>

          <Title level={5}>Tab 5：属性规则</Title>
          <Paragraph>
            配置「商品名称包含关键词时自动标注属性值」的规则。例如：商品名含"5.1声道"→ 标注属性 声道数=5.1。
            支持全局规则（适用所有品类）和品类级规则。
            <br />配置字段：关键词、匹配方式、属性名、属性值、品类（可空=全局）、优先级。
          </Paragraph>
          <Paragraph>
            属性规则在每批匹配完成后自动执行，匹配结果可在「匹配确认」→「未补属性」Tab 查看。
          </Paragraph>

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
          <Title level={5}>匹配来源标签说明</Title>
          <Paragraph>
            「待确认条目」列表的「来源」列显示该条目通过哪个阶段被匹配：
          </Paragraph>
          <Paragraph>
            <Tag color="blue">URL映射</Tag> S0 精确URL匹配&emsp;
            <Tag color="purple">历史库</Tag> S0.2 历史对照表命中&emsp;
            <Tag color="cyan">规则</Tag> S0.5 显式关键词规则&emsp;
            <Tag color="green">算法S1-S4</Tag> 文本算法匹配&emsp;
            <Tag>未知</Tag> 待确认/未命中
          </Paragraph>
          <Title level={5}>第二步：人工处理待确认条目</Title>
          <Paragraph>
            在「待确认条目」列表中，查看宝贝名称和原始品牌 → 在「指定型号」下拉框搜索并选择型号（支持品牌码、型号码、型号名搜索）→ 点「确认」；确实不属于分析范围则点「排除」。
          </Paragraph>
          <Title level={5}>第三步：（可选）处理未识别品牌</Title>
          <Paragraph>
            切换到「未识别品牌」Tab，查看品牌无法识别的条目。可直接在此处确认型号，或回到「规则管理」→「品牌写法库」补充映射后重新匹配。
          </Paragraph>
          <Title level={5}>第四步：（可选）检查未补属性</Title>
          <Paragraph>
            切换到「未补属性」Tab，查看已匹配但属性尚未补全的条目。可手动补充，或回到「规则管理」→「属性规则」补充规则后重新应用。
          </Paragraph>
          <Title level={5}>第五步：发布到分析库</Title>
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
            常见原因：① <S>型号库缺少对应品类数据</S>——前往「型号管理」补充；② <S>品牌名称不统一</S>——在「规则管理」→「品牌写法库」补充写法映射；③ <S>商品名称噪声多</S>——在「规则管理」→「干扰词库」添加干扰词后重新清洗匹配；④ 部分数据本身不属于目标品类，可在「匹配确认」中选「排除」。
          </Paragraph>

          <Title level={5}>Q：历史数据怎么导入系统？</Title>
          <Paragraph>
            分两步：① 原始历史数据通过「数据上传」正常上传（与新数据流程相同）；② 历史确认对照表（商品→型号）通过「历史库」→「导入历史对照表」导入，系统会在匹配阶段自动命中。
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

          <Title level={5}>Q：匹配规则和历史库都有同一个商品，哪个优先？</Title>
          <Paragraph>
            优先级从高到低：<Tag color="blue">URL映射（S0）</Tag> &gt; <Tag color="purple">历史库（S0.2）</Tag> &gt; <Tag color="cyan">匹配规则（S0.5）</Tag> &gt; <Tag color="green">算法（S1-S4）</Tag>。URL映射配置后优先级最高，不会被其他规则覆盖。
          </Paragraph>
        </Typography>
      </Col>
    </Row>
  )
}
