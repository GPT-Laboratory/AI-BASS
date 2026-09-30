from __future__ import annotations

from collections import Counter, defaultdict
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from .report_utils import collect_filtered_prompt_logs, resolve_time_range


class PromptVolumeMonthlyReport:
    script_id = "prompt-volume-monthly-report"

    def describe(self):
        return {
            "id": self.script_id,
            "name": "Prompt Volume by Month",
            "output_format": "xlsx",
        }

    def run(self, context: dict, params: dict):
        mongo = context["mongo"]

        start_time, end_time = resolve_time_range(params)
        filtered = collect_filtered_prompt_logs(mongo, start_time, end_time, params)

        workbook = Workbook()
        summary_ws = workbook.active
        summary_ws.title = "Monthly counts"
        details_ws = workbook.create_sheet("Details")

        company_ids = filtered["company_ids"]
        company_id_by_user = filtered["company_id_by_user"]

        company_month_counts = defaultdict(Counter)
        all_months = set()

        for log in filtered["logs"]:
            metrics = log.get("metrics", {}) or {}
            company_id = metrics.get("company_id") or company_id_by_user.get(metrics.get("user_id"))
            if not company_id:
                continue
            timestamp = log.get("timestamp") or ""
            month_key = str(timestamp)[:7]
            if len(month_key) != 7:
                continue
            all_months.add(month_key)
            company_month_counts[company_id][month_key] += 1

        ordered_months = sorted(all_months)

        headers = ["Company ID", "Total prompts"] + ordered_months
        summary_ws.append(headers)
        self._style_header(summary_ws, 1)

        for company_id in sorted(company_ids.keys()):
            row = [company_id, sum(company_month_counts[company_id].values())]
            for month_key in ordered_months:
                row.append(company_month_counts[company_id].get(month_key, 0))
            summary_ws.append(row)

        total_row = ["All companies", sum(sum(counter.values()) for counter in company_month_counts.values())]
        for month_key in ordered_months:
            total_row.append(sum(company_month_counts[company_id].get(month_key, 0) for company_id in company_ids.keys()))
        summary_ws.append(total_row)

        details_ws.append(["Field", "Value"])
        self._style_header(details_ws, 1)
        details_ws.append(["Start time", start_time.isoformat()])
        details_ws.append(["End time", end_time.isoformat()])
        details_ws.append(["Environment filter", filtered["filters"].get("company_env") or "all"])
        details_ws.append(["Company filter", filtered["filters"].get("company_id") or "all"])
        details_ws.append(["User filter", filtered["filters"].get("user_id") or "all"])
        details_ws.append(["Log rows", len(filtered["logs"])])

        for ws in (summary_ws, details_ws):
            self._autosize_columns(ws)

        output = BytesIO()
        workbook.save(output)
        return {
            "content": output.getvalue(),
            "filename": f"prompt_volume_monthly_{start_time.strftime('%Y%m%d')}_{end_time.strftime('%Y%m%d')}.xlsx",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }

    def _style_header(self, worksheet, row_number: int):
        for cell in worksheet[row_number]:
            cell.font = Font(bold=True)

    def _autosize_columns(self, worksheet):
        for column_cells in worksheet.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter
            for cell in column_cells:
                try:
                    value = str(cell.value) if cell.value is not None else ""
                except Exception:
                    value = ""
                if len(value) > max_length:
                    max_length = len(value)
            worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 40)
