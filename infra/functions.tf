# Flex Consumption Function App, per ITD-003. Two timer triggers (CSV scan, API pull) run
# in the same app; schedules are app settings so they stay configurable without a redeploy.

resource "azurerm_service_plan" "functions" {
  name                = "asp-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  os_type             = "Linux"
  sku_name            = "FC1"
  tags                = local.tags
}

resource "azurerm_function_app_flex_consumption" "main" {
  name                = "func-${local.name}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  service_plan_id     = azurerm_service_plan.functions.id

  storage_container_type            = "blobContainer"
  storage_container_endpoint        = "${azurerm_storage_account.functions.primary_blob_endpoint}${azurerm_storage_container.function_deployments.name}"
  storage_authentication_type       = "UserAssignedIdentity"
  storage_user_assigned_identity_id = azurerm_user_assigned_identity.function.id

  runtime_name    = "python"
  runtime_version = var.python_version

  instance_memory_in_mb  = var.instance_memory_mb
  maximum_instance_count = var.maximum_instance_count

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.function.id]
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.main.connection_string
  }

  app_settings = {
    FUNCTIONS_WORKER_RUNTIME = "python"

    BLOB_LANDING_CONTAINER    = azurerm_storage_container.landing.name
    BLOB_PROCESSED_CONTAINER  = azurerm_storage_container.processed.name
    BLOB_QUARANTINE_CONTAINER = azurerm_storage_container.quarantine.name
    STORAGE_ACCOUNT_NAME      = azurerm_storage_account.data.name
    AZURE_CLIENT_ID           = azurerm_user_assigned_identity.function.client_id

    PG_HOST                 = azurerm_postgresql_flexible_server.main.fqdn
    PG_PORT                 = "5432"
    PG_DATABASE             = azurerm_postgresql_flexible_server_database.students.name
    PG_USER                 = azurerm_user_assigned_identity.function.name
    PG_SSLMODE              = "require"
    PG_USE_MANAGED_IDENTITY = "true"

    API_BASE_URL      = var.api_base_url
    API_TOKEN_URL     = var.api_token_url
    API_CLIENT_ID     = var.api_client_id
    API_CLIENT_SECRET = "@Microsoft.KeyVault(VaultName=${azurerm_key_vault.main.name};SecretName=${var.api_client_secret_name})"
    API_AUTH_TYPE     = "oauth2_client_credentials"

    CSV_SCHEDULE_CRON       = var.csv_schedule_cron
    API_SCHEDULE_CRON       = var.api_schedule_cron
    CHUNK_SIZE              = tostring(var.chunk_size)
    RUN_STALE_AFTER_SECONDS = tostring(var.run_stale_after_seconds)
    LOG_LEVEL               = var.log_level
  }

  tags = local.tags

  depends_on = [
    azurerm_role_assignment.function_blob_data,
    azurerm_role_assignment.function_host_storage,
    azurerm_role_assignment.function_keyvault_secrets,
  ]
}

resource "azapi_update_resource" "function_key_vault_reference_identity" {
  type        = "Microsoft.Web/sites@2025-03-01"
  resource_id = azurerm_function_app_flex_consumption.main.id

  body = {
    properties = {
      keyVaultReferenceIdentity = azurerm_user_assigned_identity.function.id
    }
  }
}

resource "azurerm_storage_container" "function_deployments" {
  name                  = "app-package"
  storage_account_id    = azurerm_storage_account.functions.id
  container_access_type = "private"
}
