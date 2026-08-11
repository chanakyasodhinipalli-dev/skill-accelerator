#!/usr/bin/env python3
"""Convert markdown slide decks into simple HTML slide decks without external dependencies."""
from __future__ import annotations

import html
from pathlib import Path

SLIDE_FILES = [
    "docs/policy_checker_slide_deck.md",
    "docs/data_profiler_slide_deck.md",
    "docs/document_summarizer_slide_deck.md",
]

CSS = """
body { font-family: Arial, sans-serif; margin: 0; padding: 0; }
.slide { padding: 40px; min-height: 100vh; box-sizing: border-box; }
hr { border: none; border-top: 2px solid #ccc; margin: 1.5em 0; }
h1, h2, h3, h4 { margin: 0 0 0.5em; }
ul { margin: 0.5em 0 1.5em 1.25em; }
pre { background: #f5f5f5; padding: 1em; overflow-x: auto; }
code { font-family: Consolas, monospace; }
.section-title { color: #444; border-bottom: 1px solid #ddd; margin-bottom: 0.5em; }
"""


def render_markdown_to_html(text: str) -> str:
    lines = text.splitlines()
    parts: list[str] = []
    in_code = False
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            parts.append("</ul>")
            in_list = False

    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            close_list()
            parts.append("</section>")
            parts.append("<section class='slide'>")
            continue

        if stripped.startswith("```"):
            if in_code:
                parts.append("</code></pre>")
                in_code = False
            else:
                close_list()
                parts.append("<pre><code>")
                in_code = True
            continue

        if in_code:
            parts.append(html.escape(line))
            continue

        if not stripped:
            close_list()
            parts.append("")
            continue

        if stripped.startswith("# "):
            close_list()
            parts.append(f"<h1>{html.escape(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            close_list()
            parts.append(f"<h2>{html.escape(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            close_list()
            parts.append(f"<h3>{html.escape(stripped[4:])}</h3>")
        elif stripped.startswith("- "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            value = html.escape(stripped[2:])
            parts.append(f"  <li>{value}</li>")
        elif stripped.startswith("+ "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            value = html.escape(stripped[2:])
            parts.append(f"  <li>{value}</li>")
        elif stripped.startswith("* "):
            if not in_list:
                parts.append("<ul>")
                in_list = True
            value = html.escape(stripped[2:])
            parts.append(f"  <li>{value}</li>")
        else:
            close_list()
            parts.append(f"<p>{html.escape(stripped)}</p>")

    close_list()
    return "\n".join(parts)


def convert_file(path: Path) -> Path:
    content = path.read_text(encoding="utf-8")
    body = render_markdown_to_html(content)
    title = path.stem.replace("_", " ").title()
    html_text = f"""
<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <title>{html.escape(title)}</title>
  <style>{CSS}</style>
</head>
<body>
<section class='slide'><h1 class='section-title'>{html.escape(title)}</h1></section>
{body}
</body>
</html>
"""
    output = path.with_suffix(".html")
    output.write_text(html_text, encoding="utf-8")
    return output


def main() -> None:
    for file_path in SLIDE_FILES:
        path = Path(file_path)
        if not path.exists():
            print(f"Skipping missing file: {path}")
            continue
        output = convert_file(path)
        print(f"Converted {path} -> {output}")


if __name__ == "__main__":
    main()
