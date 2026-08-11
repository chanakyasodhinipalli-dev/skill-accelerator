Demo Instructions
=================

Run the skill demos locally (requires Python 3.8+).

1) Run the demo script

PowerShell / Command Prompt:

```powershell
python examples\skill_demos\run_demos.py
```

This will import the local `skills` packages and run small sample inputs for `policy_checker`, `data_profiler`, and `document_summarizer`.

2) Convert slide markdown to PDF (optional)

If you have `pandoc` installed you can convert a slide deck to PDF, for example:

```powershell
pandoc docs\policy_checker_slide_deck.md -o docs\policy_checker_slide_deck.pdf
```

If pandoc is unavailable, use the included converter script to generate HTML slide decks instead:

```powershell
python examples\skill_demos\convert_slide_decks.py
```

This produces:
- `docs\policy_checker_slide_deck.html`
- `docs\data_profiler_slide_deck.html`
- `docs\document_summarizer_slide_deck.html`

Notes:
- Pandoc must be installed and on PATH for PDF conversion. On Windows, install from https://pandoc.org/
- HTML export uses a dependency-free Python script and works without extra packages.
