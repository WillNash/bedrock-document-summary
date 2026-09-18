#!/usr/bin/env python3
"""
tf_arch_diagram.py — Generate an interactive HTML AWS architecture diagram
from a folder of Terraform .tf files. Pure Python, no Terraform binary required.

Fetches Cytoscape.js, dagre, and cytoscape-dagre from CDN at generation time
and embeds them inline, so the output HTML has no external dependencies.

Usage:
    python tf_arch_diagram.py <folder> [OPTIONS]

    positional arguments:
      folder          Path to folder containing .tf files

    optional arguments:
      --output FILE   Output HTML file (default: architecture.html)
      --title TITLE   Diagram title (default: derived from folder name)
      --icon-dir DIR  Directory of <icon-key>.svg files (official AWS icons)
      --no-support    Hide support/auxiliary resources (cleaner graph)
      --open          Open output in default browser after generation
      --verbose       Print resource counts, skipped files, and dropped edges
"""
import argparse
import base64
import json
import re
import sys
import urllib.request
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any, Final, NamedTuple, TypeAlias

try:
    import hcl2
except ImportError:
    sys.exit("Error: python-hcl2 is not installed. Run: pip install python-hcl2")


# ── Type aliases ──────────────────────────────────────────────────────────────
# hcl2 returns untyped nested dicts at an external boundary; Any is justified.
Attrs: TypeAlias = dict[str, Any]
Registry: TypeAlias = dict[str, Attrs]
GroupNodes: TypeAlias = dict[str, list[str]]
# Cytoscape.js elements payload: {"nodes": [...], "edges": [...]}
CyElements: TypeAlias = dict[str, list[dict[str, Any]]]


# ── Resource catalog ──────────────────────────────────────────────────────────

class ResourceEntry(NamedTuple):
    label: str
    group: str
    icon_key: str


_SUPPORT_GROUP: Final = "Support"
_AWS_PREFIX_LEN: Final = len("aws_")  # rfind start position to preserve the 'aws_' prefix
_DEFAULT_ENTRY = ResourceEntry(label="", group="Other", icon_key="")

