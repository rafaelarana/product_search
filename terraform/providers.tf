# The provider reads auth from the CLI profile set via DATABRICKS_CONFIG_PROFILE
# or from explicit `profile = ...` below. We use the `azure-video` profile.
provider "databricks" {
  profile = var.databricks_profile
}
