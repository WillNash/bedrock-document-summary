terraform {
  backend "s3" {
    # Config is supplied via infra/backend.hcl (gitignored).
    # Copy infra/backend.hcl.example → infra/backend.hcl and fill in values,
    # then: terraform -chdir=infra init -backend-config=backend.hcl
    encrypt = true
  }
}
