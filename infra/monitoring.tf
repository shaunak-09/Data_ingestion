# App Insights for traces/metrics, plus the 3 alerts AGENTS.md requires: pipeline failure,
# quarantine spike, and missed run. Structured JSON logs (src/logging_setup.py) land in the
# `traces` table as JSON documents, so alerts parse the message payload.

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  tags                = local.tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "other"
  tags                = local.tags
}

resource "azurerm_monitor_action_group" "alerts" {
  name                = "ag-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "ingestalert"

  email_receiver {
    name          = "primary"
    email_address = var.alert_email
  }

  tags = local.tags
}

# 1. Pipeline failure: an invocation exception, or a run that logged run.failed / *_failed.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "pipeline_failure" {
  name                 = "alert-${local.name}-pipeline-failure"
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  evaluation_frequency = "PT5M"
  window_duration      = "PT5M"
  scopes               = [azurerm_application_insights.main.id]
  severity             = 1
  criteria {
    query                   = <<-KQL
      union traces, exceptions
      | extend body = parse_json(message)
      | extend event = tostring(body.event)
      | where event has_any ("job_failed", "sync_failed", "file_failed") or itemType == "exception"
      | summarize count()
    KQL
    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "GreaterThan"
  }
  action {
    action_groups = [azurerm_monitor_action_group.alerts.id]
  }
  tags = local.tags
}

# 2. Quarantine spike: too many bad records in one window points at an upstream problem.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "quarantine_spike" {
  name                 = "alert-${local.name}-quarantine-spike"
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  evaluation_frequency = "PT1H"
  window_duration      = "PT1H"
  scopes               = [azurerm_application_insights.main.id]
  severity             = 2
  criteria {
    query                   = <<-KQL
      traces
      | extend body = parse_json(message)
      | where tostring(body.event) == "quarantine.written"
      | summarize total = sum(toint(body.records))
    KQL
    time_aggregation_method = "Total"
    threshold               = var.quarantine_spike_threshold
    operator                = "GreaterThan"
  }
  action {
    action_groups = [azurerm_monitor_action_group.alerts.id]
  }
  tags = local.tags
}

# 3. Missed CSV run: the daily CSV timer did not finish inside the expected window.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "missed_csv_run" {
  name                 = "alert-${local.name}-missed-csv-run"
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  evaluation_frequency = "PT1H"
  window_duration      = "PT${var.missed_run_window_hours}H"
  scopes               = [azurerm_application_insights.main.id]
  severity             = 2
  criteria {
    query                   = <<-KQL
      traces
      | extend body = parse_json(message)
      | where tostring(body.event) == "trigger.csv_finished"
      | summarize count()
    KQL
    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "LessThanOrEqual"
  }
  action {
    action_groups = [azurerm_monitor_action_group.alerts.id]
  }
  tags = local.tags
}

# 4. Missed API run: the hourly API timer did not finish inside the expected window.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "missed_api_run" {
  name                 = "alert-${local.name}-missed-api-run"
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  evaluation_frequency = "PT1H"
  window_duration      = "PT${var.api_missed_run_window_hours}H"
  scopes               = [azurerm_application_insights.main.id]
  severity             = 2
  criteria {
    query                   = <<-KQL
      traces
      | extend body = parse_json(message)
      | where tostring(body.event) == "trigger.api_finished"
      | summarize count()
    KQL
    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "LessThanOrEqual"
  }
  action {
    action_groups = [azurerm_monitor_action_group.alerts.id]
  }
  tags = local.tags
}