# Maps Terraform resource type → ResourceEntry(label, group, icon_key).
# group=_SUPPORT_GROUP marks auxiliary resources shown as small dots or hidden.
RESOURCE_CATALOG: dict[str, ResourceEntry] = {
    # Compute
    "aws_lambda_function":                               ResourceEntry("Lambda",             "Compute",       "lambda"),
    "aws_lambda_layer_version":                          ResourceEntry("Lambda Layer",        "Compute",       "lambda-layer"),
    # Orchestration
    "aws_sfn_state_machine":                             ResourceEntry("Step Functions",      "Orchestration", "step-functions"),
    # Networking
    "aws_apigatewayv2_api":                              ResourceEntry("API Gateway",         "Networking",    "api-gateway"),
    "aws_cloudfront_distribution":                       ResourceEntry("CloudFront",          "Networking",    "cloudfront"),
    # Auth
    "aws_cognito_user_pool":                             ResourceEntry("Cognito",             "Auth",          "cognito"),
    # Storage
    "aws_s3_bucket":                                     ResourceEntry("S3",                  "Storage",       "s3"),
    # Database
    "aws_dynamodb_table":                                ResourceEntry("DynamoDB",            "Database",      "dynamodb"),
    # Security
    "aws_kms_key":                                       ResourceEntry("KMS",                 "Security",      "kms"),
    "aws_iam_role":                                      ResourceEntry("IAM Role",            "Security",      "iam"),
    "aws_wafv2_web_acl":                                 ResourceEntry("WAF",                 "Security",      "waf"),
    # Messaging
    "aws_sqs_queue":                                     ResourceEntry("SQS",                 "Messaging",     "sqs"),
    "aws_sns_topic":                                     ResourceEntry("SNS",                 "Messaging",     "sns"),
    # AI/ML
    "aws_bedrock_guardrail":                             ResourceEntry("Bedrock Guardrail",   "AI/ML",         "bedrock"),
    "aws_bedrock_prompt":                                ResourceEntry("Bedrock Prompt",      "AI/ML",         "bedrock"),
    # Monitoring
    "aws_cloudwatch_metric_alarm":                       ResourceEntry("CloudWatch Alarm",    "Monitoring",    "cloudwatch"),
    # Support resources — parsed for edges but shown as small dots or hidden
    "aws_apigatewayv2_authorizer":                       ResourceEntry("API Authorizer",      _SUPPORT_GROUP,  ""),
    "aws_apigatewayv2_integration":                      ResourceEntry("API Integration",     _SUPPORT_GROUP,  ""),
    "aws_apigatewayv2_route":                            ResourceEntry("API Route",           _SUPPORT_GROUP,  ""),
    "aws_apigatewayv2_stage":                            ResourceEntry("API Stage",           _SUPPORT_GROUP,  ""),
    "aws_cloudwatch_log_group":                          ResourceEntry("Log Group",           _SUPPORT_GROUP,  ""),
    "aws_iam_role_policy":                               ResourceEntry("IAM Policy",          _SUPPORT_GROUP,  ""),
    "aws_iam_role_policy_attachment":                    ResourceEntry("IAM Attachment",      _SUPPORT_GROUP,  ""),
    "aws_lambda_function_event_invoke_config":           ResourceEntry("Lambda Config",       _SUPPORT_GROUP,  ""),
    "aws_lambda_permission":                             ResourceEntry("Lambda Permission",   _SUPPORT_GROUP,  ""),
    "aws_s3_bucket_cors_configuration":                  ResourceEntry("S3 CORS",             _SUPPORT_GROUP,  ""),
    "aws_s3_bucket_lifecycle_configuration":             ResourceEntry("S3 Lifecycle",        _SUPPORT_GROUP,  ""),
    "aws_s3_bucket_notification":                        ResourceEntry("S3 Notification",     _SUPPORT_GROUP,  ""),
    "aws_s3_bucket_policy":                              ResourceEntry("S3 Policy",           _SUPPORT_GROUP,  ""),
    "aws_s3_bucket_public_access_block":                 ResourceEntry("S3 Access Block",     _SUPPORT_GROUP,  ""),
    "aws_s3_bucket_server_side_encryption_configuration": ResourceEntry("S3 Encryption",      _SUPPORT_GROUP,  ""),
    "aws_s3_bucket_versioning":                          ResourceEntry("S3 Versioning",       _SUPPORT_GROUP,  ""),
    "aws_kms_alias":                                     ResourceEntry("KMS Alias",           _SUPPORT_GROUP,  ""),
    "aws_cloudfront_origin_access_control":              ResourceEntry("CF OAC",              _SUPPORT_GROUP,  ""),
    "aws_cognito_user_pool_client":                      ResourceEntry("Cognito Client",      _SUPPORT_GROUP,  ""),
    "aws_cognito_user_pool_domain":                      ResourceEntry("Cognito Domain",      _SUPPORT_GROUP,  ""),
    "aws_bedrock_guardrail_version":                     ResourceEntry("Guardrail Version",   _SUPPORT_GROUP,  ""),
    "aws_bedrock_prompt_version":                        ResourceEntry("Prompt Version",      _SUPPORT_GROUP,  ""),
    "aws_sns_topic_subscription":                        ResourceEntry("SNS Subscription",    _SUPPORT_GROUP,  ""),
    "aws_ce_anomaly_monitor":                            ResourceEntry("Cost Monitor",        _SUPPORT_GROUP,  ""),
    "aws_ce_anomaly_subscription":                       ResourceEntry("Cost Subscription",   _SUPPORT_GROUP,  ""),
    "aws_wafv2_web_acl_association":                     ResourceEntry("WAF Association",     _SUPPORT_GROUP,  ""),
}

# ── Group colour palette ──────────────────────────────────────────────────────
GROUP_COLORS: dict[str, str] = {
    "Compute":       "#ED7100",
    "Orchestration": "#E7157B",
    "Networking":    "#8C4FFF",
    "Auth":          "#C7131F",
    "Storage":       "#7AA116",
    "Database":      "#4053D6",
    "Security":      "#DD344C",
    "Messaging":     "#FF4F8B",
    "AI/ML":         "#005E7A",
    "Monitoring":    "#E7157B",
    _SUPPORT_GROUP:  "#555555",
    "Other":         "#888888",
}

# ── Inline SVG icon generation ────────────────────────────────────────────────
# These are original minimal SVGs, not reproductions of AWS artwork.

_ICON_ABBREVS: dict[str, str] = {
    "lambda":         "λ FN",
    "lambda-layer":   "λ Layer",
    "step-functions": "SFN",
    "api-gateway":    "APIGW",
    "cloudfront":     "CF",
    "cognito":        "Cognito",
    "s3":             "S3",
    "dynamodb":       "DDB",
    "kms":            "KMS",
    "iam":            "IAM",
    "waf":            "WAF",
    "sqs":            "SQS",
    "sns":            "SNS",
    "bedrock":        "Bedrock",
    "cloudwatch":     "CW",
}

