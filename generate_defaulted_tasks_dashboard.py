#!/usr/bin/env python3
"""
ADIRI Defaulted Tasks Dashboard Generator
Fetches overdue, unfinished tasks from the last two sprints in Jira project AD
and regenerates index.html.
"""

import json
import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional

import requests

# Configuration
JIRA_URL = "https://aiincorg.atlassian.net"
JIRA_USERNAME = os.environ.get("JIRA_USERNAME", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")

PROJECT_KEY = "AD"
SPRINT_FIELD = "customfield_10020"
EXCLUDED_LABELS = [
    '"remainder"', "Adiri_monthly", "Adiri_weekly", "salon_weekly",
    "salon_monthly", "bimonthly", '"daily-task"', '"Payment-Duedate"', "Housekeeping",
]
OUTPUT_PATH = "index.html"


TEMPLATE_HEAD = '\ufeff<meta charset="utf-8">\n<title>Defaulted Tasks</title>\n<style>\n  :root {\n    color-scheme: light;\n    --bg: #f9f9f7;\n    --surface: #fcfcfb;\n    --surface-raised: #ffffff;\n    --text-primary: #0b0b0b;\n    --text-secondary: #52514e;\n    --text-muted: #898781;\n    --border: rgba(11,11,11,0.10);\n    --grid: #e1e0d9;\n    --accent: #2a78d6;\n    --accent-soft: #cde2fb;\n    --accent-ink: #184f95;\n    --status-good: #0ca30c;\n    --status-warning: #fab219;\n    --status-serious: #ec835a;\n    --status-critical: #d03b3b;\n    --row-hover: #f0efec;\n    --chip-bg: #f0efec;\n  }\n  @media (prefers-color-scheme: dark) {\n    :root:not([data-theme="light"]) {\n      color-scheme: dark;\n      --bg: #0d0d0d;\n      --surface: #1a1a19;\n      --surface-raised: #202020;\n      --text-primary: #ffffff;\n      --text-secondary: #c3c2b7;\n      --text-muted: #898781;\n      --border: rgba(255,255,255,0.10);\n      --grid: #2c2c2a;\n      --accent: #3987e5;\n      --accent-soft: #184f95;\n      --accent-ink: #cde2fb;\n      --status-good: #0ca30c;\n      --status-warning: #fab219;\n      --status-serious: #ec835a;\n      --status-critical: #d03b3b;\n      --row-hover: #242422;\n      --chip-bg: #242422;\n    }\n  }\n  :root[data-theme="dark"] {\n    color-scheme: dark;\n    --bg: #0d0d0d;\n    --surface: #1a1a19;\n    --surface-raised: #202020;\n    --text-primary: #ffffff;\n    --text-secondary: #c3c2b7;\n    --text-muted: #898781;\n    --border: rgba(255,255,255,0.10);\n    --grid: #2c2c2a;\n    --accent: #3987e5;\n    --accent-soft: #184f95;\n    --accent-ink: #cde2fb;\n    --status-good: #0ca30c;\n    --status-warning: #fab219;\n    --status-serious: #ec835a;\n    --status-critical: #d03b3b;\n    --row-hover: #242422;\n    --chip-bg: #242422;\n  }\n\n  * { box-sizing: border-box; }\n  body {\n    margin: 0;\n    background: var(--bg);\n    color: var(--text-primary);\n    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;\n    padding-inline: 20px;\n    padding-block: 20px 40px;\n  }\n  .wrap { max-width: 1180px; margin: 0 auto; }\n\n  header.page { margin-bottom: 20px; }\n  .eyebrow {\n    font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;\n    color: var(--accent-ink); margin: 0 0 6px;\n  }\n  h1 { font-size: 26px; font-weight: 800; margin: 0 0 4px; letter-spacing: -0.01em; }\n  .subtitle { font-size: 14px; color: var(--text-secondary); margin: 0; }\n\n  .sync-bar {\n    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;\n    font-size: 12.5px; color: var(--text-secondary);\n    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;\n    padding: 8px 12px; margin-bottom: 16px;\n  }\n  .sync-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-muted); flex: none; }\n  .sync-dot.live { background: var(--status-good); box-shadow: 0 0 0 3px rgba(12,163,12,0.15); }\n  .sync-dot.syncing { background: var(--status-warning); animation: sync-pulse 1.1s ease-in-out infinite; }\n  .sync-dot.error, .sync-dot.needs_reauth { background: var(--status-critical); }\n  @keyframes sync-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }\n  .sync-btn {\n    margin-left: auto; font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 6px;\n    border: 1px solid var(--border); background: var(--surface-raised); color: var(--accent-ink); cursor: pointer;\n  }\n  .sync-btn:hover:not(:disabled) { border-color: var(--accent); }\n  .sync-btn:disabled { opacity: 0.5; cursor: default; }\n\n  .stats {\n    display: grid;\n    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));\n    gap: 10px;\n    margin: 20px 0 22px;\n  }\n  .stat-tile {\n    background: var(--surface);\n    border: 1px solid var(--border);\n    border-radius: 10px;\n    padding: 14px 16px;\n  }\n  .stat-tile .label { font-size: 11.5px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }\n  .stat-tile .value { font-size: 28px; font-weight: 800; font-variant-numeric: tabular-nums; margin-top: 4px; }\n  .stat-tile.grand { border-color: var(--accent); background: linear-gradient(180deg, var(--accent-soft) 0%, var(--surface) 130%); }\n  .stat-tile.grand .value { color: var(--accent-ink); }\n  .stat-tile .sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }\n\n  .chart-card {\n    background: var(--surface);\n    border: 1px solid var(--border);\n    border-radius: 10px;\n    padding: 16px 18px 14px;\n    margin-bottom: 22px;\n  }\n  .chart-title { font-size: 13px; font-weight: 700; color: var(--text-secondary); margin: 0 0 4px; text-transform: uppercase; letter-spacing: 0.04em; }\n  .chart-hint { font-size: 12px; color: var(--text-muted); margin: 0 0 16px; }\n  .bar-plot { position: relative; padding-left: 2px; }\n  .bar-row, .bar-ticks-row { display: flex; align-items: center; gap: 14px; }\n  .bar-row { margin-bottom: 16px; border-radius: 6px; transition: opacity 0.2s ease; }\n  .bar-row-label, .bar-row-spacer { flex: 0 0 190px; min-width: 0; }\n  .bar-sprint-name { display: block; font-size: 13px; font-weight: 700; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }\n  .bar-row-label .state-badge { margin-top: 3px; }\n  .bar-track { flex: 1 1 auto; position: relative; height: 26px; background: var(--chip-bg); border-radius: 4px; min-width: 0; }\n  .bar-fill { position: absolute; left: 0; top: 0; height: 100%; border-radius: 4px; transition: width 0.4s ease; }\n  .bar-value, .bar-value-spacer { flex: 0 0 44px; font-size: 13.5px; font-weight: 800; color: var(--text-primary); font-variant-numeric: tabular-nums; white-space: nowrap; }\n\n  .bar-row-clickable { cursor: pointer; }\n  .bar-row-clickable:hover .bar-sprint-name { color: var(--accent); }\n  .bar-row-clickable:hover .bar-track { outline: 1px solid var(--accent); outline-offset: 1px; }\n  .bar-row-clickable:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }\n  .bar-plot.has-selection .bar-row:not(.selected) { opacity: 0.4; }\n  .bar-row.selected .bar-sprint-name { color: var(--accent-ink); }\n  .bar-row.selected .bar-track { outline: 2px solid var(--accent); outline-offset: 1px; }\n  .bar-ticks-row { margin-top: 2px; }\n  .bar-ticks-track { flex: 1 1 auto; display: flex; justify-content: space-between; min-width: 0; }\n  .bar-ticks-track span { font-size: 10.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }\n  .bar-gridlines { position: absolute; inset: 0; display: flex; justify-content: space-between; pointer-events: none; }\n  .bar-gridlines span { width: 1px; height: 100%; background: var(--grid); }\n\n  .controls {\n    display: flex; flex-wrap: wrap; gap: 8px; align-items: center;\n    margin-bottom: 18px;\n  }\n  .search {\n    flex: 1 1 220px;\n    min-width: 0;\n    background: var(--surface);\n    border: 1px solid var(--border);\n    border-radius: 8px;\n    padding: 9px 12px;\n    font-size: 14px;\n    color: var(--text-primary);\n  }\n  .search:focus { outline: 2px solid var(--accent); outline-offset: -1px; }\n  .search::placeholder { color: var(--text-muted); }\n\n  .select {\n    background: var(--surface);\n    border: 1px solid var(--border);\n    border-radius: 8px;\n    padding: 9px 30px 9px 12px;\n    font-size: 14px;\n    color: var(--text-primary);\n    font-family: inherit;\n    cursor: pointer;\n  }\n  .select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }\n\n  .chip-group { display: flex; gap: 6px; flex-wrap: wrap; }\n  .chip {\n    font-size: 12.5px; font-weight: 600; padding: 7px 12px; border-radius: 999px;\n    background: var(--chip-bg); border: 1px solid var(--border); color: var(--text-secondary);\n    cursor: pointer; user-select: none; white-space: nowrap;\n  }\n  .chip:hover { border-color: var(--accent); }\n  .chip[aria-pressed="true"] {\n    background: var(--accent); color: #fff; border-color: var(--accent);\n  }\n  .chip .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }\n\n  section.sprint { margin-bottom: 26px; }\n  .sprint-head {\n    display: flex; align-items: baseline; justify-content: space-between; gap: 10px;\n    flex-wrap: wrap;\n    padding: 4px 2px 10px;\n    border-bottom: 2px solid var(--grid);\n    margin-bottom: 0;\n  }\n  .sprint-title-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }\n  .sprint-name { font-size: 17px; font-weight: 800; }\n  .state-badge {\n    font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;\n    padding: 3px 8px; border-radius: 5px;\n  }\n  .state-badge.active { background: var(--accent); color: #fff; }\n  .state-badge.closed { background: var(--chip-bg); color: var(--text-secondary); border: 1px solid var(--border); }\n  .state-badge.rank { background: var(--chip-bg); color: var(--text-muted); border: 1px solid var(--border); font-variant-numeric: tabular-nums; }\n  .sprint-range { font-size: 12.5px; color: var(--text-muted); }\n  .sprint-count { font-size: 14px; color: var(--text-secondary); font-weight: 600; font-variant-numeric: tabular-nums; }\n  .sprint-count b { color: var(--text-primary); font-size: 16px; }\n\n  .table-scroll { overflow-x: auto; border: 1px solid var(--border); border-top: none; border-radius: 0 0 10px 10px; background: var(--surface); }\n  table { width: 100%; border-collapse: collapse; font-size: 13.5px; min-width: 720px; }\n  thead th {\n    position: sticky; top: 0; background: var(--surface-raised);\n    text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;\n    color: var(--text-muted); font-weight: 700; padding: 10px 12px;\n    border-bottom: 1px solid var(--border);\n    cursor: pointer; white-space: nowrap;\n  }\n  thead th.num { text-align: right; }\n  thead th .arrow { opacity: 0.35; font-size: 10px; margin-left: 3px; }\n  thead th.sorted .arrow { opacity: 1; color: var(--accent); }\n  tbody td { padding: 9px 12px; border-bottom: 1px solid var(--grid); vertical-align: top; }\n  tbody tr:last-child td { border-bottom: none; }\n  tbody tr:hover { background: var(--row-hover); }\n  tbody tr[hidden] { display: none; }\n\n  td.key a { color: var(--accent); text-decoration: none; font-weight: 700; font-variant-numeric: tabular-nums; }\n  td.key a:hover { text-decoration: underline; }\n  td.summary { color: var(--text-primary); max-width: 340px; }\n  td.assignee { color: var(--text-secondary); white-space: nowrap; }\n  td.due { color: var(--text-secondary); white-space: nowrap; font-variant-numeric: tabular-nums; }\n  td.status .status-pill {\n    display: inline-block; font-size: 11.5px; font-weight: 600; padding: 2px 8px;\n    border-radius: 5px; background: var(--chip-bg); color: var(--text-secondary); border: 1px solid var(--border);\n    white-space: nowrap;\n  }\n  td.overdue { text-align: right; white-space: nowrap; }\n  .overdue-wrap { display: inline-flex; align-items: center; gap: 6px; justify-content: flex-end; }\n  .overdue-num { font-weight: 800; font-variant-numeric: tabular-nums; font-size: 14px; }\n  .sev-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }\n  .sev-label { font-size: 10.5px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; font-weight: 700; }\n\n  .empty-row td { text-align: center; color: var(--text-muted); padding: 24px; font-size: 13.5px; }\n\n  footer.note { margin-top: 18px; font-size: 12px; color: var(--text-muted); line-height: 1.6; }\n  footer.note code { background: var(--chip-bg); padding: 1px 5px; border-radius: 4px; }\n\n  @media (max-width: 560px) {\n    h1 { font-size: 21px; }\n    .stat-tile .value { font-size: 22px; }\n    td.summary { max-width: 200px; }\n  }\n</style>\n\n<div class="wrap">\n  <header class="page">\n    <p class="eyebrow">ADIRI &middot; Jira Project AD</p>\n    <h1>Defaulted Tasks</h1>\n    <p class="subtitle">Overdue, unfinished tasks across the last two sprints</p>\n  </header>\n\n  <div class="sync-bar" id="sync-bar">\n    <span class="sync-dot" id="sync-dot"></span>\n    <span class="sync-text" id="sync-text">Loading snapshot&hellip;</span>\n    <button class="sync-btn" id="sync-refresh" type="button" hidden>Refresh now</button>\n  </div>\n\n  <div class="stats" id="stats"></div>\n\n  <div class="chart-card">\n    <p class="chart-title">Defaulted tasks by assignee &mdash; highest to lowest</p>\n    <p class="chart-hint">Click a name to filter the task list below to that assignee. Click again to clear.</p>\n    <div id="bar-chart-assignee"></div>\n  </div>\n\n  <div class="controls">\n    <input class="search" id="search" type="text" placeholder="Filter by key, summary, or assignee&hellip;" />\n    <select class="select" id="assignee-filter">\n      <option value="all">All assignees</option>\n    </select>\n    <div class="chip-group" id="severity-filters">\n      <button class="chip" data-severity="all" aria-pressed="true">All severities</button>\n      <button class="chip" data-severity="Recent"><span class="dot" style="background:var(--status-warning)"></span>Recent (&le;7d)</button>\n      <button class="chip" data-severity="Aging"><span class="dot" style="background:var(--status-serious)"></span>Aging (8&ndash;30d)</button>\n      <button class="chip" data-severity="Severe"><span class="dot" style="background:var(--status-critical)"></span>Severe (&gt;30d)</button>\n    </div>\n  </div>\n\n  <div id="sprints"></div>\n\n  <footer class="note">\n    Excludes tasks labeled <code>reminder</code>, <code>adiri-monthly</code>, <code>adiri-weekly</code>, <code>salon weekly</code>, <code>salon monthly</code>, <code>bimonthly</code>, <code>daily task</code>, <code>payment duedate</code>, or <code>housekeeping</code>. "Defaulted" = due date has passed and status is not Done/Closed. Click a column header to sort within a sprint; click a task key to open it in Jira.\n  </footer>\n</div>\n\n<script>\n(function () {\n'
TEMPLATE_MIDDLE = '\n  function severityOf(days) {\n    if (days <= 7) return "Recent";\n    if (days <= 30) return "Aging";\n    return "Severe";\n  }\n  function severityColorVar(sev) {\n    if (sev === "Recent") return "var(--status-warning)";\n    if (sev === "Aging") return "var(--status-serious)";\n    return "var(--status-critical)";\n  }\n  function fmtDate(iso) {\n    var d = new Date(iso + "T00:00:00");\n    if (isNaN(d)) return iso;\n    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });\n  }\n  function escapeHtml(s) {\n    return String(s).replace(/[&<>"\']/g, function (c) {\n      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", \'"\': "&quot;", "\'": "&#39;" }[c];\n    });\n  }\n\n  var state = { search: "", severity: "all", assignee: "all", sort: {} };\n\n  function applyFilters(rows) {\n    var q = state.search.trim().toLowerCase();\n    return rows.filter(function (r) {\n      if (state.severity !== "all" && r._severity !== state.severity) return false;\n      if (state.assignee !== "all" && r.Assignee !== state.assignee) return false;\n      if (!q) return true;\n      return (\n        r.Key.toLowerCase().indexOf(q) !== -1 ||\n        r.Summary.toLowerCase().indexOf(q) !== -1 ||\n        r.Assignee.toLowerCase().indexOf(q) !== -1\n      );\n    });\n  }\n\n  function sortRows(rows, sprintName) {\n    var s = state.sort[sprintName] || { col: "DaysOverdue", dir: "desc" };\n    var col = s.col, dir = s.dir === "asc" ? 1 : -1;\n    return rows.slice().sort(function (a, b) {\n      var av = a[col], bv = b[col];\n      if (col === "DaysOverdue") { av = a.DaysOverdue; bv = b.DaysOverdue; }\n      if (col === "DueDate") { av = a.DueDate; bv = b.DueDate; }\n      if (typeof av === "string") av = av.toLowerCase();\n      if (typeof bv === "string") bv = bv.toLowerCase();\n      if (av < bv) return -1 * dir;\n      if (av > bv) return 1 * dir;\n      return 0;\n    });\n  }\n\n  function renderStats(all) {\n    var el = document.getElementById("stats");\n    var bySprint = {};\n    SPRINTS.forEach(function (s) { bySprint[s.name] = 0; });\n    all.forEach(function (r) { bySprint[r.Sprint] = (bySprint[r.Sprint] || 0) + 1; });\n\n    var html = \'<div class="stat-tile grand"><div class="label">Grand total</div><div class="value">\' + all.length + \'</div><div class="sub">defaulted tasks</div></div>\';\n    SPRINTS.forEach(function (s) {\n      html += \'<div class="stat-tile"><div class="label">\' + escapeHtml(s.name) + \'</div><div class="value">\' + (bySprint[s.name] || 0) + \'</div><div class="sub">\' + s.state + \' &middot; \' + s.range + \'</div></div>\';\n    });\n    el.innerHTML = html;\n  }\n\n  function niceStep(rawStep) {\n    var mag = Math.pow(10, Math.floor(Math.log(rawStep) / Math.LN10));\n    var norm = rawStep / mag;\n    var niceNorm = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;\n    return niceNorm * mag;\n  }\n  function computeTicks(maxValue, targetCount) {\n    if (maxValue <= 0) return { max: 1, ticks: [0, 1] };\n    var step = niceStep(maxValue / targetCount);\n    var niceMax = Math.ceil(maxValue / step) * step;\n    var ticks = [];\n    for (var v = 0; v <= niceMax + 1e-9; v += step) ticks.push(Math.round(v));\n    return { max: niceMax, ticks: ticks };\n  }\n\n  // items: [{ label, badge: {text, cls} | null, value, color }]\n  // opts: { clickable, selected, onClick(label) }\n  function renderBarChart(elId, items, targetTickCount, opts) {\n    opts = opts || {};\n    var el = document.getElementById(elId);\n    var maxVal = Math.max.apply(null, items.map(function (it) { return it.value; }).concat([0]));\n    var scale = computeTicks(maxVal, targetTickCount || 5);\n    var hasSelection = !!opts.selected;\n\n    var rows = items.map(function (it) {\n      var pct = scale.max ? (it.value / scale.max) * 100 : 0;\n      var isSelected = opts.selected === it.label;\n      var rowCls = "bar-row" + (opts.clickable ? " bar-row-clickable" : "") + (isSelected ? " selected" : "");\n      var a11y = opts.clickable ? \' tabindex="0" role="button" aria-pressed="\' + isSelected + \'" aria-label="Filter task list to \' + escapeHtml(it.label) + \'"\' : "";\n      return \'<div class="\' + rowCls + \'" data-label="\' + escapeHtml(it.label) + \'"\' + a11y + \'>\' +\n        \'<div class="bar-row-label">\' +\n          \'<span class="bar-sprint-name">\' + escapeHtml(it.label) + "</span>" +\n          (it.badge ? \'<span class="state-badge \' + it.badge.cls + \'">\' + escapeHtml(it.badge.text) + "</span>" : "") +\n        "</div>" +\n        \'<div class="bar-track">\' +\n          \'<div class="bar-gridlines">\' + scale.ticks.map(function () { return "<span></span>"; }).join("") + "</div>" +\n          \'<div class="bar-fill" style="width:\' + pct + \'%; background:\' + it.color + \';"></div>\' +\n        "</div>" +\n        \'<span class="bar-value">\' + it.value + "</span>" +\n      "</div>";\n    }).join("");\n\n    var tickRow = \'<div class="bar-ticks-row">\' +\n      \'<div class="bar-row-spacer"></div>\' +\n      \'<div class="bar-ticks-track">\' + scale.ticks.map(function (t) { return "<span>" + t + "</span>"; }).join("") + "</div>" +\n      \'<span class="bar-value-spacer"></span>\' +\n    "</div>";\n\n    el.innerHTML = \'<div class="bar-plot\' + (hasSelection ? " has-selection" : "") + \'">\' + rows + tickRow + "</div>";\n\n    if (opts.clickable && opts.onClick) {\n      el.querySelectorAll(".bar-row-clickable").forEach(function (rowEl) {\n        var label = rowEl.getAttribute("data-label");\n        rowEl.addEventListener("click", function () { opts.onClick(label); });\n        rowEl.addEventListener("keydown", function (e) {\n          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); opts.onClick(label); }\n        });\n      });\n    }\n  }\n\n  function renderAssigneeChart(all) {\n    var counts = {};\n    (typeof TEAM_ROSTER !== "undefined" ? TEAM_ROSTER : []).forEach(function (name) { counts[name] = 0; });\n    all.forEach(function (r) { counts[r.Assignee] = (counts[r.Assignee] || 0) + 1; });\n    var names = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });\n\n    var items = names.map(function (name, i) {\n      return {\n        label: name,\n        badge: { text: "#" + (i + 1), cls: "rank" },\n        value: counts[name],\n        color: "var(--accent)"\n      };\n    });\n    renderBarChart("bar-chart-assignee", items, 5, {\n      clickable: true,\n      selected: state.assignee !== "all" ? state.assignee : null,\n      onClick: function (label) {\n        state.assignee = state.assignee === label ? "all" : label;\n        document.getElementById("assignee-filter").value = state.assignee;\n        renderAssigneeChart(ALL_ROWS);\n        render();\n        var target = document.getElementById("sprints");\n        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });\n      }\n    });\n  }\n\n  function populateAssigneeFilter(all) {\n    var sel = document.getElementById("assignee-filter");\n    var counts = {};\n    (typeof TEAM_ROSTER !== "undefined" ? TEAM_ROSTER : []).forEach(function (name) { counts[name] = 0; });\n    all.forEach(function (r) { counts[r.Assignee] = (counts[r.Assignee] || 0) + 1; });\n    var names = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });\n    var keepSelection = names.indexOf(state.assignee) !== -1 ? state.assignee : "all";\n    sel.innerHTML = \'<option value="all">All assignees</option>\';\n    names.forEach(function (name) {\n      var opt = document.createElement("option");\n      opt.value = name;\n      opt.textContent = name + " (" + counts[name] + ")";\n      sel.appendChild(opt);\n    });\n    state.assignee = keepSelection;\n    sel.value = keepSelection;\n  }\n\n  function columnLabel(col) {\n    return { Key: "Key", Summary: "Summary", Assignee: "Assignee", DueDate: "Due date", Status: "Status", DaysOverdue: "Days overdue" }[col];\n  }\n\n  function renderSprintTable(sprintMeta, rows) {\n    var visible = sortRows(applyFilters(rows), sprintMeta.name);\n    var cols = ["Key", "Summary", "Assignee", "DueDate", "Status", "DaysOverdue"];\n    var sortState = state.sort[sprintMeta.name] || { col: "DaysOverdue", dir: "desc" };\n\n    var thead = "<thead><tr>" + cols.map(function (c) {\n      var sorted = sortState.col === c;\n      var arrow = sorted ? (sortState.dir === "desc" ? "&#9660;" : "&#9650;") : "&#9660;";\n      var numCls = c === "DaysOverdue" ? " num" : "";\n      return \'<th class="\' + (sorted ? "sorted" : "") + numCls + \'" data-col="\' + c + \'" data-sprint="\' + escapeHtml(sprintMeta.name) + \'">\' + columnLabel(c) + \'<span class="arrow">\' + arrow + \'</span></th>\';\n    }).join("") + "</tr></thead>";\n\n    var body = "";\n    if (visible.length === 0) {\n      body = \'<tr class="empty-row"><td colspan="6">No tasks match the current filters.</td></tr>\';\n    } else {\n      body = visible.map(function (r) {\n        var sev = r._severity;\n        return "<tr>" +\n          \'<td class="key"><a href="https://aiincorg.atlassian.net/browse/\' + encodeURIComponent(r.Key) + \'" target="_blank" rel="noopener">\' + escapeHtml(r.Key) + "</a></td>" +\n          \'<td class="summary">\' + escapeHtml(r.Summary) + "</td>" +\n          \'<td class="assignee">\' + escapeHtml(r.Assignee) + "</td>" +\n          \'<td class="due">\' + fmtDate(r.DueDate) + "</td>" +\n          \'<td class="status"><span class="status-pill">\' + escapeHtml(r.Status) + "</span></td>" +\n          \'<td class="overdue"><span class="overdue-wrap"><span class="sev-dot" style="background:\' + severityColorVar(sev) + \'"></span><span class="overdue-num">\' + r.DaysOverdue + \'d</span><span class="sev-label">\' + sev + "</span></span></td>" +\n          "</tr>";\n      }).join("");\n    }\n\n    return \'<div class="table-scroll"><table>\' + thead + "<tbody>" + body + "</tbody></table></div>";\n  }\n\n  var ALL_ROWS = [];\n\n  function render() {\n    var container = document.getElementById("sprints");\n    var html = "";\n    SPRINTS.forEach(function (meta) {\n      var rows = ALL_ROWS.filter(function (r) { return r.Sprint === meta.name; });\n      var visibleCount = applyFilters(rows).length;\n      html += \'<section class="sprint">\' +\n        \'<div class="sprint-head">\' +\n          \'<div class="sprint-title-group">\' +\n            \'<span class="sprint-name">\' + escapeHtml(meta.name) + "</span>" +\n            \'<span class="state-badge \' + meta.state.toLowerCase() + \'">\' + meta.state + "</span>" +\n            \'<span class="sprint-range">\' + meta.range + "</span>" +\n          "</div>" +\n          \'<span class="sprint-count"><b>\' + visibleCount + "</b> / " + rows.length + " shown</span>" +\n        "</div>" +\n        renderSprintTable(meta, rows) +\n        "</section>";\n    });\n    container.innerHTML = html;\n\n    container.querySelectorAll("thead th").forEach(function (th) {\n      th.addEventListener("click", function () {\n        var col = th.getAttribute("data-col");\n        var sprint = th.getAttribute("data-sprint");\n        var cur = state.sort[sprint] || { col: "DaysOverdue", dir: "desc" };\n        var dir = cur.col === col && cur.dir === "desc" ? "asc" : "desc";\n        state.sort[sprint] = { col: col, dir: dir };\n        render();\n      });\n    });\n  }\n\n  function refreshAll() {\n    renderStats(ALL_ROWS);\n    renderAssigneeChart(ALL_ROWS);\n    populateAssigneeFilter(ALL_ROWS);\n    render();\n  }\n\n  function seedFromSnapshot(rows) {\n    ALL_ROWS = rows.map(function (r) {\n      r._severity = severityOf(r.DaysOverdue);\n      return r;\n    });\n    refreshAll();\n  }\n\n  function wireControls() {\n    document.getElementById("search").addEventListener("input", function (e) {\n      state.search = e.target.value;\n      render();\n    });\n\n    document.getElementById("assignee-filter").addEventListener("change", function (e) {\n      state.assignee = e.target.value;\n      renderAssigneeChart(ALL_ROWS);\n      render();\n    });\n\n    document.querySelectorAll("#severity-filters .chip").forEach(function (chip) {\n      chip.addEventListener("click", function () {\n        document.querySelectorAll("#severity-filters .chip").forEach(function (c) { c.setAttribute("aria-pressed", "false"); });\n        chip.setAttribute("aria-pressed", "true");\n        state.severity = chip.getAttribute("data-severity");\n        render();\n      });\n    });\n\n    document.getElementById("sync-refresh").addEventListener("click", function () {\n      refreshFromJira();\n    });\n  }\n\n  // ---- Live Jira sync -------------------------------------------------\n  var CLOUD_ID = "a4706d26-f792-4cbe-97a1-58e720c74a1a";\n  var SEARCH_TOOL = "searchJiraIssuesUsingJql";\n  var REFRESH_MS = 5 * 60 * 1000;\n  var EXCLUDED_LABELS = \'"remainder", Adiri_monthly, Adiri_weekly, salon_weekly, salon_monthly, bimonthly, "daily-task", "Payment-Duedate", Housekeeping\';\n  var mcpNS = null;\n  var mcpServer = null;\n\n  function todayStr() {\n    var d = new Date();\n    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");\n  }\n  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }\n  function fmtRange(startIso, endIso) {\n    var s = new Date(startIso), e = new Date(endIso);\n    var sMon = s.toLocaleDateString("en-US", { month: "short" });\n    var eMon = e.toLocaleDateString("en-US", { month: "short" });\n    var y = e.getFullYear();\n    return sMon === eMon\n      ? sMon + " " + s.getDate() + " &ndash; " + e.getDate() + ", " + y\n      : sMon + " " + s.getDate() + " &ndash; " + eMon + " " + e.getDate() + ", " + y;\n  }\n  function buildDefaultedJql(ids) {\n    return \'project = AD AND sprint in (\' + ids.join(",") + \') AND duedate < "\' + todayStr() +\n      \'" AND statusCategory != Done AND labels not in (\' + EXCLUDED_LABELS + \') ORDER BY duedate ASC\';\n  }\n\n  function setSyncStatus(kind, meta) {\n    var dot = document.getElementById("sync-dot");\n    var text = document.getElementById("sync-text");\n    var btn = document.getElementById("sync-refresh");\n    dot.className = "sync-dot " + kind;\n    btn.hidden = true;\n    btn.disabled = false;\n    if (kind === "loading") {\n      text.textContent = "Loading snapshot…";\n    } else if (kind === "syncing") {\n      text.textContent = "Syncing with Jira…";\n    } else if (kind === "live") {\n      text.textContent = "Live from Jira — synced " + new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });\n      btn.hidden = false;\n    } else if (kind === "unavailable") {\n      text.textContent = "Static snapshot — connect the Atlassian Rovo connector in claude.ai Settings → Connectors to enable live sync.";\n    } else if (kind === "needs_reauth") {\n      text.textContent = "Jira connection lapsed — reconnect Atlassian Rovo in claude.ai Settings → Connectors.";\n      btn.hidden = false;\n    } else if (kind === "server_not_connected") {\n      text.textContent = "Atlassian Rovo isn\'t connected — add it in claude.ai Settings → Connectors to enable live sync.";\n    } else if (kind === "error") {\n      text.textContent = "Couldn\'t sync with Jira" + (meta && meta.message ? " (" + meta.message + ")" : "") + " — showing last known data.";\n      btn.hidden = false;\n    }\n  }\n\n  function transformNodes(nodes, sprintIds) {\n    var idSet = {};\n    sprintIds.forEach(function (id) { idSet[id] = true; });\n    var today = new Date(); today.setHours(0, 0, 0, 0);\n    var rows = [];\n    nodes.forEach(function (n) {\n      var f = n.fields;\n      if (!f || !f.duedate) return;\n      var sprintMatch = (f.customfield_10020 || []).filter(function (s) { return idSet[s.id]; });\n      var due = new Date(f.duedate + "T00:00:00");\n      rows.push({\n        Key: n.key,\n        Summary: f.summary,\n        Assignee: (f.assignee && f.assignee.displayName) || "Unassigned",\n        DueDate: f.duedate,\n        Status: f.status.name,\n        Sprint: sprintMatch.length ? sprintMatch[0].name : "Unknown sprint",\n        DaysOverdue: Math.round((today - due) / 86400000)\n      });\n    });\n    return rows;\n  }\n\n  function callSearch(input) {\n    return mcpNS.callTool(mcpServer, SEARCH_TOOL, input, { cache: false });\n  }\n\n  async function detectSprints() {\n    var res = await callSearch({\n      cloudId: CLOUD_ID,\n      jql: "project = AD AND sprint is not EMPTY ORDER BY updated DESC",\n      maxResults: 50,\n      fields: ["customfield_10020"]\n    });\n    var nodes = (res.payload && res.payload.issues && res.payload.issues.nodes) || [];\n    var byId = {};\n    nodes.forEach(function (n) {\n      ((n.fields && n.fields.customfield_10020) || []).forEach(function (s) { byId[s.id] = s; });\n    });\n    var all = Object.keys(byId).map(function (k) { return byId[k]; });\n    var active = all.filter(function (s) { return s.state === "active"; });\n    var closed = all.filter(function (s) { return s.state === "closed"; })\n      .sort(function (a, b) { return new Date(b.endDate) - new Date(a.endDate); });\n    var chosen = [];\n    if (active.length) chosen.push(active[0]);\n    closed.forEach(function (s) { if (chosen.length < 2) chosen.push(s); });\n    return chosen.slice(0, 2);\n  }\n\n  async function fetchAllDefaulted(jql) {\n    var all = [];\n    var token;\n    var guard = 0;\n    do {\n      var input = {\n        cloudId: CLOUD_ID,\n        jql: jql,\n        maxResults: 100,\n        fields: ["summary", "assignee", "duedate", "status", "customfield_10020"]\n      };\n      if (token) input.nextPageToken = token;\n      var res = await callSearch(input);\n      var payload = res.payload && res.payload.issues;\n      all = all.concat((payload && payload.nodes) || []);\n      token = payload && payload.pageInfo && payload.pageInfo.hasNextPage ? payload.pageInfo.endCursor : null;\n      guard++;\n    } while (token && guard < 30);\n    return all;\n  }\n\n  async function refreshFromJira() {\n    if (!mcpNS || !mcpServer) return;\n    setSyncStatus("syncing");\n    try {\n      var sprints = await detectSprints();\n      if (!sprints.length) throw { message: "no active or recent sprint found" };\n      var ids = sprints.map(function (s) { return s.id; });\n      var nodes = await fetchAllDefaulted(buildDefaultedJql(ids));\n      var rows = transformNodes(nodes, ids);\n\n      SPRINTS = sprints.map(function (s) {\n        return { name: s.name, state: cap(s.state), range: fmtRange(s.startDate, s.endDate) };\n      });\n      ALL_ROWS = rows.map(function (r) { r._severity = severityOf(r.DaysOverdue); return r; });\n      refreshAll();\n      setSyncStatus("live");\n    } catch (err) {\n      var code = err && err.code;\n      if (code === "needs_reauth" || code === "server_not_connected" || code === "consent_required") {\n        setSyncStatus(code === "server_not_connected" ? "server_not_connected" : "needs_reauth");\n      } else {\n        setSyncStatus("error", err);\n      }\n    }\n  }\n\n  async function initLiveSync() {\n    if (!window.claude || !window.claude.use) { setSyncStatus("unavailable"); return; }\n    try {\n      mcpNS = await window.claude.use("mcp");\n    } catch (e) { mcpNS = null; }\n    if (!mcpNS) { setSyncStatus("unavailable"); return; }\n    try {\n      var list = await mcpNS.listTools();\n      var entry = (list.servers || [])[0];\n      if (!entry) { setSyncStatus("unavailable"); return; }\n      mcpServer = entry.server;\n    } catch (e) { setSyncStatus("unavailable"); return; }\n    await refreshFromJira();\n    setInterval(refreshFromJira, REFRESH_MS);\n  }\n\n  wireControls();\n\n  seedFromSnapshot([\n'
TEMPLATE_TAIL = ']\n);\n\n  initLiveSync();\n})();\n</script>\n'



class JiraClient:
    def __init__(self, url: str, username: str, api_token: str):
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, api_token)
        self.session.headers.update({"Accept": "application/json"})

    def search_all(self, jql: str, fields: List[str], max_results: int = 100, guard_limit: int = 30) -> List[Dict]:
        """Paginate through /rest/api/3/search/jql (the current Jira Cloud search API;
        the old GET /rest/api/3/search endpoint now returns 410 Gone) until all issues are collected."""
        all_issues: List[Dict] = []
        next_token: Optional[str] = None
        guard = 0
        while True:
            body = {
                "jql": jql,
                "maxResults": max_results,
                "fields": fields,
            }
            if next_token:
                body["nextPageToken"] = next_token
            response = self.session.post(f"{self.url}/rest/api/3/search/jql", json=body, timeout=30)
            response.raise_for_status()
            data = response.json()
            issues = data.get("issues", [])
            all_issues.extend(issues)
            guard += 1
            next_token = data.get("nextPageToken")
            if not issues or not next_token or data.get("isLast") or guard >= guard_limit:
                break
        return all_issues

    def detect_sprints(self) -> List[Dict]:
        """Mirror the dashboard's live-sync detectSprints(): the active sprint (if any)
        plus the most recently closed sprint(s), found among recently updated AD issues."""
        issues = self.search_all(
            jql=f"project = {PROJECT_KEY} AND sprint is not EMPTY ORDER BY updated DESC",
            fields=[SPRINT_FIELD],
            max_results=50,
            guard_limit=1,
        )
        by_id: Dict[int, Dict] = {}
        for issue in issues:
            for sprint in issue.get("fields", {}).get(SPRINT_FIELD) or []:
                by_id.setdefault(sprint["id"], sprint)

        all_sprints = list(by_id.values())
        active = [s for s in all_sprints if s.get("state") == "active"]
        closed = sorted(
            (s for s in all_sprints if s.get("state") == "closed"),
            key=lambda s: s.get("endDate") or "",
            reverse=True,
        )

        chosen: List[Dict] = []
        if active:
            chosen.append(active[0])
        for sprint in closed:
            if len(chosen) >= 2:
                break
            chosen.append(sprint)
        return chosen[:2]

    def list_team_roster(self, project_key: str) -> List[str]:
        """Real (non-bot) users assignable to issues in the project, per Jira's
        assignable-users search. accountType == "atlassian" filters out Jira/Rovo
        automation accounts (Claude Agent for Jira, Jira Triage Agent, etc.)."""
        response = self.session.get(
            f"{self.url}/rest/api/3/user/assignable/search",
            params={"project": project_key, "maxResults": 50},
            timeout=30,
        )
        response.raise_for_status()
        users = response.json()
        names = sorted({
            u["displayName"] for u in users
            if u.get("accountType") == "atlassian" and u.get("displayName")
        })
        return names


def cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def parse_jira_datetime(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def fmt_range(start_iso: str, end_iso: str) -> str:
    s = parse_jira_datetime(start_iso)
    e = parse_jira_datetime(end_iso)
    s_mon, e_mon = s.strftime("%b"), e.strftime("%b")
    if s_mon == e_mon:
        return f"{s_mon} {s.day} &ndash; {e.day}, {e.year}"
    return f"{s_mon} {s.day} &ndash; {e_mon} {e.day}, {e.year}"


def build_defaulted_jql(sprint_ids: List[int]) -> str:
    ids = ",".join(str(i) for i in sprint_ids)
    labels = ", ".join(EXCLUDED_LABELS)
    today = date.today().isoformat()
    return (
        f"project = {PROJECT_KEY} AND sprint in ({ids}) AND duedate < \"{today}\" "
        f"AND statusCategory != Done AND labels not in ({labels}) ORDER BY duedate ASC"
    )


def transform_issues(issues: List[Dict], sprint_ids: List[int]) -> List[Dict]:
    id_set = set(sprint_ids)
    today = date.today()
    rows = []
    for issue in issues:
        fields = issue.get("fields", {})
        due_str = fields.get("duedate")
        if not due_str:
            continue
        sprint_match = [s for s in (fields.get(SPRINT_FIELD) or []) if s.get("id") in id_set]
        due = datetime.strptime(due_str, "%Y-%m-%d").date()
        assignee = fields.get("assignee") or {}
        status = fields.get("status") or {}
        rows.append({
            "Key": issue["key"],
            "Summary": fields.get("summary", ""),
            "Assignee": assignee.get("displayName") or "Unassigned",
            "DueDate": due_str,
            "Status": status.get("name", ""),
            "Sprint": sprint_match[0]["name"] if sprint_match else "Unknown sprint",
            "DaysOverdue": (today - due).days,
        })
    return rows


def generate_html(sprints_meta: List[Dict], rows: List[Dict], team_roster: Optional[List[str]] = None) -> str:
    sprints_js = "  var SPRINTS = [\n"
    sprints_js += ",\n".join(
        '    { name: %s, state: %s, range: %s }' % (
            json.dumps(s["name"]), json.dumps(s["state"]), json.dumps(s["range"])
        )
        for s in sprints_meta
    )
    sprints_js += "\n  ];\n"
    sprints_js += "  var TEAM_ROSTER = " + json.dumps(team_roster or []) + ";\n"

    rows_json = json.dumps(rows, indent=4)
    assert rows_json.startswith("[") and rows_json.endswith("]")
    rows_inner = rows_json[1:-1].strip("\n")
    # Defend against a task Summary containing "</script>" and breaking out of the <script> block.
    rows_inner = rows_inner.replace("</script", "<\\/script")

    return TEMPLATE_HEAD + sprints_js + TEMPLATE_MIDDLE + rows_inner + "\n" + TEMPLATE_TAIL


def main():
    print("ADIRI Defaulted Tasks Dashboard Generator\n" + "=" * 60)

    if not JIRA_USERNAME or not JIRA_API_TOKEN:
        print("Error: set JIRA_USERNAME and JIRA_API_TOKEN environment variables.")
        print("Get an API token at https://id.atlassian.com/manage-profile/security/api-tokens")
        sys.exit(1)

    client = JiraClient(JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN)

    print("Detecting active/recent sprints for project AD...")
    sprints = client.detect_sprints()
    if not sprints:
        print("Error: no active or recent sprint found for project AD.")
        sys.exit(1)
    for s in sprints:
        print(f"  - {s['name']} ({s['state']})")

    print("\nFetching project AD team roster...")
    team_roster = client.list_team_roster(PROJECT_KEY)
    print(f"  {len(team_roster)} people: {', '.join(team_roster)}")

    sprint_ids = [s["id"] for s in sprints]
    jql = build_defaulted_jql(sprint_ids)
    print(f"\nFetching defaulted tasks (JQL: {jql})")

    issues = client.search_all(
        jql=jql,
        fields=["summary", "assignee", "duedate", "status", SPRINT_FIELD],
    )
    rows = transform_issues(issues, sprint_ids)
    print(f"  Fetched {len(rows)} defaulted tasks\n")

    sprints_meta = [
        {"name": s["name"], "state": cap(s["state"]), "range": fmt_range(s["startDate"], s["endDate"])}
        for s in sprints
    ]

    html = generate_html(sprints_meta, rows, team_roster)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard saved to: {OUTPUT_PATH}\n")
    by_sprint: Dict[str, int] = {}
    by_assignee: Dict[str, int] = {}
    for r in rows:
        by_sprint[r["Sprint"]] = by_sprint.get(r["Sprint"], 0) + 1
        by_assignee[r["Assignee"]] = by_assignee.get(r["Assignee"], 0) + 1

    print("By sprint:")
    for name, count in by_sprint.items():
        print(f"  - {name}: {count}")
    print("\nBy assignee:")
    for name, count in sorted(by_assignee.items(), key=lambda x: -x[1]):
        print(f"  - {name}: {count}")


if __name__ == "__main__":
    main()
