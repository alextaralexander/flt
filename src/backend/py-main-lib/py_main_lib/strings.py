"""Text and templates for messages."""

from __future__ import annotations

from importlib.abc import Traversable
from importlib.resources import as_file
from typing import Any, Protocol, cast

from mako.lookup import TemplateLookup


class FormatTemplate(Protocol):
    """Protocol for correct templates typing.

    Allow use format() instead of render() method that needed to maintain consistency
    with regular string formatting.
    """

    def format(self, **kwargs: Any) -> str:  # noqa: WPS125 A003
        """Render template."""


class TemplateFormatterLookup(TemplateLookup):
    """Represent a collection of templates from the local filesystem."""

    def get_template(self, uri: str) -> FormatTemplate:
        """Cast default mako template to FormatTemplate."""

        def _format(**kwargs: Any) -> str:  # noqa: WPS430
            render_result = template.render(**kwargs)
            return cast(str, render_result).rstrip()

        template = super().get_template(uri)
        template.format = _format  # noqa: WPS125
        return cast(FormatTemplate, template)


def get_lookup(_templates_ref: Traversable) -> TemplateFormatterLookup:
    with as_file(_templates_ref) as _templates_dir:
        lookup = TemplateFormatterLookup(
            directories=[str(_templates_dir)],
            input_encoding="utf-8",
            strict_undefined=True,
        )
    return lookup


# TEMPLATES
# COMPARE_BRANCHES_TEMPLATE = lookup.get_template("compare_branches_template.txt.mako")
# FOR_EACH_LOOP_VARIANT_TEMPLATE = lookup.get_template("find_loop_iters_template.txt.mako")
# WHILE_CONDITION_TEMPLATE = lookup.get_template("while_condition_template.txt.mako")