# Derived from RESOURCE_CATALOG — single source of truth for icon→colour mapping.
_ICON_COLORS: dict[str, str] = {
    entry.icon_key: GROUP_COLORS.get(entry.group, "#888888")
    for entry in RESOURCE_CATALOG.values()
    if entry.icon_key
}


def _make_icon_svg(icon_key: str) -> str:
    abbrev = _ICON_ABBREVS.get(icon_key, icon_key[:4].upper())
    color = _ICON_COLORS.get(icon_key, "#888888")
    font_size = 16 if len(abbrev) <= 3 else (11 if len(abbrev) <= 7 else 9)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
        f'<rect width="64" height="64" rx="10" ry="10" fill="{color}"/>'
        f'<text x="32" y="34" font-family="Arial,sans-serif" font-size="{font_size}px" '
        f'font-weight="bold" fill="white" text-anchor="middle" dominant-baseline="middle">'
        f'{abbrev}</text>'
        f'</svg>'
    )


def _svg_to_data_uri(svg_str: str) -> str:
    b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _get_icon_uri(icon_key: str, icon_dir: Path | None) -> str:
    if icon_dir:
        candidate = icon_dir / f"{icon_key}.svg"
        if candidate.is_file():
            return _svg_to_data_uri(candidate.read_text(encoding="utf-8"))
    return _svg_to_data_uri(_make_icon_svg(icon_key))


# ── HCL parsing ───────────────────────────────────────────────────────────────

def parse_tf_folder(folder: Path, verbose: bool = False) -> Registry:
    """
    Parse all .tf files in folder and return a flat resource registry.
    Returns: { "resource_type.resource_name": attrs_dict }

    data {} blocks are intentionally skipped — they are read-only lookups
    and do not represent deployable AWS resources.
    """
    tf_files = sorted(folder.glob("*.tf"))
    if not tf_files:
        return {}

    registry: Registry = {}
    data_block_count = 0
    failed_files: list[str] = []

    for tf_file in tf_files:
        try:
            with tf_file.open("r", encoding="utf-8") as fh:
                parsed = hcl2.load(fh)
        except Exception as err:
            print(f"Warning: skipping {tf_file.name}: {err}", file=sys.stderr)
            failed_files.append(tf_file.name)
            continue

        # data blocks are intentionally not processed
        data_block_count += len(parsed.get("data", []))

        for block in parsed.get("resource", []):
            for rtype, instances in block.items():
                for rname, attrs in instances.items():
                    # python-hcl2 v8 preserves surrounding quotes on dict keys;
                    # strip them so registry keys match the bare "type.name" form
                    # that interpolation references use (e.g. aws_s3_bucket.uploads)
                    rtype_clean = rtype.strip("\"'")
                    rname_clean = rname.strip("\"'")
                    key = f"{rtype_clean}.{rname_clean}"
                    # Strip python-hcl2 v8 __is_block__ metadata before processing
                    registry[key] = {k: v for k, v in attrs.items() if not k.startswith("__")}

    if verbose:
        ok_count = len(tf_files) - len(failed_files)
        print(f"  Parsed {ok_count}/{len(tf_files)} .tf files → {len(registry)} resources", file=sys.stderr)
        if data_block_count:
            print(
                f"  Skipped {data_block_count} data source blocks"
                " (read-only lookups, not deployable resources)",
                file=sys.stderr,
            )
        if failed_files:
            print(f"  Failed files: {', '.join(failed_files)}", file=sys.stderr)

    return registry


# ── Dependency extraction ─────────────────────────────────────────────────────

# Matches ${resource_type.resource_name} and ${resource_type.resource_name.attr}
# Capture group stops at resource_type.resource_name; trailing .attribute is consumed
# by the non-capturing group (?:[.\}]) so it is not included in the edge target.
_REF_RE = re.compile(r'\$\{([a-z][a-zA-Z0-9_]+\.[a-zA-Z0-9_\-]+)(?:[.\}])')
# Bare references (Terraform 0.12+ HCL2 — python-hcl2 may or may not normalise these)
_BARE_RE = re.compile(r'\b(aws_[a-zA-Z0-9_]+\.[a-zA-Z0-9_\-]+)\b')


