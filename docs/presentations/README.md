# Presentations

Slide decks for talks and videos about `podcast-ctl`, written in
[Marp](https://marp.app/) Markdown — plain text, versioned in Git, renderable
to HTML, PDF, PPTX, or images.

| Deck | Language |
| :--- | :--- |
| [`cli-tour-en.md`](cli-tour-en.md) | English |
| [`cli-tour-es.md`](cli-tour-es.md) | Español |

The decks cover only what is merged in `main`. When a release adds user-facing
features (e.g. embedding-based hybrid search), extend both decks together.

## Viewing and editing

- **VS Code**: install the *Marp for VS Code* extension and open the preview.
- **Anywhere**: `npx @marp-team/marp-cli docs/presentations/cli-tour-en.md`
  opens an HTML preview; add `-w` to watch for changes.

## Exporting

```bash
# PDF (one file per deck)
npx @marp-team/marp-cli docs/presentations/cli-tour-en.md --pdf
npx @marp-team/marp-cli docs/presentations/cli-tour-es.md --pdf

# PNG per slide (handy for video editing)
npx @marp-team/marp-cli docs/presentations/cli-tour-en.md --images png
```

HTML comments (`<!-- ... -->`) inside the decks are presenter notes / talk
track and do not render on the slides.

## Why Marp

Slides live in Markdown: diffable in PRs, editable with the same workflow as
the code, no binary formats, and exportable to PDF/PPTX when a conference or
video pipeline needs it.
