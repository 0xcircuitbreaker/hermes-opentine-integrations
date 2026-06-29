#!/usr/bin/env python3
"""
opentine-cli-commands — Cross-CLI Slash Command Installer
==========================================================

Installs opentine slash commands / MCP configs into supported AI agent CLIs:

  opentine-cli-commands install --target all       # install everywhere
  opentine-cli-commands install --target hermes     # Hermes plugin
  opentine-cli-commands install --target claude     # Claude Code commands
  opentine-cli-commands install --target codex      # Codex CLI MCP config
  opentine-cli-commands install --target opencode   # OpenCode MCP config
  opentine-cli-commands install --target kimi       # Kimi Code MCP config
  opentine-cli-commands install --target all --runs-dir ~/.tine_runs

  opentine-cli-commands uninstall --target claude   # remove from Claude Code
  opentine-cli-commands status                      # show what's installed

Each target installs the same opentine functionality in the format native
to that CLI:

- Hermes: Plugin with /tine, /tine fork, /tine diff, /tine replay, etc.
- Claude Code: Markdown prompt templates in ~/.claude/commands/
- Codex / OpenCode / Kimi Code: MCP server JSON config (opentine.mcp_server)

Copyright 2026 — Daedalus Development Group / 0xcircuitbreaker — MIT License
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Target definitions: name → (install function, description)
TARGETS = {
    "hermes": {
        "description": "Hermes Agent plugin (slash commands: /tine)",
        "dir": lambda: Path.home() / ".hermes/plugins/opentine",
    },
    "claude": {
        "description": "Claude Code markdown commands (/tine-list, /tine-show, etc.)",
        "dir": lambda: Path.home() / ".claude/commands",
    },
    "codex": {
        "description": "Codex CLI MCP server config",
        "dir": lambda: Path.home() / ".codex",
    },
    "opencode": {
        "description": "OpenCode MCP server config",
        "dir": lambda: Path.home() / ".opencode",
    },
    "kimi": {
        "description": "Kimi Code CLI MCP server config",
        "dir": lambda: Path.home() / ".kimi-code",
    },
}


def _fill_template(content: str, runs_dir: str) -> str:
    """Replace placeholder variables in templates."""
    return content.replace("~/.tine_runs", os.path.expanduser(runs_dir))


def _fill_json(template: dict, runs_dir: str) -> dict:
    """Fill runs_dir placeholders in a JSON config tree."""
    def _walk(obj):
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [_walk(item) for item in obj]
        elif isinstance(obj, str):
            return _fill_template(obj, runs_dir)
        return obj
    return _walk(template)  # type: ignore[return-value]


def install_hermes(runs_dir: str, force: bool = False) -> bool:
    """Install the Hermes opentine plugin."""
    target_dir = TARGETS["hermes"]["dir"]()

    # Check if the plugin already exists in the hermes-agent repo (bundled)
    # If so, just enable it in config
    bundled = Path.home() / ".hermes/hermes-agent/plugins/opentine"
    if bundled.exists():
        print(f"  ℹ️  Bundled plugin found at {bundled}")
        print(f"     Enable via: hermes config set plugins.enabled")
        return True

    target_dir.mkdir(parents=True, exist_ok=True)

    # Copy the plugin files from templates/hermes/
    src = TEMPLATES_DIR / "hermes"
    if not src.exists():
        print(f"  ⚠️  No Hermes plugin template found at {src}")
        return False

    for f in src.iterdir():
        dest = target_dir / f.name
        if dest.exists() and not force:
            print(f"  ⊘ {f.name} already exists (use --force to overwrite)")
            continue
        shutil.copy2(f, dest)
        print(f"  ✅ {f.name} → {dest}")

    print(f"\n  Enable in Hermes: hermes config set plugins.enabled")
    return True


def install_claude(runs_dir: str, force: bool = False) -> bool:
    """Install Claude Code slash command templates."""
    target_dir = TARGETS["claude"]["dir"]()
    target_dir.mkdir(parents=True, exist_ok=True)

    src = TEMPLATES_DIR / "claude"
    if not src.exists():
        print(f"  ⚠️  No Claude templates found at {src}")
        return False

    for f in src.glob("*.md"):
        dest = target_dir / f.name
        if dest.exists() and not force:
            print(f"  ⊘ {f.name} already exists (use --force to overwrite)")
            continue
        content = _fill_template(f.read_text(), runs_dir)
        dest.write_text(content)
        print(f"  ✅ {f.name} → {dest}")

    return True


def install_mcp_config(target: str, runs_dir: str, force: bool = False) -> bool:
    """Install MCP server config for Codex/OpenCode/Kimi."""
    target_dir = TARGETS[target]["dir"]()
    target_dir.mkdir(parents=True, exist_ok=True)

    src = TEMPLATES_DIR / target / "config.json"
    if target == "codex":
        src = TEMPLATES_DIR / target / "mcp_servers.json"
        dest = target_dir / "mcp_servers.json"
    elif target == "opencode":
        src = TEMPLATES_DIR / target / "config.json"
        dest = target_dir / "config.json"
    elif target == "kimi":
        src = TEMPLATES_DIR / target / "config.json"
        dest = target_dir / "config.json"
    else:
        return False

    if dest.exists() and not force:
        print(f"  ⊘ {dest.name} already exists (use --force to overwrite)")
        return True

    config = json.loads(src.read_text())
    config = _fill_json(config, runs_dir)
    dest.write_text(json.dumps(config, indent=2) + "\n")
    print(f"  ✅ {dest.name} → {dest}")
    return True


def install_target(target: str, runs_dir: str, force: bool = False) -> bool:
    """Install opentine commands for a single target."""
    info = TARGETS.get(target)
    if not info:
        print(f"  ❌ Unknown target: {target}")
        print(f"     Valid targets: {', '.join(TARGETS.keys())}")
        return False

    print(f"\n📦 Installing opentine for {target} ({info['description']})")
    print(f"   Runs dir: {runs_dir}")

    if target == "hermes":
        return install_hermes(runs_dir, force)
    elif target == "claude":
        return install_claude(runs_dir, force)
    elif target in ("codex", "opencode", "kimi"):
        return install_mcp_config(target, runs_dir, force)
    else:
        print(f"  ❌ No installer for target: {target}")
        return False


def uninstall_target(target: str) -> bool:
    """Remove opentine commands from a target CLI."""
    info = TARGETS.get(target)
    if not info:
        print(f"  ❌ Unknown target: {target}")
        return False

    target_dir = info["dir"]()
    print(f"\n🗑️  Uninstalling opentine from {target}...")

    if target == "hermes":
        plugin_dir = target_dir
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)
            print(f"  ✅ Removed {plugin_dir}")
        else:
            print(f"  ⊘ Nothing to remove at {plugin_dir}")
    elif target == "claude":
        for f in target_dir.glob("tine-*.md"):
            f.unlink()
            print(f"  ✅ Removed {f}")
        if not list(target_dir.glob("tine-*.md")):
            print(f"  ⊘ No tine-*.md commands found in {target_dir}")
    elif target in ("codex", "opencode", "kimi"):
        # Remove just the opentine entry from the config
        if target == "codex":
            config_file = target_dir / "mcp_servers.json"
            key = "mcpServers"
        elif target == "opencode":
            config_file = target_dir / "config.json"
            key = "mcp"
        else:
            config_file = target_dir / "config.json"
            key = "mcp_servers"

        if config_file.exists():
            try:
                config = json.loads(config_file.read_text())
                if key in config and "opentine" in config[key]:
                    del config[key]["opentine"]
                    config_file.write_text(json.dumps(config, indent=2) + "\n")
                    print(f"  ✅ Removed opentine from {config_file}")
                else:
                    print(f"  ⊘ No opentine entry in {config_file}")
            except Exception as e:
                print(f"  ❌ Failed to update {config_file}: {e}")
        else:
            print(f"  ⊘ No config at {config_file}")

    return True


def show_status() -> None:
    """Show what's installed across all targets."""
    print("opentine CLI Integration Status")
    print("=" * 50)

    for target, info in TARGETS.items():
        target_dir = info["dir"]()
        print(f"\n{target.upper()} ({info['description']})")

        if target == "hermes":
            plugin_file = target_dir / "__init__.py"
            if plugin_file.exists():
                print(f"  ✅ Plugin installed at {target_dir}")
            else:
                print(f"  ❌ Not installed")

        elif target == "claude":
            commands = list(target_dir.glob("tine-*.md")) if target_dir.exists() else []
            if commands:
                print(f"  ✅ {len(commands)} commands: {', '.join(c.stem for c in commands)}")
            else:
                print(f"  ❌ No tine-*.md commands in {target_dir}")

        elif target in ("codex", "opencode", "kimi"):
            if target == "codex":
                config_file = target_dir / "mcp_servers.json"
                key = "mcpServers"
            elif target == "opencode":
                config_file = target_dir / "config.json"
                key = "mcp"
            else:
                config_file = target_dir / "config.json"
                key = "mcp_servers"

            if config_file.exists():
                try:
                    config = json.loads(config_file.read_text())
                    if key in config and "opentine" in config[key]:
                        print(f"  ✅ MCP server configured in {config_file}")
                    else:
                        print(f"  ❌ No opentine in {config_file}")
                except Exception:
                    print(f"  ❌ Invalid JSON in {config_file}")
            else:
                print(f"  ❌ No config at {config_file}")


