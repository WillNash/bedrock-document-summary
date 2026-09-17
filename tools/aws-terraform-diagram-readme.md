# AWS Terraform Architecture Diagram Tool

Generates a self-contained, interactive HTML diagram of an AWS architecture directly from Terraform `.tf` files. No Terraform binary, no `terraform init`, no plan file — just point it at a folder.

## Requirements

Python 3.11+ with two packages:

```bash
pip install -r tools/requirements.txt
```

```
python-hcl2==8.1.4
pyvis==0.3.2
```

## Quick start

```bash
python3 tools/tf_arch_diagram.py infra/ --open
```

This parses every `.tf` file in `infra/`, writes `architecture.html` in the current directory, and opens it in your default browser.

## Usage

```
python3 tools/tf_arch_diagram.py <folder> [OPTIONS]
```

### Arguments

| Argument | Description |
|---|---|
| `folder` | Path to the directory containing `.tf` files (required) |

### Options

| Option | Default | Description |
|---|---|---|
| `--output FILE` | `architecture.html` | Path to write the output HTML file |
| `--title TITLE` | Folder name, title-cased | Heading shown in the diagram |
| `--icon-dir DIR` | — | Directory of official AWS SVG icons (see [Icon customisation](#icon-customisation)) |
| `--no-support` | — | Hide auxiliary resources for a cleaner diagram |
| `--open` | — | Open the output file in the default browser after writing |
| `--verbose` | — | Print parse counts, skipped files, and dropped edges to stderr |

### Examples

```bash
# Basic — writes architecture.html in the current directory
python3 tools/tf_arch_diagram.py infra/

# Custom output path and title
python3 tools/tf_arch_diagram.py infra/ \
    --output docs/architecture.html \
    --title "Bedrock Summarizer"

# Clean view — primary resources only, open immediately
python3 tools/tf_arch_diagram.py infra/ --no-support --open

# Diagnose what was parsed
python3 tools/tf_arch_diagram.py infra/ --verbose

# Use official AWS icons
python3 tools/tf_arch_diagram.py infra/ --icon-dir ~/aws-icons/
```

## Navigating the diagram

The output is a single HTML file with no external dependencies. Open it in any modern browser — no web server needed.

| Action | How |
|---|---|
| Pan | Click and drag the canvas |
| Zoom | Scroll wheel, or pinch on trackpad |
| Move a node | Click and drag the node |
| Inspect a resource | Hover over a node to see its Terraform address and key attributes |
| Toggle a service group | Use the checkboxes in the header bar |
| Fit all nodes to screen | Click the navigation button (bottom-left) or press `f` |
| Zoom in / out with keyboard | `+` / `-` |

Arrows point **from dependent to dependency** — the same direction as `terraform graph`. For example, an arrow from `aws_lambda_function.api_presign` to `aws_s3_bucket.uploads` means the Lambda references the bucket.

## Primary and support resources

Resources fall into two tiers:

**Primary** resources are the main architectural components — Lambda functions, S3 buckets, DynamoDB tables, API Gateway, Step Functions, and so on. They appear as coloured icon tiles and are grouped by service category in the legend.

**Support** resources are auxiliary constructs that configure primary resources — `aws_s3_bucket_notification`, `aws_iam_role_policy`, `aws_cloudwatch_log_group`, `aws_lambda_permission`, and similar. By default they appear as small grey dots so that their dependency edges are preserved. Use `--no-support` to remove them entirely for a cleaner high-level view.

### Service groups and colours

| Group | Colour | Example resources |
|---|---|---|
| Compute | Orange | Lambda, Lambda Layer |
| Orchestration | Pink | Step Functions |
| Networking | Purple | API Gateway, CloudFront |
| Auth | Red | Cognito |
| Storage | Green | S3 |
| Database | Blue | DynamoDB |
| Security | Red | KMS, IAM Role, WAF |
| Messaging | Pink | SQS, SNS |
| AI/ML | Teal | Bedrock Guardrail, Bedrock Prompt |
| Monitoring | Pink | CloudWatch Alarm |
| Support | Dark grey | All auxiliary resources |
| Other | Grey | Unrecognised resource types |

## Icon customisation

By default the tool generates simple coloured tiles with service abbreviations as node icons. These are original artwork and carry no licensing restrictions.

To use the official AWS Architecture Icons instead:

1. Download the icon package from [aws.amazon.com/architecture/icons](https://aws.amazon.com/architecture/icons/) and unzip it.
2. Collect the SVG files you want and place them in a flat directory named by icon key (see table below).
3. Pass that directory with `--icon-dir`.

```bash
python3 tools/tf_arch_diagram.py infra/ --icon-dir ~/aws-icons/
```

The tool looks for `<icon-key>.svg` in the supplied directory. If a file is not found, it falls back to the generated inline icon — missing icons never cause an error.

### Icon key reference

| Icon key | Service |
|---|---|
| `lambda` | Lambda |
| `lambda-layer` | Lambda Layer |
| `step-functions` | Step Functions |
| `api-gateway` | API Gateway |
| `cloudfront` | CloudFront |
| `cognito` | Cognito |
| `s3` | S3 |
| `dynamodb` | DynamoDB |
| `kms` | KMS |
| `iam` | IAM Role |
| `waf` | WAF |
| `sqs` | SQS |
| `sns` | SNS |
| `bedrock` | Bedrock Guardrail and Prompt |
| `cloudwatch` | CloudWatch Alarm |

## How dependencies are detected

The tool uses static analysis — it reads the raw `.tf` files without running Terraform. Dependencies are extracted two ways:

**Attribute references** — every resource's attributes are scanned for cross-resource references such as `${aws_s3_bucket.uploads.id}` or bare Terraform 0.12+ style `aws_s3_bucket.uploads.id`. Each reference that resolves to another resource in the folder becomes a directed edge.

**`depends_on` blocks** — explicit dependencies are also collected.

Because the tool reads source files rather than a plan, a few things follow naturally:

- **`count = 0` resources appear in the diagram.** The tool cannot evaluate variable expressions, so conditional resources are always shown. This is expected — treat the diagram as a map of what _can_ be deployed, not necessarily what _is_ deployed in the current workspace.
- **`for_each` resources appear as a single node.** The tool sees the HCL block once; Terraform would expand it into multiple instances at apply time. Nodes with `for_each` show a note in their tooltip.
- **Only `.tf` files in the specified folder are scanned** — subdirectories (Terraform modules) are not traversed. The tool is designed for flat `infra/` layouts.
- **`data` source blocks are skipped.** They are read-only lookups, not deployable resources.

## Output file

The generated HTML is fully self-contained: vis.js is embedded inline, icons are base64-encoded data URIs, and no CDN requests are made at render time. The file can be shared, committed, or stored as a build artefact without any supporting files.

Typical file size for a medium-complexity AWS stack: 700 KB – 1 MB (dominated by the embedded vis.js bundle).

## Extending the resource catalog

The `RESOURCE_CATALOG` dictionary in `tf_arch_diagram.py` maps Terraform resource types to display metadata. To add support for a resource type not currently listed, add an entry:

```python
"aws_elasticache_cluster": ResourceEntry("ElastiCache", "Database", "elasticache"),
```

- **label** — human-readable name shown in tooltips
- **group** — determines colour and legend grouping; use an existing group name or add a new one to `GROUP_COLORS`
- **icon_key** — filename stem for `--icon-dir` lookup and abbreviation source; use `""` for support resources

Unrecognised resource types are rendered automatically in the `Other` group as grey ellipses, so the diagram never breaks on unfamiliar resources — they are just unstyled.
