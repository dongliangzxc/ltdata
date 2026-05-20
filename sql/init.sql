-- =============================================================
-- 洛图数据处理平台 - 初始化 SQL
-- 适用数据库: MySQL 5.7+
-- 说明: 全量建表，CREATE TABLE IF NOT EXISTS 保证幂等性
--       已有线上库若要增量执行，仅需执行「新增表」部分
-- =============================================================

CREATE DATABASE IF NOT EXISTS luotu DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE luotu;

-- ─────────────────────────────────────────────────────────────
-- 已有表（4 张）
-- ─────────────────────────────────────────────────────────────

-- 上传文件记录
CREATE TABLE IF NOT EXISTS upload_files (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    filename     VARCHAR(255) NOT NULL           COMMENT '原始文件名',
    platform     VARCHAR(50)                     COMMENT '平台: JD/TM/TB',
    month_range  VARCHAR(20)                     COMMENT '月份范围, 如 202501-202503',
    row_count    INT          DEFAULT 0          COMMENT '实际入库行数',
    status       VARCHAR(20)  DEFAULT 'done'     COMMENT 'pending/processing/done/error',
    template_id  INT                             COMMENT '本次上传使用的列模板 ID',
    uploaded_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='上传文件记录';

-- 原始数据（含去重唯一索引）
CREATE TABLE IF NOT EXISTS raw_data (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    file_id        INT          NOT NULL          COMMENT '关联 upload_files.id',
    platform       VARCHAR(50)                    COMMENT '平台',
    month          INT                            COMMENT '月份, 如 202507',
    category_lv0   VARCHAR(100)                   COMMENT 'JD Lv0类目',
    category_lv1   VARCHAR(100)                   COMMENT 'Lv1类目',
    category_lv2   VARCHAR(100)                   COMMENT 'Lv2类目',
    category_lv3   VARCHAR(100)                   COMMENT 'Lv3类目',
    category_lv4   VARCHAR(100)                   COMMENT 'Lv4类目',
    category_lv5   VARCHAR(100)                   COMMENT 'Lv5类目',
    item_id        VARCHAR(100)                   COMMENT '宝贝ID',
    item_name      TEXT                           COMMENT '宝贝名称',
    item_image     TEXT                           COMMENT '宝贝图片URL',
    item_url       TEXT                           COMMENT '宝贝链接',
    ref_price      DECIMAL(12,2)                  COMMENT '参考价格',
    brand_raw      VARCHAR(200)                   COMMENT '平台原始品牌字段',
    shop_name      VARCHAR(200)                   COMMENT '宝贝店铺名称',
    sales_qty      INT                            COMMENT '销量',
    sales_amount   DECIMAL(14,2)                  COMMENT '销售额',
    price          DECIMAL(12,2)                  COMMENT '价格（人工补录或已处理文件带入）',
    brand_std      VARCHAR(100)                   COMMENT '标准化品牌（人工录入）',
    model_std      VARCHAR(100)                   COMMENT '标准化机型（人工录入）',
    extra_data     JSON                           COMMENT '扩展字段（保留）',
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    KEY idx_file_id (file_id),
    -- 去重唯一索引：同一商品同一月份同一平台只保留一条
    UNIQUE KEY uq_raw_dedup (item_id, month, platform),
    CONSTRAINT fk_raw_file FOREIGN KEY (file_id) REFERENCES upload_files(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='原始数据';

-- 清洗任务
CREATE TABLE IF NOT EXISTS clean_jobs (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    file_ids    JSON                              COMMENT '关联的 file_id 列表',
    rules       JSON                              COMMENT '清洗规则 {filter_brands, dedup}',
    status      VARCHAR(20)  DEFAULT 'done'       COMMENT 'done/error',
    row_in      INT          DEFAULT 0            COMMENT '输入行数',
    row_out     INT          DEFAULT 0            COMMENT '输出行数',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='清洗任务记录';

-- 清洗后数据
CREATE TABLE IF NOT EXISTS cleaned_data (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    raw_data_id    INT                            COMMENT '关联原始数据 id（可为空）',
    clean_job_id   INT          NOT NULL          COMMENT '关联 clean_jobs.id',
    platform       VARCHAR(50),
    month          INT,
    category_lv1   VARCHAR(100),
    category_lv2   VARCHAR(100),
    category_lv3   VARCHAR(100),
    category_lv4   VARCHAR(100),
    category_lv5   VARCHAR(100),
    item_id        VARCHAR(100),
    item_url       TEXT,
    item_name      TEXT,
    item_image     TEXT,
    ref_price      DECIMAL(12,2),
    brand_raw      VARCHAR(200),
    shop_name      VARCHAR(200),
    sales_qty      INT,
    sales_amount   DECIMAL(14,2),
    price          DECIMAL(12,2),
    brand_std      VARCHAR(100),
    model_std      VARCHAR(100),
    category_lv0   VARCHAR(100),
    calc_price     DECIMAL(12,2),
    corrected_sales_qty    INT,
    corrected_sales_amount DECIMAL(14,2),
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP,
    KEY idx_clean_job_id (clean_job_id),
    CONSTRAINT fk_cleaned_job FOREIGN KEY (clean_job_id) REFERENCES clean_jobs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='清洗后数据';

-- ─────────────────────────────────────────────────────────────
-- 新增表（3 张）
-- ─────────────────────────────────────────────────────────────

-- 元数据规格配置（对应 Excel 模版"元数据" sheet）
CREATE TABLE IF NOT EXISTS metadata_specs (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    category_code  VARCHAR(100) NOT NULL          COMMENT '品类码',
    spec_name      VARCHAR(200) NOT NULL          COMMENT '规格名称',
    spec_type      VARCHAR(50)  NOT NULL          COMMENT '规格类型（数值型/文本型等）',
    spec_values    TEXT                           COMMENT '规格可选值，逗号分隔，如 2.0,2.1,3.1',
    required       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否必填 1=是 0=否',
    decimal_places INT          DEFAULT NULL      COMMENT '保留小数位数（数值型有效）',
    single_select  TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '是否单选 1=是 0=否',
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_category_spec (category_code, spec_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='元数据规格配置';

-- 型号主信息（对应 Excel 模版"型号" sheet）
-- 唯一键：brand_code + model_code（品类码已移除）
CREATE TABLE IF NOT EXISTS models (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    brand_code    VARCHAR(100) NOT NULL           COMMENT '品牌码',
    model_code    VARCHAR(100) NOT NULL           COMMENT '型号码',
    category_name VARCHAR(200)                    COMMENT '品类名称',
    brand_name    VARCHAR(200)                    COMMENT '品牌名称',
    model_name    VARCHAR(200)                    COMMENT '型号名称',
    launch_year   INT                             COMMENT '上市年',
    launch_month  INT                             COMMENT '上市月',
    launch_week   INT                             COMMENT '上市周',
    launch_price  DECIMAL(12,2)                   COMMENT '上市价格',
    url           TEXT                            COMMENT '网址',
    created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_model (brand_code, model_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='型号主信息';

-- 型号规格参数（对应 Excel 模版"型号规格" sheet）
-- spec_type 已移除，规格类型信息存于元数据表
CREATE TABLE IF NOT EXISTS model_specs (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    model_id   INT          NOT NULL              COMMENT '关联 models.id',
    spec_name  VARCHAR(200) NOT NULL              COMMENT '规格名称',
    spec_value TEXT                               COMMENT '规格值（多选用英文逗号分隔）',
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_model_id (model_id),
    CONSTRAINT fk_model_spec FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='型号规格参数';

-- =============================================================
-- 线上库迁移脚本（已有数据库执行此部分，全新建库可忽略）
-- 执行前建议先备份：mysqldump luotu models model_specs > backup.sql
-- =============================================================

-- 1. 清理 models 表中因旧 category_code 产生的重复记录
--    保留每组 (brand_code, model_code) 中 id 最小的那条
DELETE m FROM models m
INNER JOIN (
    SELECT MIN(id) AS keep_id, brand_code, model_code
    FROM models
    GROUP BY brand_code, model_code
    HAVING COUNT(*) > 1
) dup ON m.brand_code = dup.brand_code
      AND m.model_code = dup.model_code
      AND m.id > dup.keep_id;

-- 2. 删除旧的唯一索引（三列）
ALTER TABLE models DROP INDEX uq_model;

-- 3. 删除 category_code 列
ALTER TABLE models DROP COLUMN category_code;

-- 4. 添加新唯一索引（两列）
ALTER TABLE models ADD UNIQUE KEY uq_model (brand_code, model_code);

-- 5. 删除 model_specs 的 spec_type 列
ALTER TABLE model_specs DROP COLUMN spec_type;

-- =============================================================
-- 新增表：match_results（型号匹配结果，全新库直接建，已有库执行此段）
-- =============================================================

CREATE TABLE IF NOT EXISTS match_results (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    clean_job_id INT NOT NULL           COMMENT '关联清洗任务 clean_jobs.id',
    raw_data_id  INT NOT NULL           COMMENT '关联原始数据 raw_data.id',
    model_id     INT                    COMMENT '匹配到的型号 models.id（NULL=未匹配）',
    match_status VARCHAR(20) NOT NULL DEFAULT 'pending'
                                       COMMENT 'matched/pending/confirmed/excluded',
    matched_by   VARCHAR(20) NOT NULL DEFAULT 'auto'
                                       COMMENT 'auto=自动匹配 manual=人工确认',
    match_source VARCHAR(20)           COMMENT 's1/s2/s3/s4=自动匹配步骤 manual=人工',
    price_flag VARCHAR(20) NULL COMMENT 'ok/high/low/no_history',
    price_ref DECIMAL(10,2) NULL COMMENT '参考均价',
    sales_coefficient DECIMAL(7,4) NULL COMMENT '销量调整系数',
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_match_clean_job (clean_job_id),
    KEY idx_match_raw_data  (raw_data_id),
    KEY idx_match_model     (model_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='型号匹配结果';

-- P4: 匹配候选型号（top-5，用于多候选展示）
CREATE TABLE IF NOT EXISTS match_result_candidates (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    match_result_id INT NOT NULL                   COMMENT '关联 match_results.id',
    model_id        INT NOT NULL                   COMMENT '候选型号 models.id',
    match_source    VARCHAR(20)                    COMMENT '命中阶段 s1/s2/s3/s4',
    score           INT NOT NULL                   COMMENT '命中长度分值',
    rank            INT NOT NULL                   COMMENT '排名（1=最优）',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_mrc_match_result_id (match_result_id),
    CONSTRAINT fk_mrc_match_result FOREIGN KEY (match_result_id) REFERENCES match_results(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='匹配候选型号';

CREATE TABLE IF NOT EXISTS correction_rules (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    category_code VARCHAR(100),
    brand_code    VARCHAR(100),
    model_id      INT,
    attr_name     VARCHAR(200),
    attr_value    VARCHAR(200),
    target        ENUM('sales_qty', 'sales_amount', 'both') NOT NULL,
    rule_type     ENUM('multiply', 'offset') NOT NULL,
    value         DECIMAL(12,4) NOT NULL,
    priority      INT NOT NULL DEFAULT 100,
    is_active     TINYINT NOT NULL DEFAULT 1,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='修正规则';

-- 发布任务记录（存于 luotu 处理库）
CREATE TABLE IF NOT EXISTS publish_jobs (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    clean_job_id INT NOT NULL           COMMENT '关联清洗任务',
    status       VARCHAR(20) NOT NULL DEFAULT 'done' COMMENT 'done/error',
    published_count INT DEFAULT 0      COMMENT '本次发布写入条数',
    note         VARCHAR(500)          COMMENT '备注',
    created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_publish_clean_job (clean_job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='发布任务记录';

-- 用户表（登录账号，默认创建 admin/luotu123）
CREATE TABLE IF NOT EXISTS users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    username        VARCHAR(100) NOT NULL UNIQUE COMMENT '用户名',
    hashed_password VARCHAR(200) NOT NULL        COMMENT 'bcrypt 哈希密码',
    is_active       TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '是否启用',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='登录用户';

-- 异步导出任务记录
CREATE TABLE IF NOT EXISTS export_jobs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    clean_job_id    INT          NOT NULL               COMMENT '关联清洗任务',
    filename_prefix VARCHAR(255) NOT NULL DEFAULT '已处理数据' COMMENT '文件名前缀',
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending' COMMENT 'pending/running/done/error',
    filename        VARCHAR(500)                        COMMENT '生成的文件名',
    token           VARCHAR(64)                         COMMENT '下载 token',
    rows            INT                                 COMMENT '已匹配行数',
    pending_rows    INT                                 COMMENT '待确认行数',
    error_msg       TEXT                                COMMENT '失败原因',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_export_clean_job (clean_job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='异步导出任务';

-- =============================================================
-- luotu_analytics 分析库（同一 MySQL 实例，独立 database）
-- =============================================================

CREATE DATABASE IF NOT EXISTS luotu_analytics DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE luotu_analytics;

-- 已发布商品宽表（基础字段，无规格列）
CREATE TABLE IF NOT EXISTS published_items (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    publish_job_id INT          NOT NULL          COMMENT '关联 luotu.publish_jobs.id',
    clean_job_id   INT          NOT NULL          COMMENT '关联 luotu.clean_jobs.id',
    match_result_id INT         NOT NULL          COMMENT '关联 luotu.match_results.id',
    -- 商品基础信息
    platform       VARCHAR(50)                    COMMENT '平台',
    month          INT                            COMMENT '月份 202507',
    category_lv1   VARCHAR(100),
    category_lv2   VARCHAR(100),
    category_lv3   VARCHAR(100),
    category_lv4   VARCHAR(100),
    category_lv5   VARCHAR(100),
    item_id        VARCHAR(100),
    item_name      TEXT,
    item_image     TEXT,
    item_url       TEXT,
    ref_price      DECIMAL(12,2),
    shop_name      VARCHAR(200),
    sales_qty      INT,
    sales_amount   DECIMAL(14,2),
    price          DECIMAL(12,2),
    -- 标准化品牌/型号（来自 models 表）
    brand_code     VARCHAR(100)                   COMMENT '品牌码',
    brand_name     VARCHAR(200)                   COMMENT '品牌名称',
    model_code     VARCHAR(100)                   COMMENT '型号码',
    model_name     VARCHAR(200)                   COMMENT '型号名称',
    category_name  VARCHAR(200)                   COMMENT '型号所属品类',
    -- P1 扩展字段
    category_lv0   VARCHAR(100)                   COMMENT '顶级类目',
    calc_price     DECIMAL(12,2)                  COMMENT '计算价格',
    corrected_sales_qty    INT                    COMMENT '修正销量',
    corrected_sales_amount DECIMAL(14,2)          COMMENT '修正销售额',
    -- 发布时间
    published_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_pub_platform  (platform),
    KEY idx_pub_month     (month),
    KEY idx_pub_brand     (brand_code),
    KEY idx_pub_model     (model_code),
    KEY idx_pub_category  (category_name),
    KEY idx_pub_job       (publish_job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='已发布商品宽表';

-- 已发布商品规格（EAV，按品类动态扩展）
CREATE TABLE IF NOT EXISTS published_item_specs (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    published_item_id  INT          NOT NULL  COMMENT '关联 published_items.id',
    spec_name          VARCHAR(200) NOT NULL  COMMENT '规格名称',
    spec_value         TEXT                  COMMENT '规格值',
    KEY idx_spec_item  (published_item_id),
    KEY idx_spec_name  (spec_name(50))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='已发布商品规格(EAV)';

-- 新增 match_source 列（记录命中步骤：s1/s2/s3/s4/manual）
ALTER TABLE luotu.match_results
    ADD COLUMN IF NOT EXISTS match_source VARCHAR(20) DEFAULT NULL
        COMMENT 's1/s2/s3/s4=自动匹配步骤 manual=人工' AFTER matched_by;

-- =============================================================
-- 品类受控词表（categories）及预置 24 条数据
-- =============================================================
USE luotu;

CREATE TABLE IF NOT EXISTS categories (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    code        VARCHAR(50)  NOT NULL UNIQUE COMMENT '品类码，如 soundbar',
    name        VARCHAR(100) NOT NULL        COMMENT '显示名称，如 回音壁',
    parent_code VARCHAR(50)  NULL            COMMENT '父品类码，NULL 表示顶级品类',
    sort_order  INT          NOT NULL DEFAULT 0 COMMENT '排序值，越小越靠前',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='品类受控词表';

INSERT IGNORE INTO categories (code, name) VALUES
    ('tv',             '电视'),
    ('monitor',        '显示器'),
    ('laptop',         '笔记本'),
    ('tablet',         '智能平板'),
    ('edu_tablet',     '学习平板'),
    ('eink_tablet',    '电子纸平板'),
    ('word_card',      '单词卡'),
    ('dict_pen',       '词典笔'),
    ('mind_machine',   '思维机'),
    ('projector',      '投影仪'),
    ('mobile_screen',  '移动智慧屏'),
    ('smart_speaker',  '智能音箱'),
    ('bt_speaker',     '无线蓝牙音箱'),
    ('soundbar',       '回音壁'),
    ('headphone',      '耳机'),
    ('smart_lock',     '智能门锁'),
    ('camera',         '监控摄像头'),
    ('video_doorbell', '可视门铃'),
    ('router',         '路由器'),
    ('dashcam',        '行车记录仪'),
    ('power_bank',     '移动电源'),
    ('smartwatch',     '智能手表'),
    ('band',           '手环'),
    ('vrar',           'VRAR');

-- 干扰词库（P1 规则引擎）
CREATE TABLE IF NOT EXISTS noise_words (
  `id`            INT AUTO_INCREMENT PRIMARY KEY,
  `keyword`       VARCHAR(200) NOT NULL              COMMENT '干扰关键词',
  `match_field`   VARCHAR(20)  NOT NULL DEFAULT 'item_name' COMMENT 'item_name/shop_name/brand_raw',
  `is_active`     TINYINT      NOT NULL DEFAULT 1    COMMENT '1=启用 0=禁用',
  `created_by`    VARCHAR(50)  DEFAULT NULL          COMMENT '创建人',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `category_code` varchar(50)  DEFAULT NULL          COMMENT '品类码，NULL=全局',
  UNIQUE KEY uq_noise_keyword_field (keyword, match_field),
  KEY ix_noise_words_category_code (category_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='干扰词库';

-- Alembic 版本记录：与 init.sql 建表结构对应的迁移链终点
-- 新环境初始化时直接标记为当前最新，后续增量迁移正常执行
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT IGNORE INTO alembic_version (version_num) VALUES ('p7a1b2c3d4e5');

-- ── P8: Dispatch Tables ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS dispatch_rules (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    category_code    VARCHAR(50)  NOT NULL,
    platform         VARCHAR(50),
    field            VARCHAR(50)  NOT NULL,
    match_type       VARCHAR(20)  NOT NULL,
    value            VARCHAR(200) NOT NULL,
    item_name_keyword VARCHAR(200),
    priority         INT          NOT NULL DEFAULT 100,
    is_active        TINYINT      NOT NULL DEFAULT 1,
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_dispatch_rules_category_code (category_code),
    INDEX ix_dispatch_rules_priority (priority)
);

CREATE TABLE IF NOT EXISTS dispatch_batches (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    file_id          INT          NULL,
    status           VARCHAR(20)  NOT NULL DEFAULT 'running',
    total_rows       INT,
    dispatched_rows  INT,
    unmatched_rows   INT,
    created_at       DATETIME     DEFAULT CURRENT_TIMESTAMP,
    finished_at      DATETIME,
    CONSTRAINT fk_db_file FOREIGN KEY (file_id) REFERENCES upload_files(id) ON DELETE SET NULL,
    INDEX ix_dispatch_batches_file_id (file_id)
);

CREATE TABLE IF NOT EXISTS dispatch_items (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    batch_id         INT          NOT NULL,
    raw_data_id      INT          NULL,
    category_code    VARCHAR(50)  NOT NULL,
    matched_rule_id  INT,
    UNIQUE KEY uq_dispatch_items_batch_row (batch_id, raw_data_id),
    CONSTRAINT fk_di_batch FOREIGN KEY (batch_id) REFERENCES dispatch_batches(id) ON DELETE CASCADE,
    CONSTRAINT fk_di_raw   FOREIGN KEY (raw_data_id) REFERENCES raw_data(id) ON DELETE SET NULL,
    INDEX ix_dispatch_items_batch_id (batch_id),
    INDEX ix_dispatch_items_category_code (category_code)
);

-- clean_jobs dispatch columns (idempotent)
ALTER TABLE clean_jobs
    ADD COLUMN IF NOT EXISTS dispatch_batch_id      INT  NULL,
    ADD COLUMN IF NOT EXISTS dispatch_category_code VARCHAR(50) NULL;

-- ─── P9: 列模板 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS column_templates (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    module          VARCHAR(20)  NOT NULL DEFAULT 'sales' COMMENT 'sales/model/url/attr',
    name            VARCHAR(100) NOT NULL            COMMENT '模板名称',
    platform        VARCHAR(50)                      COMMENT 'jd/tmall/taobao/suning/NULL=通用',
    col_fingerprint CHAR(64)                         COMMENT '列名集合 MD5',
    mapping         JSON         NOT NULL            COMMENT '{"原始列名": "标准字段"}',
    ignore_columns  JSON                             COMMENT '["列名", ...]',
    is_builtin      SMALLINT     NOT NULL DEFAULT 0  COMMENT '1=内置不可删',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_module_template_name (module, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='列映射模板';

INSERT IGNORE INTO column_templates (name, platform, col_fingerprint, mapping, ignore_columns, is_builtin)
VALUES
  ('京东月报', 'jd', NULL,
   '{"平台":"platform","月":"month","Lv0类目名称(逐月固定)":"category_lv0","Lv1类目名称(逐月固定)":"category_lv1","Lv2类目名称(逐月固定)":"category_lv2","宝贝ID":"item_id","宝贝名称":"item_name","宝贝图片":"item_image","宝贝链接":"item_url","参考价格":"ref_price","宝贝品牌(bid)":"brand_raw","宝贝店铺名称":"shop_name","销量":"sales_qty","销售额":"sales_amount","价格":"price","品牌":"brand_std","机型":"model_std"}',
   '[]', 1),
  ('天猫/淘宝月报', 'tmall', NULL,
   '{"平台":"platform","月":"month","Lv1类目名称(逐月固定)":"category_lv1","Lv2类目名称(逐月固定)":"category_lv2","Lv3类目名称(逐月固定)":"category_lv3","Lv4类目名称(逐月固定)":"category_lv4","Lv5类目名称(逐月固定)":"category_lv5","宝贝ID":"item_id","宝贝名称":"item_name","宝贝图片":"item_image","宝贝链接":"item_url","参考价格":"ref_price","宝贝品牌":"brand_raw","宝贝店铺名称":"shop_name","销量":"sales_qty","销售额":"sales_amount","价格":"price","品牌":"brand_std","机型":"model_std"}',
   '[]', 1);

ALTER TABLE upload_files ADD COLUMN IF NOT EXISTS template_id INT NULL COMMENT '本次上传使用的列模板 ID';

UPDATE alembic_version SET version_num = 'p11a1b2c3d4e5';
