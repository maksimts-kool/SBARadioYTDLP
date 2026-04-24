from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable
from zipfile import ZIP_DEFLATED, ZipFile

from pathvalidate import sanitize_filename


def safe_filename(name: str, fallback: str = "download") -> str:
    cleaned = sanitize_filename(name).strip(" .")
    return cleaned or fallback


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def zip_files(files: Iterable[Path], destination: Path) -> Path:
    used_names = set()
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for file_path in files:
            arcname = safe_filename(file_path.name)
            stem = Path(arcname).stem
            suffix = Path(arcname).suffix
            counter = 2
            while arcname.lower() in used_names:
                arcname = f"{stem} ({counter}){suffix}"
                counter += 1
            used_names.add(arcname.lower())
            archive.write(file_path, arcname=arcname)
    return destination

