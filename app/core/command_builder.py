from pathlib import Path
from typing import Optional, Union

from app.core.config import AppConfig


PathLike = Union[str, Path]


class CommandBuilder:
    def __init__(self, config: Optional[AppConfig] = None) -> None:
        self.config = config

    def build_powershell_command(
        self,
        *,
        config_path: PathLike,
        input_dir: Optional[PathLike] = None,
        output_dir: Optional[PathLike] = None,
        concurrency: Optional[int] = None,
        events_jsonl: bool = True,
    ) -> str:
        resolved_output_dir = output_dir
        if resolved_output_dir is None and self.config is not None:
            resolved_output_dir = self.config.output.output_dir
        if resolved_output_dir is None:
            raise ValueError("output_dir is required to build a runnable command")

        lines = [
            "# Configure API credentials in the GUI/API config, or set OPENAI_API_KEY before running.",
            "python -m app run `",
            f"  --config {self._quote_powershell(config_path)} `",
        ]

        if input_dir is not None:
            lines.append(f"  --input-dir {self._quote_powershell(input_dir)} `")

        lines.append(f"  --output-dir {self._quote_powershell(resolved_output_dir)} `")

        resolved_concurrency = concurrency
        if resolved_concurrency is None and self.config is not None:
            resolved_concurrency = self.config.execution.concurrency

        if resolved_concurrency is not None:
            lines.append(f"  --concurrency {resolved_concurrency} `")

        if events_jsonl:
            lines.append("  --events-jsonl")
        else:
            lines[-1] = lines[-1].removesuffix(" `")

        return "\n".join(lines)

    @staticmethod
    def _quote_powershell(value: PathLike) -> str:
        text = str(value).replace("\\", "/")
        escaped = text.replace("`", "``").replace('"', '`"').replace("$", "`$")
        return f'"{escaped}"'
