# PostgreSQL 16 + pgvector

商用目标：**PostgreSQL 是唯一主库**。不用 SQLite，不用 FAISS 独立索引，向量走 `pgvector`。
Mac 开发和 Linux 服务器使用**同一份 compose、同一个 `DATABASE_URL`**，代码不分叉。

## 为什么不是 SQLite

`app/store.py` 最早的决定就是「文件型存储（无 SQLite）」，未来换 PostgreSQL。
SQLite 是单机文件库，并发写、备份、迁移、权限都不适合商用服务器；现在直接上 PostgreSQL，
本地和服务器同构，不做 SQLite 过渡。

## 目录

```
deploy/docker-compose.yml   # PostgreSQL 16 + pgvector + MinIO
db/migrations/001_init.sql  # 表、索引、HNSW
app/db.py                   # 连接池（psycopg3）
scripts/migrate_pg.py       # 执行迁移
scripts/import_to_pg.py     # 现有 JSON/JSONL 导入
scripts/verify_pg.py        # 行数 / 证据 / 悬空边校验
```

## Mac 开发（Docker Desktop）

```bash
cp .env.example .env
docker compose --env-file .env -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml ps

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-pg.txt

export DATABASE_URL=postgresql://book:book@127.0.0.1:5432/bookworld
python3 scripts/migrate_pg.py
python3 scripts/import_to_pg.py --dry-run
python3 scripts/import_to_pg.py
python3 scripts/verify_pg.py
```

Apple Silicon 上 `pgvector/pgvector:pg16` 是多架构镜像；如果拉取异常，再加
`platform: linux/amd64`（会走 Rosetta，慢但可用）。代码不需要改。

## Linux 服务器

同样的 compose：

```bash
docker compose --env-file .env -f deploy/docker-compose.yml up -d
```

或者用托管 PostgreSQL（RDS / Cloud SQL / 阿里云 RDS），要求：

- PostgreSQL 16；
- 能 `CREATE EXTENSION vector;` 和 `CREATE EXTENSION pg_trgm;`；
- `DATABASE_URL` 指向它，然后跑 `migrate_pg.py / import_to_pg.py / verify_pg.py`。

服务器上不要把 5432 直接暴露公网；用内网/安全组/反向代理。密码用强密码，`.env` 不进版本库。

## 常用检查

```bash
# 容器内 psql
docker compose -f deploy/docker-compose.yml exec db \
  psql -U book -d bookworld -c "select count(*) from kg_nodes;"

# 备份
docker compose -f deploy/docker-compose.yml exec -T db \
  pg_dump -U book -d bookworld -Fc > bookworld.dump

# 恢复
docker compose -f deploy/docker-compose.yml exec -T db \
  pg_restore -U book -d bookworld --clean --if-exists < bookworld.dump
```

## 迁移顺序

1. 起 PostgreSQL + pgvector；
2. `migrate_pg.py`；
3. `import_to_pg.py --dry-run` 看行数；
4. `import_to_pg.py`；
5. `verify_pg.py`；
6. 再接 `store.py` / `runner.py` / `kg_build.py`，最后切流；
7. 文件导出保留作回滚，但不作为主存储。

> 当前应用仍然跑文件版；这一步只建 PG 底座和导入，不切流，不影响现有页面。

## 对象存储

PDF/docx 原件不要进 PostgreSQL。上传原件放 MinIO/S3，`files.object_key` 存 key；
数据库只存元数据、锚点、图谱和向量。
