# Changelog

Versions follow [SemVer](https://semver.org/). Details for each version are on the [Releases](https://github.com/AThevon/quizz/releases) page.

## 1.8.0 (2026-11-21)

- The quiz interface now exists in English: a quiz with `"langue": "en"` gets English buttons, help, overview, summary, Dig in, Reframe, save states, dates and the prompts sent to the in-page Claude. Claude writes the quiz in your language and sets the field when you talk to it in English. Without the field, the page is French and byte for byte the same as before.
- Interface strings live in `skills/quizz/langues/` (one file per language), the template only holds `{{key}}` markers. `build.py` refuses an unknown language with a clear message.
- The theme preview (`build.py --apercu --langue en`) and the one-time theme tip follow the language too.
- README and changelog in English, screenshots retaken from an English quiz.

## 1.7.1 (2026-11-21)

- Reworked README: badges, quiz screenshots, gallery of the five themes, commands as a table.
- This changelog, and a fuller plugin manifest (homepage, keywords).

## 1.7.0 (2026-11-21)

- Themes are discoverable: the page's `?` help reminds the quiz author of `/quizz theme`, and Claude mentions it once, on the first quiz of someone who has no theme yet.

## 1.6.0 (2026-11-21)

- New built-in theme `homie`: the glass bubble of the Homie suite (pastel sky, milky glass, white edges, very rounded, Fredoka and Figtree, small Homie orb).
- Themes accept an optional `matiere` (sky, glass, blur, edge, shapes, orb, radius per level). The four existing themes render identically.

## 1.5.1 (2026-11-18)

- More compact Dig in panel: quick asks on one line, your question and "Ask" side by side.

## 1.5.0 (2026-11-16)

- Solo by default, with others on request.
- Visuals keep their shape (portrait, square, landscape), photo orientation respected.
- `verifie.py`: checks and captures every visual in headless Chrome before publishing.
- A single decision log (`~/.claude/quizz-registre.json`).

Earlier versions have no tag: see the commit history.
