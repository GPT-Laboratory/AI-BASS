from __future__ import annotations

from datetime import datetime, timezone


def resolve_time_range(params: dict):
    start_time_raw = params.get("start_time")
    end_time_raw = params.get("end_time")

    start_time = parse_iso_datetime(start_time_raw) if start_time_raw else datetime(1970, 1, 1, tzinfo=timezone.utc)
    end_time = parse_iso_datetime(end_time_raw) if end_time_raw else datetime.now(timezone.utc)
    return start_time, end_time


def parse_iso_datetime(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def collect_filtered_prompt_logs(mongo, start_time: datetime, end_time: datetime, filters: dict):
    companies_col = mongo.db.companies
    users_col = mongo.db.users
    logs_col = mongo.db.log_entries

    filter_environment = filters.get("company_env")
    filter_company_id = filters.get("company_id")
    filter_user_id = filters.get("user_id")

    company_query = {}
    if filter_environment:
        company_query["environment"] = filter_environment
    if filter_company_id:
        company_query["_id"] = _safe_object_id(filter_company_id)

    companies = list(companies_col.find(company_query, {"_id": 1, "environment": 1}))
    company_ids = {str(company["_id"]): str(company["_id"]) for company in companies}
    allowed_company_ids = set(company_ids.keys())

    user_query = {}
    if allowed_company_ids:
        user_query["company_id"] = {"$in": list(allowed_company_ids)}
    elif filter_company_id or filter_environment:
        user_query["company_id"] = {"$in": []}

    if filter_user_id:
        user_query["phone_number"] = filter_user_id

    users = list(users_col.find(user_query, {"phone_number": 1, "company_id": 1}))
    company_id_by_user = {}
    for user in users:
        phone = user.get("phone_number")
        company_id = user.get("company_id")
        if phone and company_id:
            company_id_by_user[phone] = company_id

    user_ids = list(company_id_by_user.keys())

    log_query = {
        "timestamp": {
            "$gte": start_time.isoformat(),
            "$lte": end_time.isoformat(),
        },
        "question": {"$exists": True, "$ne": ""},
    }

    or_clauses = []
    if allowed_company_ids:
        or_clauses.append({"metrics.company_id": {"$in": list(allowed_company_ids)}})
    if user_ids:
        or_clauses.append({"metrics.user_id": {"$in": user_ids}})

    if filter_user_id:
        log_query["metrics.user_id"] = filter_user_id

    if filter_company_id:
        log_query["metrics.company_id"] = filter_company_id

    if filter_environment and not filter_company_id:
        if or_clauses:
            log_query["$or"] = or_clauses
        else:
            log_query["metrics.company_id"] = {"$in": []}
    elif not filter_company_id and not filter_user_id:
        if or_clauses:
            log_query["$or"] = or_clauses

    logs = list(
        logs_col.find(
            log_query,
            {
                "timestamp": 1,
                "question": 1,
                "metrics.company_id": 1,
                "metrics.user_id": 1,
            },
        ).sort("timestamp", 1)
    )

    return {
        "logs": logs,
        "company_ids": company_ids,
        "company_id_by_user": company_id_by_user,
        "filters": {
            "company_env": filter_environment,
            "company_id": filter_company_id,
            "user_id": filter_user_id,
        },
    }


def _safe_object_id(value):
    from bson.objectid import ObjectId

    try:
        return ObjectId(value)
    except Exception:
        return value
