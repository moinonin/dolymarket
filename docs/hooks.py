"""MkDocs build hooks.

Post-build: replace the indigo primary (#4051b5) with the Dolymarket teal
(#00d492) everywhere it appears in the generated CSS, so the docs site never
ships the indigo colour even in cached palette stylesheets.
"""
from pathlib import Path


def on_post_build(config, **kwargs):
    site_dir = Path(config.site_dir)
    for css_file in site_dir.rglob("*.css"):
        try:
            text = css_file.read_text(encoding="utf-8")
        except OSError:
            continue
        changed = False
        if "#4051b5" in text:
            text = text.replace("#4051b5", "#00d492")
            changed = True
        if "#526cfe" in text:
            text = text.replace("#526cfe", "#00d492")
            changed = True
        if changed:
            css_file.write_text(text, encoding="utf-8")