#!/usr/bin/env python3
"""Install pinned operator-only skills for an AI-assisted SMB deployment session.

Never mount operator skills into Builder. The runtime mounts its own narrower,
read-only builder skill catalog through compose.smb.yaml.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "smb/skills.lock.json"
DESTINATION = ROOT / "runtime/smb/operator-skills"
SOURCE = "https://github.com/stanta/skills_superset"


def install(target: Path = DESTINATION) -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if lock.get("schema_version") != 1 or lock.get("source") != SOURCE:
        raise RuntimeError("Unapproved skills source")
    commit = lock.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Skills must be pinned to one full commit SHA")
    operator = lock.get("operator_skills")
    if not isinstance(operator, list) or not operator:
        raise RuntimeError("Missing operator skills manifest")
    for skill in operator:
        if not isinstance(skill, str) or not re.fullmatch(r"atomic-skills/[a-z0-9-]+", skill):
            raise RuntimeError("Invalid operator skill path")
    if target.is_symlink():
        raise RuntimeError("Refusing operator skill symlink destination")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hermeteam-operator-skills-") as tmp:
        clone = Path(tmp) / "repo"
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        subprocess.run(["git", "-C", str(clone), "remote", "add", "origin", SOURCE + ".git"], check=True)
        subprocess.run(["git", "-C", str(clone), "sparse-checkout", "set", *operator], check=True)
        subprocess.run(["git", "-C", str(clone), "fetch", "--depth=1", "origin", commit], check=True)
        subprocess.run(["git", "-C", str(clone), "checkout", "--detach", "-q", "FETCH_HEAD"], check=True)
        actual = subprocess.check_output(["git", "-C", str(clone), "rev-parse", "HEAD"], text=True).strip()
        if actual != commit:
            raise RuntimeError("Operator skills checkout does not match the lock SHA")
        ready = Path(tmp) / "ready"
        ready.mkdir()
        for skill in operator:
            source = clone / skill
            if not (source / "SKILL.md").is_file():
                raise RuntimeError(f"Pinned operator skill missing: {skill}")
            shutil.copytree(source, ready / source.name, symlinks=False)
        # Never replace active skills during a running deployment session.
        if target.exists():
            raise RuntimeError("Operator skills are already installed; review a new lock before replacing them")
        ready.replace(target)
    print(f"Operator skills connected at pinned revision {commit[:12]}: {len(operator)} read-only references")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=DESTINATION)
    args = parser.parse_args()
    try:
        install(args.target)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Operator skills installation failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
