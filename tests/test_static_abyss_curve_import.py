# 验证同版深渊曲线同时可供赛季表和公共 Buff 求值读取。
import sqlite3
import unittest

from tools.game_data.static_database_catalog_imports import CatalogImportMixin


class AbyssCurveImportTests(unittest.TestCase):
    def test_abyss_curve_keeps_official_path_and_missing_role_scope_is_allowed(self):
        class Probe(CatalogImportMixin):
            character_effect_curve_rows = ()

            def source_row_id(self, table, row):
                return 1

        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript("""
            CREATE TABLE combat_curve(path,id,interpolation,default_value,before,after,source);
            CREATE TABLE combat_curve_point(path,id,ordinal,time,value);
        """)
        probe = Probe()
        probe.connection = conn
        probe.rows = {"abyss_buff_curves": {"test": {
            "Keys": [{"Time": 1, "Value": 0.45}],
            "InterpMode": "RCIM_Constant", "PreInfinityExtrap": "RCCE_Constant",
            "PostInfinityExtrap": "RCCE_Constant",
        }}}
        probe._import_combat_curves()
        self.assertEqual(conn.execute("SELECT path,id,time,value FROM combat_curve_point").fetchone(),
                         ("/Game/DataAssets/DataAssetSet/Abyss/CT_AbyssBuff", "test", 1.0, 0.45))
        probe.rows = {}
        probe._import_combat_curves()
        self.assertEqual(conn.execute("SELECT count(*) FROM combat_curve_point").fetchone()[0], 1)
