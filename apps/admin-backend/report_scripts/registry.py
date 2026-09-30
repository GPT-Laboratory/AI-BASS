from __future__ import annotations

from .prompt_category_report import PromptCategoryReport
from .prompt_volume_monthly_report import PromptVolumeMonthlyReport


_SCRIPTS = {
    PromptCategoryReport.script_id: PromptCategoryReport(),
    PromptVolumeMonthlyReport.script_id: PromptVolumeMonthlyReport(),
}


def list_report_scripts():
    return [script.describe() for script in _SCRIPTS.values()]


def run_report_script(script_id: str, context: dict, params: dict | None = None):
    script = _SCRIPTS.get(script_id)
    if not script:
        raise KeyError(f"Unknown report script: {script_id}")
    return script.run(context=context, params=params or {})
