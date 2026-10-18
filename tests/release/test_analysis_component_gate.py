# 验证发行分析组件使用统一版本，同时拒绝能力缺失与文件身份漂移。
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from src.integrations.nte_analysis_core import ENGINE_VERSION
from tools.release.app_bundle_validation import validate_analysis_component


class AnalysisComponentGateTests(unittest.TestCase):
    def test_current_component_and_invalid_delivery_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            binary, metadata = root / 'nte-analysis-core.exe', root / 'component.json'
            binary.write_bytes(b'synthetic component; never executed')
            manifest = {
                'engine': 'nte-analysis-core', 'engine_version': ENGINE_VERSION,
                'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'capabilities': ['battle_page_v1', 'main_static_catalog_v1', 'allocation_v2',
                                 'allocation_blueprints_v1', 'damage_allocation_v1',
                                 'equipment_scoring_v1', 'battle_axis_team_v1', 'battle_axis_fixed_team_v1'],
            }
            metadata.write_text(json.dumps(manifest), encoding='utf-8')
            validate_analysis_component(binary, metadata)
            for change in ({'engine_version': '0.0.0'}, {'capabilities': []}, {'sha256': '0' * 64}):
                with self.subTest(change=change):
                    metadata.write_text(json.dumps({**manifest, **change}), encoding='utf-8')
                    with self.assertRaises(RuntimeError):
                        validate_analysis_component(binary, metadata)
