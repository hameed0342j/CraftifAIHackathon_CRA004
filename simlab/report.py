"""Self-contained HTML incident report: the evidence-to-action chain of one run."""

from __future__ import annotations

import html
import json
from pathlib import Path

STATE_HEX = {"IDLE": "#5ac85a", "SUSPECT": "#ffc800", "CONFIRMING": "#ff8c00", "CLOSED": "#ff3030",
             "VERIFYING": "#ff3030", "LATCHED": "#2f7bff", "FAULT": "#c000ff"}


def _chart(timeline: list[dict], zone: str, w: int = 760, h: int = 220) -> str:
    if not timeline:
        return ""
    t_end = timeline[-1]["t"] or 1.0
    amax = max(max(s["zones"][zone]["true_area"], s["zones"][zone]["seen_area"]) for s in timeline) or 0.1
    amax *= 1.15
    pad_l, pad_b, pad_t = 46, 26, 10
    pw, ph = w - pad_l - 10, h - pad_b - pad_t
    X = lambda t: pad_l + pw * t / t_end  # noqa: E731
    Y = lambda a: pad_t + ph * (1 - a / amax)  # noqa: E731
    parts = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="pool area over time, {zone}">']
    prev, start = None, 0.0
    for s in timeline + [{"t": t_end, "zones": {zone: {"state": None}}}]:  # state bands
        st = s["zones"][zone]["state"]
        if st != prev:
            if prev is not None:
                parts.append(f'<rect x="{X(start):.1f}" y="{pad_t}" width="{max(0.5, X(s["t"]) - X(start)):.1f}" '
                             f'height="{ph}" fill="{STATE_HEX.get(prev, "#888")}" opacity="0.13"><title>{prev}'
                             f'</title></rect>')
            prev, start = st, s["t"]
    for key, col, dash in (("true_area", "#888", "4 3"), ("seen_area", "#1f6feb", "")):
        pts = " ".join(f"{X(s['t']):.1f},{Y(s['zones'][zone][key]):.1f}" for s in timeline)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2" '
                     f'stroke-dasharray="{dash}"/>')
    for k in range(5):
        a = amax * k / 4
        parts.append(f'<text x="{pad_l - 6}" y="{Y(a) + 4:.1f}" text-anchor="end" class="ax">{a:.2f}</text>')
    for k in range(6):
        t = t_end * k / 5
        parts.append(f'<text x="{X(t):.1f}" y="{h - 8}" text-anchor="middle" class="ax">{t:.0f}s</text>')
    parts.append(f'<text x="{pad_l}" y="{pad_t + 12}" class="ax">m2  (dashed: true pool, blue: PipeGen)</text>')
    parts.append("</svg>")
    return "".join(parts)


