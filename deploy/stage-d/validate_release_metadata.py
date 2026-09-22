#!/usr/bin/env python3
"""Offline, fail-closed check of the builder's generated YAML/stamp format.

This deliberately accepts only the emitted scalar/mapping/list YAML subset;
no YAML tags, aliases or executable stamp sourcing. It reads only release metadata.
"""
import argparse
from pathlib import Path
import re

VERSIONS = {
    "stage": "D", "phase": "D.6", "config_schema_version": "3",
    "migration_version": "resource-manager-v2",
    "resource_manager_contract_version": "2",
    "priority_class_contract_version": "1", "job_state_contract_version": "1",
    "provider_registry_schema_version": "1", "unified_admission_contract_version": "1",
    "compatibility_contract_version": "1",
}
PROVIDERS = ("llm_provider", "agent_provider", "media_generation_provider",
             "embedding_provider", "knowledge_backend")


def manifest_scalars(text):
    values, parents, seen = {}, [], set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if line.strip().startswith("- "):
            if not parents or parents[-1][1] != "changed_components":
                raise ValueError("unexpected manifest list")
            continue
        match = re.fullmatch(r" *([a-z_]+):(?: ([A-Za-z0-9:._/-]+))?", line)
        if not match or indent % 2:
            raise ValueError("unsupported manifest syntax")
        while parents and parents[-1][0] >= indent:
            parents.pop()
        if indent != (parents[-1][0] + 2 if parents else 0):
            raise ValueError("invalid manifest indentation")
        key, value = match.groups()
        path = tuple(name for _, name in parents) + (key,)
        if path in seen:
            raise ValueError("duplicate manifest key")
        seen.add(path)
        if value is None:
            parents.append((indent, key))
        else:
            values[path] = value
    return values


def validate(directory):
    stamp = {}
    for line in (directory / "RELEASE").read_text().splitlines():
        key, sep, value = line.partition("=")
        if not sep or key in stamp:
            raise ValueError("invalid or duplicate RELEASE field")
        stamp[key] = value
    manifest = manifest_scalars((directory / "metadata/release-manifest.yaml").read_text())
    for key, value in VERSIONS.items():
        if stamp.get(key) != value:
            raise ValueError(f"RELEASE contract mismatch: {key}")
        if key.endswith("_contract_version"):
            path = ("release", "contract_versions", key.removesuffix("_contract_version"))
        elif key == "provider_registry_schema_version":
            path = ("release", "schema_versions", "provider_registry")
        else:
            path = ("release", key)
        if manifest.get(path) != value:
            raise ValueError(f"manifest contract mismatch: {key}")
    for key in PROVIDERS:
        if manifest.get(("release", "contract_versions", key)) != "1":
            raise ValueError("provider contract mismatch")
    for key, manifest_key in (("release_id", "id"), ("source_git_sha", "source_git_sha"),
                              ("provider_model_config_version", "provider_model_config_version")):
        if not stamp.get(key) or manifest.get(("release", manifest_key)) != stamp[key]:
            raise ValueError(f"release identity mismatch: {key}")
    sha = stamp["source_git_sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid source SHA")
    for service in ("ai_bridge", "ai_gateway"):
        if stamp.get(service + "_git_sha") != sha or manifest.get((service, "source_git_sha")) != sha:
            raise ValueError("service source mismatch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path)
    args = parser.parse_args()
    try:
        validate(args.release)
    except (OSError, ValueError):
        raise SystemExit("FAIL: D.6 release metadata invalid or unreadable") from None
    print("D.6 RELEASE METADATA: PASS (offline; not runtime validation)")
