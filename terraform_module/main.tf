terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.71"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.10"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.20"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = "5d43fdfa-fcba-4fe1-8ee2-2a503c338062"
}

provider "helm" {
  kubernetes = {
    host                   = module.aks.kube_config[0].host
    client_certificate     = base64decode(module.aks.kube_config[0].client_certificate)
    client_key             = base64decode(module.aks.kube_config[0].client_key)
    cluster_ca_certificate = base64decode(module.aks.kube_config[0].cluster_ca_certificate)
  }
}

provider "kubernetes" {
  host                   = module.aks.kube_config[0].host
  client_certificate     = base64decode(module.aks.kube_config[0].client_certificate)
  client_key             = base64decode(module.aks.kube_config[0].client_key)
  cluster_ca_certificate = base64decode(module.aks.kube_config[0].cluster_ca_certificate)
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

resource "azurerm_subnet" "app_gateway_subnet" {
  address_prefixes     = ["10.52.1.0/24"]
  name                 = "${random_id.prefix.hex}-appgw-sn"
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
  
  # Ingress configuration
  enable_ingress           = false
  app_gateway_subnet_id    = azurerm_subnet.app_gateway_subnet.id
}

module "helm_apps" {
  source = "./modules/helm-app"
  
  namespace        = "test-apps"
  app_name         = "nginx-demo"
  ingress_enabled  = true
  ingress_host     = "nginx-demo.local"
  replicas         = 2
  
  depends_on = [module.aks]
}

module "airflow" {
  source = "./modules/airflow"
  
  namespace      = "airflow"
  release_name   = "airflow"
  chart_version  = "1.18.0"
  
  custom_image = {
    repository = "brayanto/airflow-custom"
    tag        = "3.0.2"
    pullPolicy = "IfNotPresent"
  }
  
  admin_user = {
    username = "admin"
    password = "admin"
    email    = "admin@example.com"
  }
  
  ingress_enabled = true
  ingress_host    = "airflow.local"
  
  dags_storage_size    = "2Gi"
  logs_storage_size    = "5Gi"
  plugins_storage_size = "1Gi"
  
  depends_on = [module.aks]
}
