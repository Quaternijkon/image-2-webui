from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.models import InputImage, PreflightIssue


def read_image_metadata(path: Path) -> tuple[int, int, str]:
    with Image.open(path) as image:
        return image.width, image.height, image.format or path.suffix.lstrip(".").upper()


def validate_mask(mask_path: Path, source: InputImage) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []

    if not mask_path.exists():
        return [
            PreflightIssue(
                code="mask_missing",
                message=f"mask file does not exist: {mask_path}",
                path=mask_path,
            )
        ]

    try:
        with Image.open(mask_path) as mask:
            if (mask.width, mask.height) != (source.width, source.height):
                issues.append(
                    PreflightIssue(
                        code="mask_dimension_mismatch",
                        message="mask dimensions must match source image dimensions",
                        path=mask_path,
                        details={
                            "source_size": [source.width, source.height],
                            "mask_size": [mask.width, mask.height],
                        },
                    )
                )
            if "A" not in mask.getbands():
                issues.append(
                    PreflightIssue(
                        code="mask_missing_alpha",
                        message="mask image must include an alpha channel",
                        path=mask_path,
                    )
                )
    except (OSError, UnidentifiedImageError) as exc:
        issues.append(
            PreflightIssue(
                code="invalid_mask",
                message=f"mask image could not be read: {exc}",
                path=mask_path,
            )
        )

    return issues


__all__ = ["read_image_metadata", "validate_mask"]
