# User-assigned identity shared by both timer functions. One identity, RBAC-scoped per
# resource, is simpler to audit than per-function system identities.

resource "azurerm_user_assigned_identity" "function" {
  name                = "id-${local.name}-func"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}
