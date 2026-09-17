#!/usr/bin/env python3
"""
tf_arch_diagram.py — Generate an interactive HTML AWS architecture diagram
from a folder of Terraform .tf files. Pure Python, no Terraform binary required.

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
import tempfile
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any, Final, NamedTuple, TypeAlias

try:
    import hcl2
except ImportError:
    sys.exit("Error: python-hcl2 is not installed. Run: pip install python-hcl2")

try:
    from pyvis.network import Network
except ImportError:
    sys.exit("Error: pyvis is not installed. Run: pip install pyvis")


# ── Type aliases ──────────────────────────────────────────────────────────────
# hcl2 returns untyped nested dicts at an external boundary; Any is justified.
Attrs: TypeAlias = dict[str, Any]
Registry: TypeAlias = dict[str, Attrs]
GroupNodes: TypeAlias = dict[str, list[str]]


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


# ── Graph construction ────────────────────────────────────────────────────────

def build_graph(
    registry: Registry,
    edges: list[tuple[str, str]],
    show_support: bool,
    icon_dir: Path | None,
) -> tuple[Network, GroupNodes]:
    """
    Build the pyvis Network. Returns (network, group_nodes) where
    group_nodes maps group name → list of node IDs in that group.
    """
    net = Network(
        height="870px",
        width="100%",
        directed=True,
        cdn_resources="in_line",   # embeds vis.js inline — no CDN needed at render time
        bgcolor="#1a1a2e",
        font_color="white",
        notebook=False,
    )

    net.set_options(json.dumps({
        "physics": {
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
                "gravitationalConstant": -50,
                "springLength": 150,
                "springConstant": 0.05,
                "damping": 0.4,
            },
            "stabilization": {"iterations": 200},
        },
        "layout": {"improvedLayout": True},
        "interaction": {
            "hover": True,
            "tooltipDelay": 150,
            "navigationButtons": True,
            "keyboard": True,
        },
        "edges": {
            "smooth": {"type": "curvedCW", "roundness": 0.1},
            "font": {"size": 0},
        },
    }))

    group_nodes: GroupNodes = {}

    for key, attrs in registry.items():
        rtype, rname = key.rsplit(".", 1)
        entry = RESOURCE_CATALOG.get(rtype, _DEFAULT_ENTRY)

        if not show_support and entry.group == _SUPPORT_GROUP:
            continue

        group_nodes.setdefault(entry.group, []).append(key)
        color = GROUP_COLORS.get(entry.group, "#888888")

        # Build a concise hover tooltip
        tooltip_lines = [f"<b>{key}</b>", f"Group: {entry.group}"]
        for attr_name in ("function_name", "name", "bucket", "table_name", "alarm_name"):
            val = attrs.get(attr_name)
            if val and isinstance(val, str) and not val.startswith("$"):
                tooltip_lines.append(f"{attr_name}: {val}")
                break
        if "for_each" in attrs:
            tooltip_lines.append("(for_each — multiple instances at apply time)")
        elif "count" in attrs:
            tooltip_lines.append(f"count: {attrs['count']}")
        tooltip = "<br>".join(tooltip_lines)

        if entry.group == _SUPPORT_GROUP:
            net.add_node(
                key,
                label=rname,
                title=tooltip,
                shape="dot",
                size=8,
                color={"background": "#555555", "border": "#777777"},
                group=entry.group,
            )
        elif entry.icon_key:
            net.add_node(
                key,
                label=rname,
                title=tooltip,
                shape="image",
                image=_get_icon_uri(entry.icon_key, icon_dir),
                size=35,
                group=entry.group,
                font={"color": "white", "size": 11, "strokeWidth": 2, "strokeColor": "#1a1a2e"},
            )
        else:
            # "Other" group — no icon key defined in RESOURCE_CATALOG
            net.add_node(
                key,
                label=rname,
                title=tooltip,
                shape="ellipse",
                size=25,
                color={"background": color, "border": color},
                group=entry.group,
                font={"color": "white", "size": 11},
            )

    node_ids_in_graph = set(net.get_nodes())
    for src, dst in edges:
        if src in node_ids_in_graph and dst in node_ids_in_graph:
            net.add_edge(src, dst, arrows="to", color={"color": "#aaaaaa", "opacity": 0.7}, width=1.5)

    return net, group_nodes


# ── HTML post-processing ──────────────────────────────────────────────────────

_INLINE_CSS = """\
<meta charset="utf-8">
<style>
  body { margin: 0; padding: 0; background: #1a1a2e; font-family: Arial, sans-serif; overflow-x: hidden; }
  #tf-arch-header { background: #16213e; padding: 10px 18px 7px; border-bottom: 2px solid #0f3460; position: sticky; top: 0; z-index: 1000; box-shadow: 0 2px 8px rgba(0,0,0,0.5); }
  #tf-arch-title { margin: 0 0 7px; color: #e2e8f0; font-size: 17px; font-weight: bold; letter-spacing: 0.3px; }
  #tf-arch-legend { display: flex; flex-wrap: wrap; gap: 12px 18px; margin-bottom: 6px; }
  .grp-swatch { display: flex; align-items: center; gap: 6px; color: #cbd5e0; font-size: 12px; cursor: pointer; user-select: none; }
  .grp-swatch input[type=checkbox] { cursor: pointer; accent-color: #4a9eff; }
  .swatch-dot { display: inline-block; width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0; }
  #tf-arch-footer { color: #718096; font-size: 11px; margin-top: 4px; }
</style>"""


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
    return (
        f'<div id="tf-arch-header">'
        f'<div id="tf-arch-title">{title}</div>'
        f'<div id="tf-arch-legend">{"".join(swatches)}</div>'
        f'<div id="tf-arch-footer">'
        f'Generated by tf_arch_diagram.py · {date.today()} · '
        f'{resource_count} resources · {edge_count} edges'
        f'</div>'
        f'</div>'
    )


def _build_toggle_script(group_nodes: GroupNodes) -> str:
    group_map_json = json.dumps(group_nodes)
    return f"""\
<script>
(function() {{
  var groupNodes = {group_map_json};

  function getNetwork() {{
    // Detect the vis.Network instance by scanning window scope.
    // pyvis 0.3.x assigns it to a variable named 'network' or similar.
    var common = ['network', 'network1', 'net'];
    for (var i = 0; i < common.length; i++) {{
      var obj = window[common[i]];
      if (obj && obj.body && obj.body.data && obj.body.data.nodes) return obj;
    }}
    for (var k in window) {{
      try {{
        var obj = window[k];
        if (obj && typeof obj === 'object' && obj.body && obj.body.data && obj.body.data.nodes) return obj;
      }} catch (e) {{}}
    }}
    return null;
  }}

  function toggleGroup(group, visible) {{
    var net = getNetwork();
    if (!net) return;
    var ids = groupNodes[group] || [];
    var updates = ids.map(function(id) {{ return {{ id: id, hidden: !visible }}; }});
    if (updates.length) net.body.data.nodes.update(updates);
  }}

  window.addEventListener('load', function() {{
    // Small delay so vis.js finishes its own initialisation
    setTimeout(function() {{
      document.querySelectorAll('.grp-toggle').forEach(function(cb) {{
        cb.addEventListener('change', function() {{
          toggleGroup(this.dataset.group, this.checked);
        }});
      }});
    }}, 300);
  }});
}})();
</script>"""


def _get_raw_html(net: Network) -> str:
    # generate_html() confirmed present in pyvis 0.3.2; tempfile fallback
    # retained for forward/backward compatibility with other 0.3.x releases.
    if hasattr(net, "generate_html"):
        return net.generate_html(local=False, notebook=False)
    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
    tmp.close()
    tmp_path = Path(tmp.name)
    try:
        net.write_html(str(tmp_path))
        return tmp_path.read_text(encoding="utf-8")
    finally:
        tmp_path.unlink()


def _strip_cdn_tags(html: str) -> str:
    # pyvis injects Bootstrap from CDN even with cdn_resources='in_line' (issue #228).
    html = re.sub(r'<link[^>]+href=["\']https://[^"\']*["\'][^>]*/?>', "", html)
    html = re.sub(r'<script[^>]+src=["\']https://[^"\']*["\'][^>]*></script>', "", html)
    return html


def _inject_head(html: str) -> str:
    return html.replace("<head>", "<head>\n" + _INLINE_CSS, 1)


def _inject_legend(html: str, legend: str) -> str:
    # String insertion rather than re.sub to avoid misinterpreting legend HTML
    # as a regex replacement string (backslashes, ampersands, etc.).
    body_match = re.search(r"<body[^>]*>", html)
    if not body_match:
        return html
    pos = body_match.end()
    return html[:pos] + "\n" + legend + html[pos:]


def _inject_toggle_script(html: str, script: str) -> str:
    return html.replace("</body>", script + "\n</body>", 1)


def generate_html(
    net: Network,
    group_nodes: GroupNodes,
    title: str,
    output_path: Path,
    resource_count: int,
    edge_count: int,
) -> None:
    legend = _build_legend_html(group_nodes, title, resource_count, edge_count)
    toggle = _build_toggle_script(group_nodes)

    html = _get_raw_html(net)
    html = _strip_cdn_tags(html)
    html = _inject_head(html)
    html = _inject_legend(html, legend)
    html = _inject_toggle_script(html, toggle)

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

    net, group_nodes = build_graph(registry, edges, show_support=show_support, icon_dir=icon_dir)

    resource_count = sum(len(ids) for ids in group_nodes.values())
    edge_count = len(net.get_edges())

    output_path = Path(args.output)
    try:
        generate_html(net, group_nodes, title, output_path, resource_count, edge_count)
    except IOError as err:
        print(f"Error: could not write '{output_path}': {err}", file=sys.stderr)
        sys.exit(1)

    print(f"Generated {output_path} — {resource_count} resources, {edge_count} edges.")

    if args.open:
        webbrowser.open(output_path.resolve().as_uri())


if __name__ == "__main__":
    main()
