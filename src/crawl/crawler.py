"""Stage 1 — UI layer.

LLM-guided Playwright crawl, scoped to the seed screens in config/target.yaml.
For each seed it (optionally) performs an interaction to reveal UI, then captures:
  - a screenshot
  - the interactive elements (role, accessible label, stable selector, text)
  - the transition that produced the screen (which element click led here)

Why scripted-with-seeds instead of autonomous browser-use free-roam: for a gradeable
slice we want reproducible, debuggable artifacts over an agent that wanders differently
each run. Crawl BREADTH is the layer we deliberately scoped down (see CONTEXT.md).

The capture itself is fully deterministic. An optional LLM pass can relabel ambiguous
elements, but accessible labels from the DOM already carry most of the signal, so the
crawl runs with no API key.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from src.config import Settings
from src.common.models import Screen, UIElement, Edge

# Elements worth capturing as testable UI surface.
_INTERACTIVE_JS = r"""
() => {
  const out = [];
  const sel = 'button,[role="button"],[role="menuitem"],[role="menuitemradio"],a[href],input,select,textarea,[aria-label][tabindex]';
  const nodes = Array.from(document.querySelectorAll(sel));
  for (const el of nodes) {
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    const label = (el.getAttribute('aria-label') || el.getAttribute('title') ||
                   el.innerText || el.value || el.getAttribute('alt') || '').trim().slice(0, 120);
    if (!label) continue;
    out.push({
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      label,
      testid: el.getAttribute('data-testid') || '',
      ariaLabel: el.getAttribute('aria-label') || '',
      cls: (el.getAttribute('class') || '').split(' ').filter(Boolean).slice(0,2).join('.'),
      title: el.getAttribute('title') || '',
    });
  }
  return out;
}
"""


def _selector_for(e: dict, tag_role: str) -> str:
    if e["testid"]:
        return f'[data-testid="{e["testid"]}"]'
    if e["ariaLabel"]:
        return f'[aria-label="{e["ariaLabel"]}"]'
    if e["cls"]:
        return f'.{e["cls"]}'
    return tag_role


def _visible(page, selector: str) -> bool:
    for sel in selector.split(","):
        try:
            if page.locator(sel.strip()).first.is_visible(timeout=1500):
                return True
        except Exception:
            continue
    return False


def _perform(page, actions: list[dict]) -> bool:
    """Run an action sequence. Returns False if any step can't be performed."""
    for act in actions:
        try:
            if "click" in act:
                page.click(act["click"], timeout=4000)
            elif "click_text" in act:
                page.get_by_text(act["click_text"], exact=False).first.click(timeout=4000)
            elif "key" in act:
                page.keyboard.press(act["key"])
            page.wait_for_timeout(700)
        except PWTimeout:
            return False
        except Exception:
            return False
    return True


def _capture_screen(page, screen_id: str, url: str) -> tuple[Screen, list[UIElement]]:
    title = page.title()
    shot_dir = page.context._shot_dir  # set by caller
    rel_shot = f"screens/{screen_id}.png"
    page.screenshot(path=str(shot_dir.parent / rel_shot))
    raw = page.evaluate(_INTERACTIVE_JS)

    elements: list[UIElement] = []
    seen: set[tuple[str, str]] = set()
    for i, e in enumerate(raw):
        label = e["label"]
        key = (e["role"], label.lower())
        if key in seen:  # dedupe by role+label
            continue
        seen.add(key)
        selector = _selector_for(e, e["role"])
        elements.append(
            UIElement(
                id=f"{screen_id}::{i}:{label[:40]}",
                screen_id=screen_id,
                role=e["role"],
                label=label,
                selector=selector,
                text=e["title"] or label,
            )
        )
    return Screen(id=screen_id, url=url, title=title, screenshot=rel_shot), elements


def run(settings: Settings) -> None:
    app = settings.cfg["app"]
    base_url = app["base_url"]
    seeds = app.get("seeds", [])
    out_dir = settings.artifacts_dir
    (out_dir / "screens").mkdir(exist_ok=True)

    screens: list[Screen] = []
    elements: list[UIElement] = []
    transitions: list[Edge] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        context._shot_dir = out_dir / "screens"  # stash for _capture_screen
        page = context.new_page()

        print(f"  loading {base_url}")
        page.goto(base_url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(1500)
        # dismiss any first-run overlay by pressing Escape / clicking canvas
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

        for seed in seeds[: app.get("max_screens", 8)]:
            sid = seed["id"]
            actions = seed.get("actions", [])
            opened = _perform(page, actions) if actions else True
            if actions and seed.get("verify"):
                opened = opened and _visible(page, seed["verify"])
            if actions and not opened:
                print(f"  ! seed '{sid}': could not open (verify failed) — capturing base state")
            else:
                print(f"  capturing seed '{sid}'" + (" (opened)" if actions else ""))

            screen, els = _capture_screen(page, sid, page.url)
            screens.append(screen)
            elements.extend(els)
            if actions and opened:
                desc = ", ".join(next(iter(a.values())) for a in actions)
                transitions.append(
                    Edge(src="canvas", dst=sid, rel="TRANSITIONS_TO",
                         confidence=1.0, evidence=desc)
                )
            # reset to base state before the next seed
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
            except Exception:
                pass

        browser.close()

    payload = {
        "base_url": base_url,
        "n_screens": len(screens),
        "n_elements": len(elements),
        "screens": [asdict(s) for s in screens],
        "elements": [asdict(e) for e in elements],
        "transitions": [asdict(t) for t in transitions],
    }
    (out_dir / "ui.json").write_text(json.dumps(payload, indent=2))
    print(f"✓ crawl: {len(screens)} screens, {len(elements)} UI elements, "
          f"{len(transitions)} transitions -> {out_dir / 'ui.json'}")


if __name__ == "__main__":
    from src import config
    run(config.load())
