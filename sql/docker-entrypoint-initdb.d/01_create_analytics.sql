-- 在 MySQL 容器首次启动时，创建分析库并授权 luotu 用户
CREATE DATABASE IF NOT EXISTS luotu_analytics
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

GRANT ALL PRIVILEGES ON luotu_analytics.* TO 'luotu'@'%';
FLUSH PRIVILEGES;
