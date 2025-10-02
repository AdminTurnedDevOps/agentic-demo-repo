variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The GCP region"
  type        = string
  default     = "northamerica-northeast5"
}

variable "cluster_name" {
  description = "The name of the GKE cluster"
  type        = string
  default     = "ambient-gke-cluster"
}

variable "node_count" {
  description = "Initial number of nodes in the node pool"
  type        = number
  default     = 3
}

variable "machine_type" {
  description = "Machine type for the node pool"
  type        = string
  default     = "e2-highcpu-8"
}

variable "min_node_count" {
  description = "Minimum number of nodes in the node pool"
  type        = number
  default     = 1
}

variable "max_node_count" {
  description = "Maximum number of nodes in the node pool"
  type        = number
  default     = 3
}