def write(out: Path, sc, summary: dict, timeline: list[dict], records: list[dict]) -> Path:
    e = html.escape
    events = [r for r in records if r["topic"].endswith("/event")]
    receipts = [r for r in records if r["topic"].endswith("/receipt")]
    rows = []
    for zid, z in summary["zones"].items():
        zr = [r for r in receipts if r["payload"]["zone_id"] == zid]
        if not zr and not any(ev["payload"]["zone_id"] == zid for ev in events):
            continue
        chain = []
        trig = zr[0]["payload"]["trigger_event_id"] if zr else ""
        first = next((ev for ev in events if ev["payload"]["event_id"] == trig), None)
        if first:
            p = first["payload"]
            snap = p.get("evidence", {}).get("snapshot")
            img = (f'<img src="{e(Path(snap).as_posix())}" alt="evidence snapshot" loading="lazy">'
                   if snap else "")
            chain.append(f'<li><b>{first["t"]:.1f}s evidence</b> vision {e(p["kind"])} '
                         f'<code>{e(p["event_id"][:12])}</code> conf {p["confidence"]:.2f}, '
                         f'pool {p["pool_area"]:.3f} m2, growth {p["growth_rate"]:+.3f} m2/min{img}</li>')
        for r in zr:
            p = r["payload"]
            v = p["verification"]
            extra = ""
            if p["to"] in ("LATCHED", "FAULT"):
                extra = (f' &middot; mechanical {"yes" if v["mechanical"] else "no"} '
                         f'({v.get("mechanical_ms", 0)} ms), hydraulic {"yes" if v["hydraulic"] else "no"} '
                         f'(growth after close {v["growth_after_close"]:+.3f}), attempts {v["close_attempts"]}')
            chain.append(f'<li><b>{r["t"]:.1f}s</b> <span class="st" style="--c:{STATE_HEX.get(p["from"])}">'
                         f'{p["from"]}</span> &rarr; <span class="st" style="--c:{STATE_HEX.get(p["to"])}">'
                         f'{p["to"]}</span> <i>{e(p["reason"])}</i> &middot; wet {p["evidence"]["wet"]}, '
                         f'limit switch {p["evidence"]["limit_switch"]}{extra}</li>')
        rows.append(f"""
<section class="zone"><h2>{e(zid)} <span class="st" style="--c:{STATE_HEX.get(z['final_state'])}">
{z['final_state']}</span> <small>{e(z['final_reason'])}</small></h2>
<dl><dt>leak starts</dt><dd>{z['leak_start_s'] if z['leak_start_s'] is not None else '-'} s</dd>
<dt>first vision detect</dt><dd>{z['first_detect_s'] if z['first_detect_s'] is not None else '-'} s</dd>
<dt>valve closed</dt><dd>{z['valve_closed_s'] if z['valve_closed_s'] is not None else 'never'} s</dd>
<dt>water lost</dt><dd>{z['water_lost_l']} L</dd>
<dt>zone-lock rejections</dt><dd>{z['zone_lock_rejections']}</dd></dl>
{_chart(timeline, zid)}
<ol class="chain">{''.join(chain) or '<li>no receipts</li>'}</ol></section>""")
    checks = "".join(f'<li class="{"ok" if c["ok"] else "bad"}">{"PASS" if c["ok"] else "FAIL"} &middot; '
                     f'{e(c["check"])}</li>' for c in summary["checks"])
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>LeakLatch run: {e(sc.title)}</title>
<style>
:root{{--bg:#fff;--fg:#1d2127;--mut:#5b6470;--card:#f5f7fa;--line:#dde3ea}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111418;--fg:#e8ecf1;--mut:#9aa5b1;--card:#1a1f26;--line:#2b333d}}}}
body{{font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:24px 16px}}
main{{max-width:840px;margin:auto}} h1{{margin:0 0 4px;font-size:24px}} p.story{{color:var(--mut)}}
.zone{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}}
h2{{margin:0 0 8px;font-size:18px}} h2 small{{color:var(--mut);font-weight:400}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:2px 14px;margin:0 0 10px}} dt{{color:var(--mut)}}
.st{{display:inline-block;padding:0 7px;border-radius:5px;background:color-mix(in srgb,var(--c) 28%,transparent);
font-weight:600;font-size:13px}}
.chart{{width:100%;height:auto;margin:6px 0}} .ax{{font-size:11px;fill:var(--mut)}}
ol.chain li{{margin:6px 0}} ol.chain img{{display:block;max-width:100%;border-radius:6px;margin-top:6px}}
ul.checks{{list-style:none;padding:0}} .ok{{color:#2da44e}} .bad{{color:#d1242f}} code{{font-size:12px}}
</style></head><body><main>
<h1>{e(sc.title)}</h1><p class="story">{e(sc.story)}</p>
<p>backend <code>{e(summary['backend'])}</code> &middot; {summary['messages']} MQTT messages &middot;
simulated {summary['duration_s']:.0f} s in {summary['wall_time_s']} s</p>
<ul class="checks">{checks}</ul>
{''.join(rows)}
</main></body></html>"""
    path = out / "report.html"
    path.write_text(doc, encoding="utf-8")
    return path
