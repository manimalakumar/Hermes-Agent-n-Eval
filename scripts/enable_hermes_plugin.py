from __future__ import annotations

import json
from pathlib import Path

import yaml


PLUGIN_NAME = "retail-agent"


def normalize_enabled(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
        return [value] if value else []
    return [str(value)]


def main() -> None:
    config_path = Path.home() / ".hermes" / "config.yaml"
    if not config_path.exists():
        raise SystemExit(f"Hermes config not found: {config_path}")
    data = yaml.safe_load(config_path.read_text()) or {}
    plugins = data.setdefault("plugins", {})
    enabled = normalize_enabled(plugins.get("enabled"))
    if PLUGIN_NAME not in enabled:
        enabled.append(PLUGIN_NAME)
    plugins["enabled"] = enabled
    config_path.write_text(yaml.safe_dump(data, sort_keys=False))
    print(f"Enabled Hermes plugin: {PLUGIN_NAME}")


if __name__ == "__main__":
    main()
