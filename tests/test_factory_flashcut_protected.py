import importlib.util
from pathlib import Path
import sqlite3


def test_protected_check_allows_new_rows_but_detects_modified_old_rows(tmp_path):
    from modules.factory.store import Database
    from modules.factory.domain.records import Record
    script=Path(__file__).resolve().parents[1]/'scripts/flashcut-protected-check.py'
    spec=importlib.util.spec_from_file_location('flashcut_protected',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    current=Database(tmp_path/'current.db')
    try:
        current.conn.execute("INSERT INTO meta(key,value) VALUES('test','safe')")
        # Use the real schema, including composite record identities.
        with current.uow() as u:
            u.records.put(Record(schema_version='fixture.v1',id='old',created_at='today'))
        baseline=sqlite3.connect(tmp_path/'baseline.db')
        current.conn.backup(baseline);baseline.close()
        with current.uow() as u:
            u.records.put(Record(schema_version='fixture.v1',id='new',created_at='today'))
        assert module.compare(tmp_path/'baseline.db',tmp_path/'current.db',tmp_path)['unchanged']
        current.conn.execute("UPDATE records SET body='{} ',version=2 WHERE id='old'")
        result=module.compare(tmp_path/'baseline.db',tmp_path/'current.db',tmp_path)
        assert not result['unchanged'] and result['tables']['records']['modified_or_missing']==1
    finally:current.close()
