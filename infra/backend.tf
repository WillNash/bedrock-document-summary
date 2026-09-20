terraform {
  backend "s3" {
    # Config is supplied at init time via -backend-config=backend.hcl.
    # In CI/CD this is written from the TF_BACKEND_CONFIG GitHub secret.
    encrypt = true
  }
}
