# 汇总极速装配完成结果与提示。
"""Compact, actionable summaries for the fast-equipment completion dialog."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def build_fast_apply_completion_summary(
    applied: Sequence[Mapping[str, Any]],
    *,
    mismatch_role_names: frozenset[str] = frozenset(),
    skipped_roles: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, str]:
    """Return dispatched equipment counts without claiming fragment verification.

    Equipment residual events are not a complete inventory view.  They remain
    useful for internal retry diagnostics, but presenting their absence or a
    partial match as a player-visible loadout result would be misleading.
    """

    del mismatch_role_names
    last_attempt = max((int(row.get("attempt_count") or 1) for row in applied), default=1)

    summary = f"已下发 {len(applied)} 个角色的配装"
    if last_attempt > 1:
        summary += f"（已进行至第 {last_attempt} 轮装配）"
    partial_count = sum(bool(row.get("skipped_assignments")) for row in applied)
    if partial_count:
        summary += f"，其中 {partial_count} 个为部分装配"
    if skipped_roles:
        summary += f"；{len(skipped_roles)} 个角色无可用装备，未发送指令"
    if not applied and skipped_roles:
        summary = "没有可用装备，未发送装配指令"
    lines = []
    for row in applied:
        role_name = str(row.get("role_name") or "未知角色")
        module_count = row.get("module_count")
        if module_count is None:
            detail = "已下发"
        else:
            detail = f"{int(module_count)} 个驱动"
            if row.get("core_count"):
                detail += " + 1 个核心"
        if row.get("skipped_assignments"):
            detail = f"部分装配，{detail}；{_skip_details(row)}"
        lines.append(f"• {role_name}：{detail}")
    for row in skipped_roles:
        lines.append(f"• {row.get('role_name') or '未知角色'}：未装配，{_skip_details(row)}")
    return summary, "\n".join(lines)


def _skip_details(row: Mapping[str, Any]) -> str:
    skipped = row.get("skipped_assignments") or ()
    virtual = sum(item.get("reason") == "virtual" for item in skipped)
    missing = sum(item.get("reason") == "missing" for item in skipped)
    reasons = []
    if virtual:
        reasons.append(f"虚拟占位 {virtual} 件")
    if missing:
        reasons.append(f"背包中不存在 {missing} 件")
    return "已跳过：" + "、".join(reasons)
