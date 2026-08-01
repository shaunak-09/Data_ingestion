# PostgreSQL Flexible Server, per ITD-002. Entra-only auth: no password logins, no DB secret
# in Key Vault. The function identity is granted a database role at deploy time (see README).

resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "psql-${local.name}-${random_string.suffix.result}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = var.postgres_version
  sku_name                      = var.postgres_sku
  storage_mb                    = var.postgres_storage_mb
  public_network_access_enabled = var.allow_public_network_access
  zone                          = "1"

  authentication {
    active_directory_auth_enabled = true
    password_auth_enabled         = false
  }

  tags = local.tags

  lifecycle {
    ignore_changes = [zone] # Azure can reassign the zone on maintenance
  }
}

resource "azurerm_postgresql_flexible_server_active_directory_administrator" "main" {
  server_name         = azurerm_postgresql_flexible_server.main.name
  resource_group_name = azurerm_resource_group.main.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  object_id           = var.postgres_entra_admin_object_id
  principal_name      = var.postgres_entra_admin_principal_name
  principal_type      = var.postgres_entra_admin_principal_type
}

# Lets local developer IPs be added without editing this file. Empty by default.
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  count            = var.allow_public_network_access ? 1 : 0
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_database" "students" {
  name      = var.database_name
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "utf8"
}
