terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.71"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = "5d43fdfa-fcba-4fe1-8ee2-2a503c338062"
}

data "azurerm_client_config" "current" {}

resource "random_id" "prefix" {
  byte_length = 8
}

resource "azurerm_resource_group" "rg" {
  name     = var.resource_group_name
  location = var.location
}


resource "azurerm_virtual_network" "aks_vnet" {
  address_space       = ["10.52.0.0/16"]
  location            = azurerm_resource_group.rg.location
  name                = "${random_id.prefix.hex}-vn"
  resource_group_name = azurerm_resource_group.rg.name
}

resource "azurerm_subnet" "aks_subnet" {
  address_prefixes     = ["10.52.0.0/24"]
  name                 = "${random_id.prefix.hex}-sn"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.aks_vnet.name
}

module "aks" {
  source              = "./modules/aks"
  resource_group_name = azurerm_resource_group.rg.name
  location            = var.location
  dns_prefix          = var.cluster_prefix
  cluster_name        = var.cluster_name
  subnet_id           = azurerm_subnet.aks_subnet.id
  node_vm_size        = var.node_vm_size
  node_count          = var.node_count
  os_disk_size_gb     = var.os_disk_size_gb
}
