# ADR-0010: Web pages under a strict Content Security Policy

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

The web service sends a strict Content Security Policy and HSTS, and uses HTMX for partial updates.

## Decision

No page loads scripts from a CDN or uses inline styles, so the default FastAPI docs pages are off and htmx indicator styles are off. Markdown goes through the `js-default` preset. The theme script loads in `<head>` without `defer`. Read routes also answer `HEAD`. The decisions below give the details.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `src/fpl/web/app.py` › `READ_METHODS = ["GET", "HEAD"]`
  - FastAPI routes answer HEAD only when asked to; uptime monitors send it.
- `src/fpl/web/app.py` › `app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`
  - The default /docs page loads scripts from a CDN, which the CSP blocks.
- `src/fpl/web/static/app.js` › `const root = document.documentElement;`
  - Loaded in <head> without defer, so the saved theme and sidebar state apply before the first paint.
- `src/fpl/web/templates/base.html` › `<meta name="htmx-config" content='{"includeIndicatorStyles": false}'>`
  - htmx adds an inline style for its indicators unless told not to; the CSP blocks inline styles.
- `src/fpl/web/templates/history_results.html` › `{% if not full_page %}`
  - Returned alone for HTMX requests; the count then updates out of band.
- `src/fpl/web/templating.py` › `_markdown = MarkdownIt("js-default")`
  - The js-default preset escapes raw HTML and refuses javascript: and data: links.
- `src/fpl/web/templating.py` › `templates.env.policies["json.dumps_kwargs"] = {"ensure_ascii": False}`
  - Keep accented player names readable and tool fields in the order the tool returned them.

## Consequences

- A new script or style must be a static file under src/fpl/web/static.
- A new read route must use `READ_METHODS`.
