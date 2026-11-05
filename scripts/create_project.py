"""Create a separate team project from the bundled configurable runtime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys


def create_project(target: Path) -> None:
    if target.exists():
        raise FileExistsError("기존 경로를 덮어쓰지 않습니다. 새 프로젝트 경로를 지정해주세요.")
    source = Path(__file__).resolve().parent.parent / "assets" / "runtime"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    config = json.loads((target / "config.example.json").read_text(encoding="utf-8"))
    config["python_executable"] = sys.executable
    (target / "config.local.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    create_project(args.target.resolve())
    print("새 프로젝트를 만들었습니다. config.local.json을 설정한 뒤 검증해주세요.")
