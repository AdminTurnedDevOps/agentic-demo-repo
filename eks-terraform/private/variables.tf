variable "cluster_name" {
  type    = string
  default = "eks-private-public"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "vpc_id" {
  type    = string
  default = ""
}

variable "private_subnet_ids" {
  type    = list(string)
  default = []
  description = "List of private subnet IDs for the EKS cluster"
}

variable "public_subnet_ids" {
  type    = list(string)
  default = []
  description = "List of public subnet IDs for the EKS cluster"
}

variable "k8s_version" {
  type    = string
  default = "1.33"
}

variable "node_instance_type" {
  type    = string
  default = "c3.2xlarge"
}

variable "desired_capacity" {
  type    = number
  default = 3
}

variable "min_capacity" {
  type    = number
  default = 2
}

variable "max_capacity" {
  type    = number
  default = 8
}

variable "endpoint_private_access" {
  type    = bool
  default = true
  description = "Enable private API server endpoint"
}

variable "endpoint_public_access" {
  type    = bool
  default = true
  description = "Enable public API server endpoint for initial access"
}

variable "public_access_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
  description = "CIDR blocks that can access the public API server endpoint"
}
