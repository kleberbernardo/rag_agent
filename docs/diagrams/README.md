# Diagrams

`architecture.html` is the source of `docs/architecture.png`, and
`architecture.pt-BR.html` is the source of `docs/architecture.pt-BR.png`.
The Portuguese file is generated, never edited by hand.

## Changing the diagram

1. Edit `architecture.html`.
2. If any wording changed, add the pair to `TRADUCAO` in `translate.py` and
   run `python docs/diagrams/translate.py`. It reports any English string it
   could not find, which is how a forgotten translation shows up.
3. Re-render both, at twice the layout size so the type stays crisp when
   GitHub scales the image down:

```bash
python -m http.server 8099 --directory docs/diagrams
# then, in any headless browser at a 3900px viewport:
#   http://localhost:8099/architecture.html
#   http://localhost:8099/architecture.pt-BR.html
# full-page screenshot each one into docs/
```

The `html { zoom: 2 }` rule at the top of the stylesheet is what makes the 2x
raster. Remove it and the image is half the resolution.

## What does not belong in it

**No number that changes on its own.** Test counts, coverage, chunk counts and
image sizes go stale between commits and would mean regenerating both images
every time. Measurements that are historical, like "by article beat by
character", are facts about a decision and stay true.
