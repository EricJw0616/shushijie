# -*- coding: utf-8 -*-
"""导入后校验：行数、证据覆盖、悬空边、锚点缺失。"""
import os
import sys

URL = os.environ.get('DATABASE_URL', 'postgresql://book:book@127.0.0.1:5432/bookworld')


def main():
    import psycopg
    with psycopg.connect(URL) as conn:
        q = lambda sql: conn.execute(sql).fetchone()[0]
        print('books      ', q('select count(*) from books'))
        print('segments   ', q('select count(*) from segments'))
        print('cards      ', q('select count(*) from cards'))
        print('people     ', q('select count(*) from people'))
        print('entities   ', q('select count(*) from entities'))
        print('kg_nodes   ', q('select count(*) from kg_nodes'))
        print('kg_edges   ', q('select count(*) from kg_edges'))
        print('embeddings ', q('select count(*) from embeddings'))

        ev_total = q("select count(*) from kg_edges where kind <> 'in_book'")
        ev_with = q("select count(*) from kg_edges where kind <> 'in_book' and evidence_anchor <> ''")
        print('evidence   ', '%s/%s' % (ev_with, ev_total))

        dangling = q("""select count(*) from kg_edges e
            where not exists (select 1 from kg_nodes n where n.id = e.source_id)
               or not exists (select 1 from kg_nodes n where n.id = e.target_id)""")
        bad_anchor = q("""select count(*) from kg_edges e
            where e.evidence_anchor <> ''
              and not exists (select 1 from segments s where s.id = e.evidence_anchor)""")
        print('dangling   ', dangling)
        print('bad_anchor ', bad_anchor)
        if dangling or bad_anchor:
            print('FAIL')
            return 1
        print('OK')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
