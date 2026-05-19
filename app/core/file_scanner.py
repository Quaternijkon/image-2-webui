from pathlib import Path

from PIL import UnidentifiedImageError

from app.core.config import InputConfig
from app.core.image_validator import read_image_metadata, validate_mask
from app.core.models import InputImage, PreflightIssue, ScanResult

FILE_ATTRIBUTE_HIDDEN = 0x2


def scan_input_images(config: InputConfig) -> ScanResult:
    if config.input_dir is None or not config.input_dir.exists():
        if config.mode == "generate":
            return ScanResult()
        missing = config.input_dir if config.input_dir is not None else Path("")
        raise FileNotFoundError(f"input directory does not exist: {missing}")

    if not config.input_dir.is_dir():
        raise NotADirectoryError(f"input path is not a directory: {config.input_dir}")

    extensions = _normalize_extensions(config.extensions)
    candidates = _iter_candidates(config.input_dir, recursive=config.recursive)
    images: list[InputImage] = []
    issues: list[PreflightIssue] = []

    for path in candidates:
        if path.suffix.lower() not in extensions:
            continue

        try:
            width, height, image_format = read_image_metadata(path)
        except (OSError, UnidentifiedImageError) as exc:
            issue = PreflightIssue(
                code="invalid_image",
                message=f"image could not be read: {exc}",
                path=path,
            )
            issues.append(issue)
            images.append(
                InputImage(
                    path=path,
                    width=0,
                    height=0,
                    format="UNKNOWN",
                    validation_status="validation_failed",
                    issues=[issue],
                )
            )
            continue

        image = InputImage(path=path, width=width, height=height, format=image_format)
        if config.mask_dir is not None:
            image, mask_issues = _attach_mask(image, config.mask_dir)
            issues.extend(mask_issues)
        images.append(image)

    return ScanResult(images=images, issues=issues)


def _normalize_extensions(extensions: list[str]) -> set[str]:
    normalized: set[str] = set()
    for extension in extensions:
        text = extension.strip().lower()
        if not text:
            continue
        normalized.add(text if text.startswith(".") else f".{text}")
    return normalized


def _iter_candidates(input_dir: Path, *, recursive: bool) -> list[Path]:
    iterator = input_dir.rglob("*") if recursive else input_dir.glob("*")
    return sorted(
        (
            path
            for path in iterator
            if path.is_file()
            and not path.name.startswith(".")
            and not path.name.startswith("~$")
            and not _has_hidden_attribute(path)
        ),
        key=lambda path: path.as_posix().lower(),
    )


def _has_hidden_attribute(path: Path) -> bool:
    attributes = getattr(path.stat(), "st_file_attributes", 0)
    return bool(attributes & FILE_ATTRIBUTE_HIDDEN)


def _attach_mask(image: InputImage, mask_dir: Path) -> tuple[InputImage, list[PreflightIssue]]:
    issues: list[PreflightIssue] = []
    match = _find_mask(image.path, mask_dir)
    if isinstance(match, PreflightIssue):
        image.validation_status = "validation_failed"
        image.issues.append(match)
        return image, [match]

    if match is None:
        issue = PreflightIssue(
            code="mask_missing",
            message=f"no mask found for image: {image.path.name}",
            path=image.path,
        )
        image.validation_status = "validation_failed"
        image.issues.append(issue)
        return image, [issue]

    image.mask_path = match
    mask_issues = validate_mask(match, image)
    if mask_issues:
        image.validation_status = "validation_failed"
        image.issues.extend(mask_issues)
        issues.extend(mask_issues)
    return image, issues


def _find_mask(source_path: Path, mask_dir: Path) -> Path | PreflightIssue | None:
    if not mask_dir.exists():
        return PreflightIssue(
            code="mask_dir_missing",
            message=f"mask directory does not exist: {mask_dir}",
            path=mask_dir,
        )

    files = [path for path in mask_dir.iterdir() if path.is_file()]
    by_lower_name: dict[str, list[Path]] = {}
    for path in files:
        by_lower_name.setdefault(path.name.lower(), []).append(path)

    priorities = [
        source_path.name,
        f"{source_path.stem}_mask{source_path.suffix}",
        f"{source_path.stem}.mask{source_path.suffix}",
    ]
    for name in priorities:
        matches = sorted(by_lower_name.get(name.lower(), []), key=lambda path: path.name)
        if len(matches) > 1:
            return PreflightIssue(
                code="mask_conflict",
                message=f"multiple same-priority masks found for {source_path.name}",
                path=source_path,
                details={"candidates": [str(path) for path in matches]},
            )
        if matches:
            return matches[0]

    return None


__all__ = ["FILE_ATTRIBUTE_HIDDEN", "scan_input_images"]
