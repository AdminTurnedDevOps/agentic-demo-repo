TOOL_TO_OBJECT = {
    "read_budget": "tool:finance/read_budget",
    "create_forecast_ticket": "tool:finance/create_forecast_ticket",
    "get_deploy_status": "tool:engineering/get_deploy_status",
    "restart_staging_service": "tool:engineering/restart_staging_service",
}

TOOL_TO_UPSTREAM = {
    "read_budget": "finance",
    "create_forecast_ticket": "finance",
    "get_deploy_status": "engineering",
    "restart_staging_service": "engineering",
}

OBJECT_TO_TOOL = {v: k for k, v in TOOL_TO_OBJECT.items()}