def main():
    parser = argparse.ArgumentParser(
        prog="opentine-cli-commands",
        description="Cross-CLI installer for opentine agent run provenance commands",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Install
    install_parser = sub.add_parser("install", help="Install opentine commands for a CLI")
    install_parser.add_argument(
        "--target", "-t",
        choices=list(TARGETS.keys()) + ["all"],
        default="all",
        help="Target CLI (default: all)",
    )
    install_parser.add_argument(
        "--runs-dir",
        default="~/.tine_runs",
        help="Directory for .tine run artifacts (default: ~/.tine_runs)",
    )
    install_parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing files",
    )

    # Uninstall
    uninstall_parser = sub.add_parser("uninstall", help="Remove opentine commands from a CLI")
    uninstall_parser.add_argument(
        "--target", "-t",
        choices=list(TARGETS.keys()) + ["all"],
        required=True,
        help="Target CLI",
    )

    # Status
    sub.add_parser("status", help="Show what's installed across all CLIs")

    args = parser.parse_args()

    if args.command == "install":
        runs_dir = os.path.expanduser(args.runs_dir)
        if args.target == "all":
            print("📦 Installing opentine for all supported CLIs")
            print(f"   Runs dir: {runs_dir}\n")
            results = []
            for target in TARGETS:
                results.append(install_target(target, runs_dir, args.force))
            print(f"\n{'='*50}")
            success = sum(results)
            total = len(results)
            print(f"✅ {success}/{total} targets installed successfully")
        else:
            ok = install_target(args.target, runs_dir, args.force)
            sys.exit(0 if ok else 1)

    elif args.command == "uninstall":
        if args.target == "all":
            for target in TARGETS:
                uninstall_target(target)
        else:
            uninstall_target(args.target)

    elif args.command == "status":
        show_status()


if __name__ == "__main__":
    main()
