variable "region" {
  type    = string
  default = "us-east-1"
}

variable "plan_only" {
  type    = bool
  default = false
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "ami_id" {
  type    = string
  default = "ami-0c7217cdde317cfec"
}

variable "ssh_public_key" {
  type = string
}

variable "admin_cidr" {
  type = string

  validation {
    condition     = can(cidrhost(var.admin_cidr, 0))
    error_message = "admin_cidr must be a CIDR block, for example 203.0.113.10/32."
  }
}

variable "data_disk_size" {
  type    = number
  default = 20
}