def extract_dependencies(
    registry: Registry,
    show_support: bool,
    verbose: bool = False,
) -> list[tuple[str, str]]:
    """
    Build directed edges from resource attribute cross-references and depends_on.
    When show_support is False, collapses support-resource edges to their primary parent.
    """
    edges: set[tuple[str, str]] = set()

    for key, attrs in registry.items():
        attr_str = str(attrs)
        refs: set[str] = set()

        for m in _REF_RE.finditer(attr_str):
            refs.add(m.group(1))
        for m in _BARE_RE.finditer(attr_str):
            refs.add(m.group(1))

        for dep in attrs.get("depends_on", []):
            cleaned = re.sub(r"^\$\{|\}$", "", str(dep).strip())
            if cleaned:
                refs.add(cleaned)

        for ref in refs:
            if ref != key and ref in registry:
                edges.add((key, ref))

    edge_list = list(edges)
    if not show_support:
        edge_list = _collapse_support_edges(edge_list, registry, verbose)
    return edge_list


def _find_primary_type(rtype: str) -> str:
    """
    Strip underscore-delimited suffixes one at a time until a primary (non-Support)
    type is found in RESOURCE_CATALOG. Returns empty string if none found.
    E.g. aws_s3_bucket_server_side_encryption_configuration → aws_s3_bucket
    """
    candidate = rtype
    while True:
        last_underscore = candidate.rfind("_", _AWS_PREFIX_LEN)
        if last_underscore == -1:
            return ""
        candidate = candidate[:last_underscore]
        entry = RESOURCE_CATALOG.get(candidate)
        if entry and entry.group != _SUPPORT_GROUP:
            return candidate


def _lcp_length(a: str, b: str) -> int:
    length = 0
    for ca, cb in zip(a, b):
        if ca == cb:
            length += 1
        else:
            break
    return length


def _collapse_support_edges(
    edges: list[tuple[str, str]],
    registry: Registry,
    verbose: bool,
) -> list[tuple[str, str]]:
    """
    When --no-support is active, remap edges whose source is a support resource
    to the best-matching primary parent resource using longest-common-prefix matching.
    Unresolvable edges are dropped.
    """
    result: list[tuple[str, str]] = []

    for src, dst in edges:
        src_rtype, src_rname = src.rsplit(".", 1)
        if RESOURCE_CATALOG.get(src_rtype, _DEFAULT_ENTRY).group != _SUPPORT_GROUP:
            result.append((src, dst))
            continue

        parent_type = _find_primary_type(src_rtype)
        if not parent_type:
            if verbose:
                print(f"  Dropped unresolvable support edge: {src} -> {dst}", file=sys.stderr)
            continue

        # Collect primary registry entries of the parent type.
        # startswith(parent_type + ".") guarantees an exact type match, so the
        # support check on the candidate is redundant but kept for safety.
        candidates = [
            (k, k.rsplit(".", 1)[1])
            for k in registry
            if k.startswith(parent_type + ".")
            and RESOURCE_CATALOG.get(k.rsplit(".", 1)[0], _DEFAULT_ENTRY).group != _SUPPORT_GROUP
        ]

        if not candidates:
            if verbose:
                print(f"  Dropped unresolvable support edge: {src} -> {dst}", file=sys.stderr)
            continue

        # LCP match — require at least 3 characters in common
        best_key, best_len = None, 0
        for cand_key, cand_name in candidates:
            lcp = _lcp_length(src_rname, cand_name)
            if lcp >= 3 and lcp > best_len:
                best_key, best_len = cand_key, lcp

        if best_key and best_key != dst:
            result.append((best_key, dst))
        else:
            if verbose:
                print(f"  Dropped unresolvable support edge: {src} -> {dst}", file=sys.stderr)

    return result


# ── Cytoscape rendering ───────────────────────────────────────────────────────

def _group_id(group: str) -> str:
    """Sanitise group name to a safe CSS/HTML id fragment."""
    return "grp-" + re.sub(r"[^a-zA-Z0-9_\-]", "_", group)


def _build_tooltip(key: str, attrs: Attrs, entry: ResourceEntry) -> str:
    lines = [f"<b>{key}</b>", f"Group: {entry.group}"]
    for attr_name in ("function_name", "name", "bucket", "table_name", "alarm_name"):
        val = attrs.get(attr_name)
        if val and isinstance(val, str) and not val.startswith("$"):
            lines.append(f"{attr_name}: {val}")
            break
    if "for_each" in attrs:
        lines.append("(for_each — multiple instances at apply time)")
    elif "count" in attrs:
        lines.append(f"count: {attrs['count']}")
    return "<br>".join(lines)


