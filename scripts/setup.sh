#!/usr/bin/env bash
# =============================================================================
# Lumen — full project setup for a fresh workspace.
#
# Runs the build in dependency order:
#   1. Verify local tools          (databricks, terraform, uv, node, npm)
#   2. Databricks CLI profile       (verify auth; log in if needed)
#   3. Python venv via uv           (repo-root .venv that Terraform bootstrap uses)
#   4. terraform.tfvars             (from example; set profile + catalog)
#   5. terraform init + plan        (download providers, preview)
#   6. terraform apply              (only with --apply; provisions billable infra)
#   7. Print outputs                (app_url)
#
# Safe by default: steps 1–5 only. Provisioning (step 6) requires --apply.
#
# Usage:
#   scripts/setup.sh [--profile NAME] [--catalog NAME] [--apply] [--yes]
#                    [--skip-terraform]
#
# Examples:
#   scripts/setup.sh                                   # checks + venv + tfvars + init + plan
#   scripts/setup.sh --profile azure-video --apply     # full provision (prompts before apply)
#   scripts/setup.sh --apply --yes                     # full provision, no prompt
#   scripts/setup.sh --skip-terraform                  # only tooling (checks + venv + tfvars)
# =============================================================================
set -euo pipefail

# ---- defaults (match terraform/variables.tf) --------------------------------
PROFILE="azure-video"
CATALOG="classic_stable_89j9qf"
DO_APPLY=false
AUTO_YES=false
SKIP_TF=false

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/terraform"
VENV="$ROOT/.venv"

# ---- pretty output ----------------------------------------------------------
c_blue=$'\033[34m'; c_grn=$'\033[32m'; c_red=$'\033[31m'; c_yel=$'\033[33m'; c_rst=$'\033[0m'
step() { printf "\n${c_blue}==>${c_rst} %s\n" "$*"; }
ok()   { printf "    ${c_grn}✓${c_rst} %s\n" "$*"; }
warn() { printf "    ${c_yel}!${c_rst} %s\n" "$*"; }
die()  { printf "\n${c_red}✗ %s${c_rst}\n" "$*" >&2; exit 1; }

# ---- args -------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --catalog) CATALOG="$2"; shift 2 ;;
    --apply)   DO_APPLY=true; shift ;;
    --yes|-y)  AUTO_YES=true; shift ;;
    --skip-terraform) SKIP_TF=true; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) die "Unknown argument: $1 (try --help)" ;;
  esac
done

# ---- 1. tools ---------------------------------------------------------------
step "1/7 · Checking local tools"
need() { command -v "$1" >/dev/null 2>&1 || die "Missing required tool: $1 ($2)"; ok "$1 — $($1 --version 2>&1 | head -1)"; }
need databricks "https://docs.databricks.com/dev-tools/cli/install.html"
need terraform  "https://developer.hashicorp.com/terraform/install"
need uv         "https://docs.astral.sh/uv/getting-started/installation/"
need node       "https://nodejs.org (frontend build)"
need npm        "ships with node"
command -v cargo >/dev/null 2>&1 && ok "cargo (optional, for loadtest/)" || warn "cargo not found — only needed for the optional Rust loadtest"

# ---- 2. Databricks profile --------------------------------------------------
step "2/7 · Databricks profile: $PROFILE"
if databricks current-user me --profile "$PROFILE" >/dev/null 2>&1; then
  ok "Authenticated as $(databricks current-user me --profile "$PROFILE" 2>/dev/null | sed -n 's/.*"userName": *"\([^"]*\)".*/\1/p' | head -1)"
else
  warn "Profile '$PROFILE' is not authenticated (or token expired)."
  warn "Launching interactive OAuth login (opens a browser)…"
  databricks auth login --profile "$PROFILE" || die "Login failed for profile '$PROFILE'"
  databricks current-user me --profile "$PROFILE" >/dev/null 2>&1 || die "Still not authenticated after login"
  ok "Login successful"
fi

# ---- 3. Python venv (uv) ----------------------------------------------------
# Terraform's bootstrap step calls $ROOT/.venv/bin/python — it must exist with
# databricks-sdk + psycopg BEFORE `terraform apply`.
step "3/7 · Python venv via uv ($VENV)"
if [[ ! -x "$VENV/bin/python" ]]; then
  uv venv "$VENV"
  ok "Created .venv"
else
  ok ".venv already exists"
fi
uv pip install --python "$VENV/bin/python" -r "$ROOT/scripts/requirements-setup.txt" >/dev/null
ok "Installed bootstrap deps (databricks-sdk, psycopg[binary], pgvector)"

# ---- 4. terraform.tfvars ----------------------------------------------------
step "4/7 · terraform.tfvars"
TFVARS="$TF_DIR/terraform.tfvars"
if [[ -f "$TFVARS" ]]; then
  ok "terraform.tfvars already present (left untouched)"
else
  cp "$TF_DIR/terraform.tfvars.example" "$TFVARS"
  # set profile + catalog from args (BSD/macOS-compatible sed -i '')
  sed -i '' -e "s/^databricks_profile.*/databricks_profile = \"$PROFILE\"/" "$TFVARS"
  sed -i '' -e "s/^catalog_name.*/catalog_name       = \"$CATALOG\"/" "$TFVARS"
  ok "Created terraform.tfvars (profile=$PROFILE, catalog=$CATALOG)"
fi

if $SKIP_TF; then
  step "Done (--skip-terraform). Tooling, venv and tfvars are ready."
  echo "    Next: scripts/setup.sh --profile $PROFILE --apply"
  exit 0
fi

# ---- 5. terraform init + plan ----------------------------------------------
step "5/7 · terraform init"
terraform -chdir="$TF_DIR" init -input=false
ok "Providers initialized"

step "6/7 · terraform plan"
terraform -chdir="$TF_DIR" plan -input=false -out=tfplan
ok "Plan written to terraform/tfplan"

# ---- 6. apply (gated) -------------------------------------------------------
if ! $DO_APPLY; then
  step "Stopping before apply (no --apply given)."
  cat <<EOF
    Review the plan above. To provision (creates billable infra: a job cluster,
    a Lakebase Autoscale project, and a Databricks App), re-run with:

        scripts/setup.sh --profile $PROFILE --catalog $CATALOG --apply
EOF
  exit 0
fi

step "7/7 · terraform apply"
if $AUTO_YES; then
  terraform -chdir="$TF_DIR" apply -input=false tfplan
else
  warn "This provisions real, billable infrastructure in workspace profile '$PROFILE'."
  read -r -p "    Type 'yes' to apply: " reply
  [[ "$reply" == "yes" ]] || die "Aborted by user"
  terraform -chdir="$TF_DIR" apply -input=false tfplan
fi

# ---- 7. outputs -------------------------------------------------------------
step "Setup complete"
APP_URL="$(terraform -chdir="$TF_DIR" output -raw app_url 2>/dev/null || true)"
[[ -n "$APP_URL" ]] && ok "App URL: $APP_URL" || warn "Run: terraform -chdir=terraform output app_url"
