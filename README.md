# 书世界（图书蒸馏）

图书入库、PDF/OCR 解析、原文核对、知识与关系检索、营销资料、营销策划、选题策划及内容交付工作区。完整 Web 前后端、解析引擎、规则词库、数据库迁移辅助脚本和测试保存在本仓库。

## Docker 部署

需要 Docker Engine 和 Docker Compose 2.24 或更新版本。应用服务使用 Python 3.11，包含中文 PDF 字体和本地 OCR；当前业务状态使用持久化 JSON/JSONL，不要求 PostgreSQL 或 MinIO。

首次安装：

```sh
git clone https://github.com/EricJw0616/shushijie.git
cd shushijie
mkdir -p runtime
cp deploy/app.env.example runtime/app.env
# 按需填写 runtime/app.env 中的模型配置，然后启动。
docker compose up -d --build
```

默认访问 `http://服务器IP:8943`。之后在仓库目录更新只需：

```sh
git pull
docker compose up -d --build
```

当前服务器部署约定：代码 `/opt/shushijie`，持久数据 `/opt/shushijie-data`，端口 `8943`。仓库根目录未跟踪的 `.env` 设置 `BOOKWORLD_DATA_DIR`、`BOOKWORLD_HOST`、`BOOKWORLD_PORT`；实际模型配置存放在数据目录的 `app.env`，不进入 Git 或镜像。

首次构建下载较慢时，可在根目录 `.env` 配置公共镜像地址 `BOOKWORLD_DEBIAN_MIRROR`、`BOOKWORLD_DEBIAN_SECURITY_MIRROR`、`BOOKWORLD_PYPI_INDEX`；默认使用官方源。构建参数只用于公共依赖镜像，不应包含访问令牌。
已有系统依赖缓存时，使用 `BOOKWORLD_PYPI_INSTALL_INDEX` 仅覆盖 Python 包下载源，避免重新构建系统依赖层。

```sh
docker compose ps
docker compose logs --tail=100 app
```

更新前等待任务中心的运行任务完成。替换容器会中断正在解析或生成的任务；已保存的数据与核对记录保留。备份时应同时备份数据目录的 `app-data`、`out`、`library`、`config`、`lexicon`、`books` 以及私有 `app.env`。

## 存量来源检查

在本机或商用容器的运行副本中执行。商用容器使用 `docker compose exec -T app python ...` 调用相同命令。

- `python scripts/plan_source_repairs.py` 检查全库的章节与段落锚点变化。增加 `--verify-numbers` 对照 PDF 原件。确认候选后，指定书码和原页使用 `--apply-numbers` 写入有唯一依据的数字修复。
- `python scripts/backfill_source_pages.py` 检查旧段落能否唯一定位到 PDF 原页。确认计划后在无写入任务的维护时段加 `--apply`，备份后补写页码。
- 章节或段落重新切分会影响已有引用，按计划核对受影响的项目和成果后再处理。保留运行数据备份和原有审校记录。

## 代码与数据

- `app/`：Web 服务、业务逻辑、前端、测试、字体与资源。
- `platform/engine/`：解析、OCR、提取、检索及生成引擎。
- `platform/config/`、`lexicon/`：默认规则及词库；运行副本持久化，只在缺文件时补默认值。
- `db/`、`scripts/`、`requirements-pg.txt`：PostgreSQL 迁移与验证工具。
- `deploy/docker-compose.yml`：可选的旧版 PostgreSQL/MinIO 基础设施配置，与根目录应用 Compose 分开。
- [应用功能与本地开发说明](app/README.md)

当前书库的原稿、用户项目、审核记录、上传文件、运行日志、本机备份、环境文件与 SSH 私钥均不进入公开仓库。仓库保留历史开发示例和测试样本。迁移已有数据时，可用 `deploy/relocate_data.py` 在服务器副本内转换旧机器的绝对路径；默认只检查，明确加 `--apply` 才写入，并保留修改前备份。

Linux 支持网页功能；小红书“原版桌面启动”仅适用于本机 Mac。模型生成、热点与作品检索需要服务器能访问已配置的外部服务；OCR 在容器内运行。部分历史研究脚本依赖本机样本文档，不属于 Web 服务启动路径。