def build_cytoscape_elements(
    registry: Registry,
    edges: list[tuple[str, str]],
    show_support: bool,
    icon_dir: Path | None,
) -> tuple[CyElements, GroupNodes]:
    """
    Build Cytoscape.js compound-node elements from the resource registry.
    Group container nodes are compound parents; resource nodes are their children.
    Returns (elements, group_nodes) where group_nodes maps group → list of node IDs.
    """
    nodes: list[dict[str, Any]] = []
    cy_edges: list[dict[str, Any]] = []
    group_nodes: GroupNodes = {}
    added_groups: set[str] = set()

    for key, attrs in registry.items():
        rtype, rname = key.rsplit(".", 1)
        entry = RESOURCE_CATALOG.get(rtype, _DEFAULT_ENTRY)

        if not show_support and entry.group == _SUPPORT_GROUP:
            continue

        group = entry.group
        color = GROUP_COLORS.get(group, "#888888")
        group_nodes.setdefault(group, []).append(key)

        if group not in added_groups:
            nodes.append({
                "data": {"id": _group_id(group), "label": group, "color": color},
                "classes": "group-container",
            })
            added_groups.add(group)

        node_data: dict[str, Any] = {
            "id": key,
            "label": rname,
            "parent": _group_id(group),
            "tooltip": _build_tooltip(key, attrs, entry),
            "group": group,
        }

        if entry.group == _SUPPORT_GROUP:
            nodes.append({"data": node_data, "classes": "support-node"})
        elif entry.icon_key:
            node_data["icon"] = _get_icon_uri(entry.icon_key, icon_dir)
            nodes.append({"data": node_data, "classes": "primary-node"})
        else:
            node_data["color"] = color
            nodes.append({"data": node_data, "classes": "other-node"})

    node_ids = {n["data"]["id"] for n in nodes}
    for src, dst in edges:
        if src in node_ids and dst in node_ids:
            cy_edges.append({"data": {"source": src, "target": dst}})

    return {"nodes": nodes, "edges": cy_edges}, group_nodes


# CDN URLs for the Cytoscape.js rendering stack — fetched once at generation
# time and embedded inline so the output HTML has no external dependencies.
_JS_URLS: Final[dict[str, str]] = {
    "cytoscape":       "https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.29.2/cytoscape.min.js",
    "dagre":           "https://cdnjs.cloudflare.com/ajax/libs/dagre/0.8.5/dagre.min.js",
    "cytoscape-dagre": "https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js",
}


def _fetch_js(name: str, url: str, verbose: bool = False) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "tf-arch-diagram/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8")
        if verbose:
            print(f"  Fetched {name} ({len(content):,} bytes)", file=sys.stderr)
        return content
    except Exception as err:
        print(f"Warning: could not fetch {name} from {url}: {err}", file=sys.stderr)
        return f"/* ERROR: {name} unavailable — diagram may not render correctly */"


def _build_script_tags(verbose: bool = False) -> str:
    parts = []
    for name, url in _JS_URLS.items():
        js = _fetch_js(name, url, verbose)
        parts.append(f"<script>\n{js}\n</script>")
    return "\n".join(parts)


# ── HTML page constants ───────────────────────────────────────────────────────

_PAGE_CSS = """\
body {
  margin: 0; padding: 0;
  background: #1a1a2e;
  font-family: Arial, sans-serif;
  overflow: hidden;
}
#tf-arch-header {
  background: #16213e;
  padding: 10px 18px 8px;
  border-bottom: 2px solid #0f3460;
  position: relative;
  z-index: 1000;
  box-shadow: 0 2px 8px rgba(0,0,0,0.5);
}
#tf-arch-top {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 8px;
}
#tf-arch-title {
  color: #e2e8f0;
  font-size: 17px;
  font-weight: bold;
  letter-spacing: 0.3px;
  margin: 0;
}
#tf-arch-controls button {
  background: #0f3460;
  color: #e2e8f0;
  border: 1px solid #4a6fa5;
  border-radius: 4px;
  padding: 3px 11px;
  cursor: pointer;
  font-size: 13px;
  margin-right: 3px;
}
#tf-arch-controls button:hover { background: #1a4a7a; }
#tf-arch-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  margin-bottom: 6px;
}
.grp-swatch {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #cbd5e0;
  font-size: 12px;
  cursor: pointer;
  user-select: none;
}
.grp-swatch input[type=checkbox] { cursor: pointer; accent-color: #4a9eff; }
.swatch-dot {
  display: inline-block;
  width: 11px;
  height: 11px;
  border-radius: 50%;
  flex-shrink: 0;
}
#tf-arch-footer { color: #718096; font-size: 11px; margin-top: 4px; }
#cy {
  width: 100%;
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  top: 0; /* overridden by JS after header height is measured */
}
#cy-tooltip {
  position: fixed;
  background: rgba(15, 25, 60, 0.95);
  color: #e2e8f0;
  border: 1px solid #4a6fa5;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
  line-height: 1.6;
  pointer-events: none;
  display: none;
  max-width: 300px;
  z-index: 2000;
  box-shadow: 0 4px 12px rgba(0,0,0,0.5);
}"""

