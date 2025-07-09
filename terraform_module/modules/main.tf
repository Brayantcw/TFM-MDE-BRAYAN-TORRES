resource "azurerm_resource_group" "this" {
  name     = var.rg_name
  location = var.location
}

resource "azurerm_virtual_network" "this" {
  name                = "${var.prefix}-vnet"
  address_space       = [var.vnet_cidr]
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_subnet" "this" {
  name                 = "${var.prefix}-snet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_cidr]
}

resource "azurerm_kubernetes_cluster" "this" {
  name                = "${var.prefix}-aks"
  location            = var.location
  resource_group_name = azurerm_resource_group.this.name
  sku_tier            = "Free"
  dns_prefix          = var.dns_prefix


  default_node_pool {
    name           = "system"
    node_count     = var.node_count
    vm_size        = var.node_vm_size
    vnet_subnet_id = azurerm_subnet.this.id
  }

  identity { type = "SystemAssigned" }
  network_profile { network_plugin = "azure"; load_balancer_sku = "standard" }
}

output "kube_config" {
  description = "Base64 encoded kubeconfig for ${var.prefix}"
  value       = azurerm_kubernetes_cluster.this.kube_config_raw
  sensitive   = true
}