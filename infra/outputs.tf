output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "storage_account_name" {
  description = "Data account. Landing/processed/quarantine containers live here."
  value       = azurerm_storage_account.data.name
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.main.fqdn
}

output "postgres_database_name" {
  value = azurerm_postgresql_flexible_server_database.students.name
}

output "function_app_name" {
  value = azurerm_function_app_flex_consumption.main.name
}

output "function_app_identity_name" {
  description = "Grant this Entra name a role inside PostgreSQL after apply (see README)."
  value       = azurerm_user_assigned_identity.function.name
}

output "function_app_identity_principal_id" {
  value = azurerm_user_assigned_identity.function.principal_id
}

output "key_vault_name" {
  description = "Set the real API client secret here after apply (see README)."
  value       = azurerm_key_vault.main.name
}

output "application_insights_connection_string" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}