# Sentinel strings __ELEMENTS__ and __GROUP_NODES__ are substituted at
# generation time by _build_init_script(). They cannot appear in the JSON
# payload because resource names and group names contain only alphanumerics,
# underscores, hyphens, dots, and slashes.
_INIT_JS_TEMPLATE = """\
(function () {
  var ELEMENTS   = __ELEMENTS__;
  var GROUP_NODES = __GROUP_NODES__;

  function gid(g) {
    return 'grp-' + g.replace(/[^a-zA-Z0-9_\\-]/g, '_');
  }

  var cy;

  function sizeCanvas() {
    var h = document.getElementById('tf-arch-header').offsetHeight;
    document.getElementById('cy').style.top = h + 'px';
    if (cy) cy.resize();
  }

  window.addEventListener('DOMContentLoaded', function () {
    sizeCanvas();

    cy = cytoscape({
      container: document.getElementById('cy'),
      elements:  ELEMENTS,
      minZoom:   0.05,
      maxZoom:   3,
      style: [
        {
          selector: 'node.group-container',
          style: {
            'label':                    'data(label)',
            'text-valign':              'top',
            'text-halign':              'center',
            'text-margin-y':            -12,
            'font-size':                '14px',
            'font-weight':              'bold',
            'color':                    '#e2e8f0',
            'text-background-color':    '#16213e',
            'text-background-opacity':  0.8,
            'text-background-padding':  '4px',
            'background-color':         'data(color)',
            'background-opacity':       0.1,
            'border-color':             'data(color)',
            'border-width':             2,
            'border-opacity':           0.75,
            'padding':                  '30px',
          }
        },
        {
          selector: 'node.primary-node',
          style: {
            'label':             'data(label)',
            'text-valign':       'bottom',
            'text-halign':       'center',
            'text-margin-y':     6,
            'font-size':         '10px',
            'color':             '#e2e8f0',
            'text-outline-color': '#1a1a2e',
            'text-outline-width': 2,
            'width':             56,
            'height':            56,
            'background-image':  'data(icon)',
            'background-fit':    'cover',
            'background-color':  '#1a1a2e',
            'border-width':      0,
            'shape':             'rectangle',
          }
        },
        {
          selector: 'node.support-node',
          style: {
            'width':            10,
            'height':           10,
            'background-color': '#555555',
            'border-color':     '#777777',
            'border-width':     1,
            'label':            '',
            'shape':            'ellipse',
          }
        },
        {
          selector: 'node.other-node',
          style: {
            'label':            'data(label)',
            'text-valign':      'center',
            'text-halign':      'center',
            'font-size':        '10px',
            'color':            '#ffffff',
            'width':            50,
            'height':           50,
            'background-color': 'data(color)',
            'border-width':     0,
            'shape':            'ellipse',
          }
        },
        {
          selector: 'edge',
          style: {
            'width':               1.5,
            'line-color':          '#aaaaaa',
            'target-arrow-color':  '#aaaaaa',
            'target-arrow-shape':  'triangle',
            'curve-style':         'bezier',
            'opacity':             0.7,
            'arrow-scale':         0.8,
          }
        },
        {
          selector: '.faded',
          style: { 'opacity': 0.1 }
        },
        {
          selector: '.highlighted',
          style: { 'opacity': 1 }
        },
        {
          selector: 'node.group-container.faded',
          style: { 'opacity': 0.4 }
        }
      ],
    });

    cy.layout({
      name:    'dagre',
      rankDir: 'LR',
      nodeSep: 50,
      rankSep: 120,
      edgeSep: 10,
      animate: false,
      padding: 30,
      spacingFactor: 1.1,
      nodeDimensionsIncludeLabels: false,
      fit: false,
    }).run();

    cy.fit(undefined, 40);
    sizeCanvas();

    // ── Tooltip ──────────────────────────────────────────────────────────────
    var tooltip = document.getElementById('cy-tooltip');

    cy.on('mouseover', 'node.primary-node, node.support-node, node.other-node', function (e) {
      var tip = e.target.data('tooltip');
      if (tip) {
        tooltip.innerHTML = tip;
        tooltip.style.display = 'block';
      }
    });

    cy.on('mousemove', function (e) {
      if (tooltip.style.display !== 'none') {
        var oe = e.originalEvent;
        tooltip.style.left = (oe.clientX + 14) + 'px';
        tooltip.style.top  = (oe.clientY + 14) + 'px';
      }
    });

    cy.on('mouseout', 'node', function () {
      tooltip.style.display = 'none';
    });

    // ── Click to highlight ───────────────────────────────────────────────────
    cy.on('tap', 'node.primary-node, node.support-node, node.other-node', function (e) {
      var node = e.target;
      cy.elements().not('.group-container').addClass('faded').removeClass('highlighted');
      node.addClass('highlighted').removeClass('faded');
      node.connectedEdges().addClass('highlighted').removeClass('faded');
      node.connectedEdges().connectedNodes().addClass('highlighted').removeClass('faded');
    });

    cy.on('tap', 'node.group-container', function () {
      cy.elements().removeClass('faded highlighted');
      tooltip.style.display = 'none';
    });

    cy.on('tap', function (e) {
      if (e.target === cy) {
        cy.elements().removeClass('faded highlighted');
        tooltip.style.display = 'none';
      }
    });

    // ── Group toggles ────────────────────────────────────────────────────────
    document.querySelectorAll('.grp-toggle').forEach(function (cb) {
      cb.addEventListener('change', function () {
        var group = this.dataset.group;
        var ids   = GROUP_NODES[group] || [];
        var disp  = this.checked ? 'element' : 'none';

        cy.getElementById(gid(group)).style('display', disp);
        ids.forEach(function (id) {
          cy.getElementById(id).style('display', disp);
        });

        // Hide edges where either endpoint is hidden
        cy.edges().forEach(function (edge) {
          var sh = edge.source().style('display') === 'none';
          var th = edge.target().style('display') === 'none';
          edge.style('display', (sh || th) ? 'none' : 'element');
        });
      });
    });

    // ── Controls ─────────────────────────────────────────────────────────────
    document.getElementById('btn-fit').addEventListener('click', function () {
      cy.fit(undefined, 40);
    });
    document.getElementById('btn-zoom-in').addEventListener('click', function () {
      cy.zoom({ level: cy.zoom() * 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    });
    document.getElementById('btn-zoom-out').addEventListener('click', function () {
      cy.zoom({ level: cy.zoom() / 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    });

    // ── Keyboard shortcuts ───────────────────────────────────────────────────
    document.addEventListener('keydown', function (e) {
      if (e.target.tagName === 'INPUT') return;
      switch (e.key) {
        case 'f':
          cy.fit(undefined, 40);
          break;
        case '+':
        case '=':
          cy.zoom({ level: cy.zoom() * 1.2, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
          break;
        case '-':
          cy.zoom({ level: cy.zoom() / 1.2, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
          break;
      }
    });
  });

  window.addEventListener('resize', sizeCanvas);
})();"""


