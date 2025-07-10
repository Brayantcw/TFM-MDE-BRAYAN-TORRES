variable "resource_group_name" { type = string }
variable "location"            { type = string }
variable "dns_prefix"          { type = string }
variable "cluster_name"        { type = string }
variable "subnet_id"           { type = string }
variable "node_vm_size"        { type = string }
variable "node_count"          { type = number }
variable "os_disk_size_gb"     { type = number }
