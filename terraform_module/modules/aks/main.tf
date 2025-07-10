resource "azurerm_kubernetes_cluster" "this" {
  name                = var.cluster_name
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = var.dns_prefix

  default_node_pool {
    name                   = "default"
    vm_size                = var.node_vm_size
    node_count             = var.node_count
    vnet_subnet_id         = var.subnet_id
    os_disk_size_gb        = var.os_disk_size_gb
    os_disk_type           = "Managed"
    type                   = "VirtualMachineScaleSets"
    enable_host_encryption = true # Azure platform-managed keys
  }
  identity {
    type = "SystemAssigned"
  }
  role_based_access_control_enabled = true
  addon_profile {
    kube_dashboard {
      enabled = false
    }
  }

  tags = {
    Environment = "Dev"
  }
}
