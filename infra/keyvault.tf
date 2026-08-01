# Key Vault holds the one real secret the pipeline needs: the vendor API client secret.
# The database uses Managed Identity, so no DB password is stored here.

resource "azurerm_key_vault" "main" {
  name                          = "kv-${local.name}-${random_string.suffix.result}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  soft_delete_retention_days    = 7
  rbac_authorization_enabled    = true
  public_network_access_enabled = var.allow_public_network_access

  tags = local.tags
}

resource "azurerm_role_assignment" "function_keyvault_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.function.principal_id
}

resource "azurerm_role_assignment" "deploy_keyvault_secrets" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# The secret VALUE is never set by Terraform. Populate it out of band:
#   az keyvault secret set --vault-name <name> --name api-client-secret --value <value>
resource "azurerm_key_vault_secret" "api_client_secret_placeholder" {
  name         = var.api_client_secret_name
  value        = "REPLACE_ME_VIA_AZ_CLI_OR_PIPELINE_NOT_TERRAFORM"
  key_vault_id = azurerm_key_vault.main.id

  lifecycle {
    ignore_changes = [value] # Terraform sets the placeholder once; ops rotates the real value
  }

  depends_on = [
    azurerm_role_assignment.deploy_keyvault_secrets,
    azurerm_role_assignment.function_keyvault_secrets,
  ]
}
