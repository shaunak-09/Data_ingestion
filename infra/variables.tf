variable "project" {
  description = "Short project name used in every resource name."
  type        = string
  default     = "studentingest"
}

variable "environment" {
  description = "Environment name, for example dev or prod."
  type        = string
  default     = "dev"
}

variable "location" {
  description = "Azure region. Must support Functions Flex Consumption."
  type        = string
  default     = "eastus"
}

variable "tags" {
  description = "Extra tags added to every resource."
  type        = map(string)
  default     = {}
}

# ---------- Storage ----------

variable "storage_replication" {
  description = "Blob replication. Use GRS or ZRS in production."
  type        = string
  default     = "LRS"
}

variable "blob_retention_days" {
  description = "Soft-delete window for blobs. Supports reprocessing after a bad deploy."
  type        = number
  default     = 7
}

# ---------- Database ----------

variable "postgres_sku" {
  description = "Flexible Server SKU. B_Standard_B1ms is the cheapest; move to GP for real load."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "16"
}

variable "postgres_storage_mb" {
  description = "Server storage in MB."
  type        = number
  default     = 32768
}

variable "postgres_entra_admin_object_id" {
  description = "Object ID of the Entra user or group that administers the database."
  type        = string
}

variable "postgres_entra_admin_principal_name" {
  description = "UPN or group name of the Entra database administrator."
  type        = string
}

variable "postgres_entra_admin_principal_type" {
  description = "User, Group or ServicePrincipal."
  type        = string
  default     = "User"
}

variable "allow_public_network_access" {
  description = "Keep true for a quick start. Set false and add a private endpoint for production."
  type        = bool
  default     = true
}

variable "database_name" {
  description = "Application database."
  type        = string
  default     = "students"
}

# ---------- Functions ----------

variable "python_version" {
  description = "Python runtime version for the function app."
  type        = string
  default     = "3.11"
}

variable "instance_memory_mb" {
  description = "Flex Consumption instance size: 512, 2048 or 4096."
  type        = number
  default     = 2048

  validation {
    condition     = contains([512, 2048, 4096], var.instance_memory_mb)
    error_message = "instance_memory_mb must be 512, 2048 or 4096."
  }
}

variable "maximum_instance_count" {
  description = "Upper bound on concurrent Flex Consumption instances."
  type        = number
  default     = 40
}

# ---------- Pipeline configuration ----------

variable "csv_schedule_cron" {
  description = "NCRONTAB schedule for the CSV scan (sec min hour day month weekday)."
  type        = string
  default     = "0 0 2 * * *"
}

variable "api_schedule_cron" {
  description = "NCRONTAB schedule for the API pull."
  type        = string
  default     = "0 0 * * * *"
}

variable "api_base_url" {
  description = "Vendor API base URL."
  type        = string
  default     = ""
}

variable "api_token_url" {
  description = "Vendor OAuth2 token endpoint."
  type        = string
  default     = ""
}

variable "api_client_id" {
  description = "OAuth2 client id. The matching secret lives in Key Vault, never here."
  type        = string
  default     = ""
}

variable "api_client_secret_name" {
  description = "Key Vault secret name holding the OAuth2 client secret."
  type        = string
  default     = "api-client-secret"
}

variable "chunk_size" {
  description = "Records processed and committed per chunk."
  type        = number
  default     = 5000
}

variable "run_stale_after_seconds" {
  description = "Seconds before a running ingest_run can be reclaimed after an abrupt stop."
  type        = number
  default     = 3600
}

variable "log_level" {
  description = "Python log level."
  type        = string
  default     = "INFO"
}

# ---------- Monitoring ----------

variable "alert_email" {
  description = "Address that receives pipeline alerts."
  type        = string
}

variable "log_retention_days" {
  description = "Log Analytics retention."
  type        = number
  default     = 30
}

variable "quarantine_spike_threshold" {
  description = "Quarantined records in one hour that should raise an alert."
  type        = number
  default     = 100
}

variable "missed_run_window_hours" {
  description = "Hours without a successful CSV run before the missed-run alert fires."
  type        = number
  default     = 26
}

variable "api_missed_run_window_hours" {
  description = "Hours without a successful API run before the missed-run alert fires."
  type        = number
  default     = 2
}
