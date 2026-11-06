# 验证全角色规则直接生成和顶部参数绑定，手动规则不获得隐含智能计算。
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from src.features.scanning.intelligent_budget_bar import IntelligentBudgetBar
from src.domain.equipment.intelligent_rules import generated_rules, RULE_SCHEME_VERSION
from src.services.inventory import warehouse_rule_generation as module


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_manual_rules_leave_controls_disabled_and_cannot_acquire_hidden_actions(app):
    rules = [{'name':'人工保留', 'action':'keep', 'enabled':True}]
    before = deepcopy(rules)
    changed = Mock()
    bar = IntelligentBudgetBar(lambda:rules, changed)
    try:
        bar.refresh()
        assert not bar.amount.isEnabled() and not bar.grade.isEnabled()
        bar.amount.setValue(800)
        bar.grade.setCurrentIndex(bar.grade.findData('ACE'))
        assert rules == before
        changed.assert_not_called()
    finally:
        bar.close();bar.deleteLater();app.processEvents()


def test_active_controls_share_rule_values_and_disable_immediately(app):
    rules = generated_rules({'grade':'SS'}, strong_set_name=None)
    future = next(r for r in rules if r.get('smart_kind')=='future')
    grade = next(r for r in rules if r.get('smart_kind')=='grade')
    bar = IntelligentBudgetBar(lambda:rules, lambda:bar.refresh())
    try:
        bar.refresh()
        bar.amount.setValue(800)
        bar.grade.setCurrentIndex(bar.grade.findData('ACE'))
        assert future['target_inventory_size']==800 and grade['grade']=='ACE'
        assert future['intelligent']['edited'] and grade['intelligent']['edited']
        future['target_inventory_size']=1200;grade['grade']='SSS';bar.refresh()
        assert bar.amount.value()==1200 and bar.grade.currentData()=='SSS'
        future['enabled']=False;grade['enabled']=False;bar.refresh()
        assert not bar.amount.isEnabled() and not bar.grade.isEnabled()
        assert '未启用' in bar.hint.text()
        future['enabled']=True;grade['enabled']=True;bar.refresh()
        assert bar.amount.isEnabled() and bar.grade.currentData()=='SSS'
        bar.grade.setCurrentIndex(bar.grade.findData('none'))
        assert not grade['enabled'] and not bar.grade.isEnabled()
    finally:
        bar.close();bar.deleteLater();app.processEvents()


def test_generation_uses_static_catalog_and_keeps_top_settings_without_inventory(monkeypatch):
    dao = MagicMock()
    dao.__enter__.return_value=dao
    dao.list_suits.return_value=[{'suit_id':'Suit6','name_zh':'光套'}, {'suit_id':'Suit11','name_zh':'音速蓝刺猬'}]
    dao.list_shapes.return_value=[{'shape_id':'formal'}]
    monkeypatch.setattr(module,'StaticGameDataDao',lambda _:dao)
    monkeypatch.setattr(module,'legacy_shape_id',lambda _:'H_3')
    old = generated_rules({'grade':'SS','target_inventory_size':800},strong_set_name=None)
    before=deepcopy(old)
    result=module.generate_warehouse_rules('static',old)
    assert old==before and result['options']=={'rule_scheme_version':RULE_SCHEME_VERSION,'last_drive_grade':'SS'}
    assert next(r for r in result['rules'] if r.get('smart_kind')=='grade')['grade']=='SS'
    assert next(r for r in result['rules'] if r.get('smart_kind')=='future')['target_inventory_size']==800
    sonic=[r for r in result['rules'] if str((r.get('intelligent') or {}).get('key','')).startswith('combo:sonic:')]
    assert len(sonic)==5 and all(r['set_names']==['音速蓝刺猬'] for r in sonic)


def test_generation_flow_returns_draft_without_constructing_role_dialog(monkeypatch):
    from src.features.inventory.warehouse import recommendation_controller as controller
    context=SimpleNamespace(account=SimpleNamespace(active_account_id='test',user_database_path='account'),
        generation=1,paths=SimpleNamespace(equipment_allocation_database_path='static'))
    monkeypatch.setattr(controller,'generate_warehouse_rules',lambda *_,**kwargs:{'rules':['draft'],'options':{}})
    monkeypatch.setattr(controller,'RecommendationDialog',lambda *_args,**_kwargs:pytest.fail('生成不能打开角色选择弹窗'))
    flow=controller.WarehouseRecommendationFlow(context)
    assert flow.open(None,{'preserve_rules':[],'recommendation':{'last_drive_grade':'SS'}},None)=={'rules':['draft'],'options':{}}


def test_alternative_blueprints_are_deduplicated_and_not_added_as_simultaneous_demand():
    from src.solver.blueprint_utils import dedupe_blueprints_by_piece_signature
    from src.domain.equipment.warehouse_recommendation import shape_demands
    first={'set_pieces':['H_2','H_2'],'extra_pieces':['V_2']}
    second={'set_pieces':['H_2'],'extra_pieces':['V_2','V_2']}
    blueprints=dedupe_blueprints_by_piece_signature([first,deepcopy(first),second])
    assert len(blueprints)==2
    assert shape_demands({'角色':blueprints})=={'角色':{'H_2':1.5,'V_2':1.5}}


def test_first_grade_progress_waits_for_worker_and_cancel_discards_result(app):
    from threading import Event
    import time
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog
    from src.features.inventory.warehouse.rule_generation_progress import RuleGenerationProgress
    def wait(predicate):
        deadline=time.monotonic()+5
        while not predicate() and time.monotonic()<deadline:
            QTest.qWait(5)
        assert predicate()
    complete=RuleGenerationProgress(None,build=lambda **_:{'rules':['draft'],'options':{}})
    try:
        wait(lambda:not complete.is_running())
        assert complete.result()==QDialog.Accepted and complete.generated['rules']==['draft']
    finally:
        complete.close();complete.deleteLater();app.processEvents()
    started=Event()
    def build(cancel_check):
        started.set()
        while not cancel_check():
            time.sleep(.002)
        return {'rules':['stale']}
    cancelled=RuleGenerationProgress(None,build=build)
    try:
        wait(started.is_set)
        cancelled.reject()
        wait(lambda:not cancelled.is_running())
        assert cancelled.result()==QDialog.Rejected and cancelled.generated is None
    finally:
        cancelled.close();cancelled.deleteLater();app.processEvents()