# ── HTML assembly ─────────────────────────────────────────────────────────────

def _build_legend_html(
    group_nodes: GroupNodes,
    title: str,
    resource_count: int,
    edge_count: int,
) -> str:
    swatches = [
        f'<label class="grp-swatch">'
        f'<input type="checkbox" class="grp-toggle" data-group="{group}" checked>'
        f'<span class="swatch-dot" style="background:{GROUP_COLORS.get(group, "#888888")}"></span>'
        f'<span>{group} ({len(group_nodes[group])})</span>'
        f'</label>'
        for group in sorted(group_nodes)
    ]
    controls = (
        '<div id="tf-arch-controls">'
        '<button id="btn-fit" title="Fit all nodes to screen (F)">Fit</button>'
        '<button id="btn-zoom-in" title="Zoom in (+)">+</button>'
        '<button id="btn-zoom-out" title="Zoom out (−)">−</button>'
        '</div>'
    )
    return (
        f'<div id="tf-arch-header">'
        f'<div id="tf-arch-top">'
        f'<div id="tf-arch-title">{title}</div>'
        f'{controls}'
        f'</div>'
        f'<div id="tf-arch-legend">{"".join(swatches)}</div>'
        f'<div id="tf-arch-footer">'
        f'Generated by tf_arch_diagram.py · {date.today()} · '
        f'{resource_count} resources · {edge_count} edges'
        f'</div>'
        f'</div>'
    )


def _build_init_script(elements_json: str, group_nodes_json: str) -> str:
    js = (
        _INIT_JS_TEMPLATE
        .replace("__ELEMENTS__", elements_json)
        .replace("__GROUP_NODES__", group_nodes_json)
    )
    return f"<script>\n{js}\n</script>"


