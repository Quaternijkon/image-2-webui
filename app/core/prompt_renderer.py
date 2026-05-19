from collections.abc import Mapping


class PromptRenderError(ValueError):
    pass


class PromptRenderer:
    def __init__(self, *, variables_enabled: bool, context: Mapping[str, object]) -> None:
        self.variables_enabled = variables_enabled
        self.context = dict(context)

    def render(self, template: str) -> str:
        if not self.variables_enabled:
            return template
        try:
            return template.format_map(_StrictFormatMap(self.context))
        except KeyError as exc:
            raise PromptRenderError(f"unknown prompt variable: {exc.args[0]}") from exc
        except ValueError as exc:
            raise PromptRenderError(f"malformed prompt template: {exc}") from exc


class _StrictFormatMap(dict[str, object]):
    def __missing__(self, key: str) -> object:
        raise KeyError(key)


__all__ = ["PromptRenderError", "PromptRenderer"]
