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
    host                   = try(module.aks.kube_config[0].host, "")
    client_certificate     = try(base64decode(module.aks.kube_config[0].client_certificate), "")
    client_key             = try(base64decode(module.aks.kube_config[0].client_key), "")
    cluster_ca_certificate = try(base64decode(module.aks.kube_config[0].cluster_ca_certificate), "")
  }
}

provider "kubernetes" {
  host                   = try(module.aks.kube_config[0].host, "")
  client_certificate     = try(base64decode(module.aks.kube_config[0].client_certificate), "")
  client_key             = try(base64decode(module.aks.kube_config[0].client_key), "")
  cluster_ca_certificate = try(base64decode(module.aks.kube_config[0].cluster_ca_certificate), "")
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

resource "azurerm_public_ip" "app_gateway_pip" {
  allocation_method   = "Static"
  location            = azurerm_resource_group.rg.location
  name                = "${random_id.prefix.hex}-appgw-pip"
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "Standard"
  domain_name_label   = "appgw-${lower(random_id.prefix.hex)}"
}

resource "azurerm_application_gateway" "app_gateway" {
  location            = azurerm_resource_group.rg.location
  name                = "${random_id.prefix.hex}-appgw"
  resource_group_name = azurerm_resource_group.rg.name

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 2
  }

  gateway_ip_configuration {
    name      = "appGatewayIpConfig"
    subnet_id = azurerm_subnet.app_gateway_subnet.id
  }

  frontend_port {
    name = "port_80"
    port = 80
  }

  frontend_ip_configuration {
    name                 = "appGwPublicFrontendIp"
    public_ip_address_id = azurerm_public_ip.app_gateway_pip.id
  }

  backend_address_pool {
    name = "defaultaddresspool"
  }

  backend_http_settings {
    name                  = "defaulthttpsetting"
    cookie_based_affinity = "Disabled"
    port                  = 80
    protocol              = "Http"
    request_timeout       = 60
  }

  http_listener {
    name                           = "defaulthttplistener"
    frontend_ip_configuration_name = "appGwPublicFrontendIp"
    frontend_port_name             = "port_80"
    protocol                       = "Http"
  }

  request_routing_rule {
    name                       = "defaultroutingrule"
    rule_type                  = "Basic"
    http_listener_name         = "defaulthttplistener"
    backend_address_pool_name  = "defaultaddresspool"
    backend_http_settings_name = "defaulthttpsetting"
    priority                   = 1
  }

  lifecycle {
    ignore_changes = [
      backend_address_pool,
      backend_http_settings,
      http_listener,
      probe,
      request_routing_rule,
      url_path_map,
      ssl_certificate,
      redirect_configuration,
      autoscale_configuration
    ]
  }
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
  enable_ingress = true
  app_gateway_id = azurerm_application_gateway.app_gateway.id

  depends_on = [azurerm_application_gateway.app_gateway]
}

module "helm_apps" {
  source = "./modules/helm-app"

  namespace       = "test-apps"
  app_name        = "nginx-demo"
  ingress_enabled = false
  replicas        = 2

  depends_on = [module.aks]
}

module "airflow" {
  source = "./modules/airflow"

  namespace     = "airflow"
  release_name  = "airflow"
  chart_version = "1.18.0"

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

  ingress_enabled = false

  dags_storage_size    = "2Gi"
  logs_storage_size    = "5Gi"
  plugins_storage_size = "1Gi"

  depends_on = [module.aks]
}
