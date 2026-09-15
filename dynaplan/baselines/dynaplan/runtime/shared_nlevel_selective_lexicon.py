"""LexiCon adapter refinement for canonical validated H1 caching."""

from __future__ import annotations

from typing import Any

from shared_nlevel_lexicon import LexiconH1Library, SharedNLevelLexiconAdapter
from shared_nlevel_pipeline import ArtifactCheck


class SelectiveLexiconNLevelAdapter(SharedNLevelLexiconAdapter):
    """Cache a state-independent serialization of the validated H1 library."""

    state_descriptor_validation_authoritative = True

    def canonicalize_h1(
        self, task: Any, output: str, check: ArtifactCheck
    ) -> str:
        del task, output
        library = check.value
        if not isinstance(library, LexiconH1Library):
            raise TypeError("validated LexiCon H1 did not produce LexiconH1Library")
        mappings = []
        for name in sorted(library.mappings):
            mapping = library.mappings[name]
            header = f"{mapping.name}({', '.join(mapping.params)})"
            body = ", ".join(str(call) for call in mapping.calls)
            mappings.append(f"{header} = [{body}]")
        return "```start_mapping\n" + ",\n".join(mappings) + "\n```end_mapping"


__all__ = ["SelectiveLexiconNLevelAdapter"]
