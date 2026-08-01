# Blob Storage: three containers (landing/processed/quarantine) plus the storage account
# the Function App itself needs for triggers and run state.

resource "azurerm_storage_account" "data" {
  name                             = "st${local.name_compact}${random_string.suffix.result}"
  resource_group_name              = azurerm_resource_group.main.name
  location                         = azurerm_resource_group.main.location
  account_tier                     = "Standard"
  account_replication_type         = var.storage_replication
  min_tls_version                  = "TLS1_2"
  shared_access_key_enabled        = false # Managed Identity / RBAC only, no account keys
  cross_tenant_replication_enabled = false

  blob_properties {
    delete_retention_policy {
      days = var.blob_retention_days
    }
  }

  tags = local.tags
}

resource "azurerm_storage_container" "landing" {
  name                  = "landing"
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "processed" {
  name                  = "processed"
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "quarantine" {
  name                  = "quarantine"
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

# Separate account for the Functions host (deployment package, triggers). Keeps host
# plumbing out of the data-plane account that holds student records.
resource "azurerm_storage_account" "functions" {
  name                      = "st${local.name_compact}func${random_string.suffix.result}"
  resource_group_name       = azurerm_resource_group.main.name
  location                  = azurerm_resource_group.main.location
  account_tier              = "Standard"
  account_replication_type  = "LRS"
  min_tls_version           = "TLS1_2"
  shared_access_key_enabled = true # required by the Functions host runtime today

  tags = local.tags
}

# Least privilege: the function identity can read/write blobs in the data account,
# and only what the Functions host itself needs on the host account.
resource "azurerm_role_assignment" "function_blob_data" {
  scope                = azurerm_storage_account.data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.function.principal_id
}

resource "azurerm_role_assignment" "function_host_storage" {
  scope                = azurerm_storage_account.functions.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = azurerm_user_assigned_identity.function.principal_id
}
