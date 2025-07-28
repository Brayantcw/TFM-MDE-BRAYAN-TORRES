resource "azurerm_kubernetes_cluster" "this" {
  name                = var.cluster_name
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = var.dns_prefix

  default_node_pool {
    name            = "default"
    vm_size         = var.node_vm_size
    node_count      = var.node_count
    vnet_subnet_id  = var.subnet_id
    os_disk_size_gb = var.os_disk_size_gb
    os_disk_type    = "Managed"
    type            = "VirtualMachineScaleSets"
  }

  network_profile {
    network_plugin = "azure"
    network_policy = "azure"
  }

  identity {
    type = "SystemAssigned"
  }

  dynamic "ingress_application_gateway" {
    for_each = var.enable_ingress ? [1] : []
    content {
      gateway_id = var.app_gateway_id
    }
  }

  role_based_access_control_enabled = true
  tags = {
    Environment = "Dev"
  }
}

# Grant Network Contributor permissions to AGIC identity
resource "azurerm_role_assignment" "agic_network_contributor" {
  count                = var.enable_ingress ? 1 : 0
  scope                = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}"
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_kubernetes_cluster.this.ingress_application_gateway[0].ingress_application_gateway_identity[0].object_id
}

# Grant Contributor permissions to AGIC identity on Application Gateway
resource "azurerm_role_assignment" "agic_app_gateway_contributor" {
  count                = var.enable_ingress ? 1 : 0
  scope                = var.app_gateway_id
  role_definition_name = "Contributor"
  principal_id         = azurerm_kubernetes_cluster.this.ingress_application_gateway[0].ingress_application_gateway_identity[0].object_id
}

# Grant Reader permissions to AGIC identity on Resource Group
resource "azurerm_role_assignment" "agic_resource_group_reader" {
  count                = var.enable_ingress ? 1 : 0
  scope                = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${var.resource_group_name}"
  role_definition_name = "Reader"
  principal_id         = azurerm_kubernetes_cluster.this.ingress_application_gateway[0].ingress_application_gateway_identity[0].object_id
}

# Data source for current client config
data "azurerm_client_config" "current" {}
