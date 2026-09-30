class SettingsProvider:
    def __init__(self, db):
        self.settings_col = db["settings"]

    def get_task_prompt_template(self, task: str) -> str | None:
        doc = self.settings_col.find_one() or {}
        for p in doc.get("system_prompts", []):
            if p["task"] == task:
                return p["prompt"]
        return None

    def get_global_system_prompt(self) -> str | None:
        doc = self.settings_col.find_one() or {}
        return doc.get("global_system_prompt", "")

    def get_memory_generation_prompt(self) -> str | None:
        """Get the prompt used for memory generation from settings."""
        doc = self.settings_col.find_one() or {}
        return doc.get("memory_generation_prompt", "")

    def get_all_tasks(self) -> list[dict]:
        doc = self.settings_col.find_one() or {}
        return doc.get("system_prompts", []) if doc else []

    def get_task_by_name(self, task_name: str) -> dict | None:
        tasks = self.get_all_tasks()
        for task in tasks:
            if task["task"].lower() == task_name.lower():
                return task
        return None
