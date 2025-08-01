"""Generates markdown tables for all tokens."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


generated_templates_dir = Path("docs/snippets/generated_templates")


def write_token_out(
    path: Path,
    items: list[tuple[str, str]],
    double_bracket: bool = False,
    bracket_space: bool = False,
) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write("| Token | Description |\n|-------|-------------|\n")
        for token, desc in items:
            if bracket_space:
                t = f"{{{{ {token} }}}}" if double_bracket else f"{{ {token} }}"
            else:
                t = f"{{{{{token}}}}}" if double_bracket else f"{{{token}}}"
            f.write(f"| `{t}` | {desc} |\n")


def main() -> None:
    from src.backend.tokens import FileToken, NfoToken, Tokens

    generated_templates_dir = Path("docs/snippets/generated_templates")
    generated_templates_dir.mkdir(exist_ok=True, parents=True)

    file_tokens = []
    nfo_tokens = []
    for attr in dir(Tokens):
        value = getattr(Tokens, attr)
        if isinstance(value, FileToken):
            file_tokens.append((value.token.strip("{}"), value.description))
        elif isinstance(value, NfoToken):
            nfo_tokens.append((value.token.strip("{}"), value.description))
    file_tokens.sort()
    nfo_tokens.sort()

    write_token_out(path=generated_templates_dir / "file_tokens.md", items=file_tokens)
    write_token_out(
        path=generated_templates_dir / "nfo_tokens.md",
        items=nfo_tokens,
        double_bracket=True,
        bracket_space=True,
    )


if __name__ == "__main__":
    main()
