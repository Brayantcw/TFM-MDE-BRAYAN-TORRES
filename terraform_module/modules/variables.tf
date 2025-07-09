variable "prefix" {
  description = "Prefix for naming resources"
  type        = string
}
variable "location" { type = string }
variable "rg_name" { type = string }
variable "vnet_cidr" { type = string }
variable "subnet_cidr" { type = string }
variable "dns_prefix" { type = string }
variable "node_count" { type = number; default = 1 }
variable "node_vm_size" { type = string; default = "Standard_B1s" }
