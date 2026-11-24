# -*- coding: utf-8 -*-
"""按顺序执行 db/migrations/*.sql；Mac / Linux 通用。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIG = ROOT / 'db' / 'migrations'
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://book:book@127.0.0.1:5432/bookworld')


def main():
    dry = '--dry-run' in sys.argv
    files = sorted(MIG.glob('*.sql'))
    if not files:
        print('no migrations')
        return 1
    if dry:
        for f in files:
            print('would apply', f.name)
        return 0
    import psycopg
    from psycopg import ClientCursor

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())""")
        conn.commit()
        for f in files:
            cur = conn.execute('select 1 from schema_migrations where version=%s', (f.stem,))
            if cur.fetchone():
                print('skip', f.name)
                continue
            sql = f.read_text(encoding='utf-8')
            # ClientCursor 走 simple query，允许一个文件多条语句。
            with conn.cursor(cursor_factory=ClientCursor) as c:
                c.execute(sql)
            conn.execute('insert into schema_migrations(version) values (%s) on conflict do nothing', (f.stem,))
            conn.commit()
            print('applied', f.name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