def _build_cytoscape_html(
    elements: CyElements,
    group_nodes: GroupNodes,
    title: str,
    resource_count: int,
    edge_count: int,
    script_tags: str,
) -> str:
    elements_json   = json.dumps(elements,    ensure_ascii=False)
    group_nodes_json = json.dumps(group_nodes, ensure_ascii=False)
    legend      = _build_legend_html(group_nodes, title, resource_count, edge_count)
    init_script = _build_init_script(elements_json, group_nodes_json)

    return (
        "<!DOCTYPE html>\n"
        "<html lang='en'>\n"
        "<head>\n"
        "<meta charset='utf-8'>\n"
        f"<title>{title}</title>\n"
        f"<style>\n{_PAGE_CSS}\n</style>\n"
        f"{script_tags}\n"
        "</head>\n"
        "<body>\n"
        f"{legend}\n"
        "<div id='cy'></div>\n"
        "<div id='cy-tooltip'></div>\n"
        f"{init_script}\n"
        "</body>\n"
        "</html>"
    )


def generate_html(
    elements: CyElements,
    group_nodes: GroupNodes,
    title: str,
    output_path: Path,
    resource_count: int,
    edge_count: int,
    verbose: bool = False,
) -> None:
    script_tags = _build_script_tags(verbose=verbose)
    html = _build_cytoscape_html(
        elements, group_nodes, title, resource_count, edge_count, script_tags
    )
    output_path.write_text(html, encoding="utf-8")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an interactive HTML AWS architecture diagram from Terraform files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python tf_arch_diagram.py infra/ --output arch.html --verbose\n"
            "  python tf_arch_diagram.py infra/ --no-support --open\n"
            "  python tf_arch_diagram.py infra/ --icon-dir ~/aws-icons/ --title 'My Stack'\n"
        ),
    )
    parser.add_argument("folder", help="Path to folder containing .tf files")
    parser.add_argument("--output", default="architecture.html", metavar="FILE",
                        help="Output HTML file path (default: architecture.html)")
    parser.add_argument("--title", default=None, metavar="TITLE",
                        help="Diagram title (default: derived from folder name)")
    parser.add_argument("--icon-dir", default=None, metavar="DIR",
                        help="Directory of <icon-key>.svg files for official AWS icons")
    parser.add_argument("--no-support", action="store_true",
                        help="Hide support/auxiliary resources for a cleaner graph")
    parser.add_argument("--open", action="store_true",
                        help="Open the output file in the default browser after generation")
    parser.add_argument("--verbose", action="store_true",
                        help="Print resource counts, skipped files, and dropped edges to stderr")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a directory or does not exist.", file=sys.stderr)
        sys.exit(1)

    tf_files = list(folder.glob("*.tf"))
    if not tf_files:
        print(f"Error: no .tf files found in '{folder}'.", file=sys.stderr)
        sys.exit(1)

    icon_dir: Path | None = None
    if args.icon_dir:
        icon_dir = Path(args.icon_dir)
        if not icon_dir.is_dir():
            print(f"Warning: --icon-dir '{icon_dir}' does not exist; using inline icons.", file=sys.stderr)
            icon_dir = None

    title = args.title or folder.resolve().name.replace("_", " ").replace("-", " ").title()
    show_support = not args.no_support

    if args.verbose:
        print(f"Parsing {len(tf_files)} .tf files in '{folder}'...", file=sys.stderr)

    registry = parse_tf_folder(folder, verbose=args.verbose)
    if not registry:
        print("Error: all .tf files failed to parse or no resources found.", file=sys.stderr)
        sys.exit(2)

    if args.verbose:
        conditional_count = sum(
            1 for attrs in registry.values()
            if "count" in attrs or "for_each" in attrs
        )
        if conditional_count:
            print(
                f"  Warning: {conditional_count} resources have count/for_each — "
                "static parsing cannot exclude count=0 resources from the diagram.",
                file=sys.stderr,
            )

    edges = extract_dependencies(registry, show_support=show_support, verbose=args.verbose)

    if args.verbose:
        print(f"  Found {len(edges)} dependency edges", file=sys.stderr)

    elements, group_nodes = build_cytoscape_elements(
        registry, edges, show_support=show_support, icon_dir=icon_dir
    )

    resource_count = sum(len(ids) for ids in group_nodes.values())
    edge_count = len(elements["edges"])

    output_path = Path(args.output)
    try:
        generate_html(
            elements, group_nodes, title, output_path,
            resource_count, edge_count, verbose=args.verbose,
        )
    except IOError as err:
        print(f"Error: could not write '{output_path}': {err}", file=sys.stderr)
        sys.exit(1)

    print(f"Generated {output_path} — {resource_count} resources, {edge_count} edges.")

    if args.open:
        webbrowser.open(output_path.resolve().as_uri())


if __name__ == "__main__":
    main()
