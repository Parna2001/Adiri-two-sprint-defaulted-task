#!/usr/bin/env python3
"""
ADIRI Defaulted Tasks Dashboard Generator
Fetches unfinished tasks from the last two sprints in Jira project AD and regenerates index.html.

Two categories are reported (a task is in exactly one of them):
  - Defaulted:   current due date is before today.
  - Rescheduled: current due date is today or later, but the due date was pushed later at
                 least once (found through the Jira changelog), however many times.
Tasks with a "not required now" style comment (see DEFERRAL_PHRASES) are left out of both, except
overdue tasks in the active sprint, which always stay Defaulted.
"""

import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

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
    '"consumer-loan"',
]
OUTPUT_PATH = "index.html"

# A comment containing any of these phrases (case-insensitive, whitespace-tolerant, whole words)
# removes the task from the dashboard. Excluded tasks are printed to the console.
# Exception: an overdue (Defaulted) task that is in the active sprint is always kept.
DEFERRAL_PHRASES = [
    "not required now", "not required for now", "not needed now",
    "not needed for now", "will do later", "will be done later",
    "take it up later", "on hold", "put on hold", "deprioritized",
    "deprioritised", "postponed", "deferred", "parked for now",
    "not a priority now", "later sprint", "next quarter",
]

CATEGORY_DEFAULTED = "Defaulted"
CATEGORY_RESCHEDULED = "Rescheduled"
HEAVY_RESCHEDULE_COUNT = 5  # "Rescheduled 5+ times" (the dashboard also shows an amber badge from 3)

REQUEST_MAX_RETRIES = 6
REQUEST_TIMEOUT = 30
PAGE_SIZE = 100
CHANGELOG_EMBED_LIMIT = 100  # Jira embeds at most this many changelog entries per issue in search results

BOM = "﻿"

# The dashboard page. __DASHBOARD_DATA__ is replaced by a JSON object (see generate_html).
TEMPLATE = r"""<meta charset="utf-8">
<title>Defaulted Tasks</title>
<style>
  :root {
    color-scheme: light;
    --bg: #f9f9f7;
    --surface: #fcfcfb;
    --surface-raised: #ffffff;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #898781;
    --border: rgba(11,11,11,0.10);
    --grid: #e1e0d9;
    --accent: #2a78d6;
    --accent-soft: #cde2fb;
    --accent-ink: #184f95;
    --status-good: #0ca30c;
    --status-warning: #fab219;
    --status-serious: #ec835a;
    --status-critical: #d03b3b;
    --row-hover: #f0efec;
    --chip-bg: #f0efec;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --bg: #0d0d0d;
      --surface: #1a1a19;
      --surface-raised: #202020;
      --text-primary: #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted: #898781;
      --border: rgba(255,255,255,0.10);
      --grid: #2c2c2a;
      --accent: #3987e5;
      --accent-soft: #184f95;
      --accent-ink: #cde2fb;
      --status-good: #0ca30c;
      --status-warning: #fab219;
      --status-serious: #ec835a;
      --status-critical: #d03b3b;
      --row-hover: #242422;
      --chip-bg: #242422;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg: #0d0d0d;
    --surface: #1a1a19;
    --surface-raised: #202020;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #898781;
    --border: rgba(255,255,255,0.10);
    --grid: #2c2c2a;
    --accent: #3987e5;
    --accent-soft: #184f95;
    --accent-ink: #cde2fb;
    --status-good: #0ca30c;
    --status-warning: #fab219;
    --status-serious: #ec835a;
    --status-critical: #d03b3b;
    --row-hover: #242422;
    --chip-bg: #242422;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    padding-inline: 20px;
    padding-block: 20px 40px;
  }
  .wrap { max-width: 1180px; margin: 0 auto; }

  header.page { margin-bottom: 20px; }
  .eyebrow {
    font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
    color: var(--accent-ink); margin: 0 0 6px;
  }
  h1 { font-size: 26px; font-weight: 800; margin: 0 0 4px; letter-spacing: -0.01em; }
  .subtitle { font-size: 14px; color: var(--text-secondary); margin: 0; }

  .sync-bar {
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    font-size: 12.5px; color: var(--text-secondary);
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 12px; margin-bottom: 16px;
  }
  .sync-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--status-good); flex: none; }

  .stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 10px;
    margin: 20px 0 22px;
  }
  .stat-tile {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
  }
  .stat-tile .label { font-size: 11.5px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
  .stat-tile .value { font-size: 28px; font-weight: 800; font-variant-numeric: tabular-nums; margin-top: 4px; }
  .stat-tile.grand { border-color: var(--accent); background: linear-gradient(180deg, var(--accent-soft) 0%, var(--surface) 130%); }
  .stat-tile.grand .value { color: var(--accent-ink); }
  .stat-tile.resched { border-color: var(--status-warning); }
  .stat-tile.heavy { border-color: var(--status-critical); }
  .stat-tile.heavy .value { color: var(--status-critical); }
  .stat-tile .sub { font-size: 12px; color: var(--text-muted); margin-top: 2px; }

  .chart-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px 14px;
    margin-bottom: 22px;
  }
  .chart-title { font-size: 13px; font-weight: 700; color: var(--text-secondary); margin: 0 0 4px; text-transform: uppercase; letter-spacing: 0.04em; }
  .chart-hint { font-size: 12px; color: var(--text-muted); margin: 0 0 12px; }
  .legend { display: flex; gap: 18px; flex-wrap: wrap; margin: 0 0 16px; font-size: 12.5px; color: var(--text-secondary); }
  .legend-swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }
  .bar-plot { position: relative; padding-left: 2px; }
  .bar-row, .bar-ticks-row { display: flex; align-items: center; gap: 14px; }
  .bar-row { margin-bottom: 16px; border-radius: 6px; transition: opacity 0.2s ease; }
  .bar-row-label, .bar-row-spacer { flex: 0 0 190px; min-width: 0; }
  .bar-sprint-name { display: block; font-size: 13px; font-weight: 700; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .bar-row-label .state-badge { margin-top: 3px; }
  .bar-track { flex: 1 1 auto; position: relative; height: 26px; background: var(--chip-bg); border-radius: 4px; min-width: 0; overflow: hidden; }
  .bar-fill { position: absolute; top: 0; height: 100%; transition: width 0.4s ease; }
  .bar-fill + .bar-fill { border-left: 2px solid var(--surface); }
  .bar-value, .bar-value-spacer { flex: 0 0 44px; font-size: 13.5px; font-weight: 800; color: var(--text-primary); font-variant-numeric: tabular-nums; white-space: nowrap; }

  .bar-row-clickable { cursor: pointer; }
  .bar-row-clickable:hover .bar-sprint-name { color: var(--accent); }
  .bar-row-clickable:hover .bar-track { outline: 1px solid var(--accent); outline-offset: 1px; }
  .bar-row-clickable:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .bar-plot.has-selection .bar-row:not(.selected) { opacity: 0.4; }
  .bar-row.selected .bar-sprint-name { color: var(--accent-ink); }
  .bar-row.selected .bar-track { outline: 2px solid var(--accent); outline-offset: 1px; }
  .bar-ticks-row { margin-top: 2px; }
  .bar-ticks-track { flex: 1 1 auto; display: flex; justify-content: space-between; min-width: 0; }
  .bar-ticks-track span { font-size: 10.5px; color: var(--text-muted); font-variant-numeric: tabular-nums; }
  .bar-gridlines { position: absolute; inset: 0; display: flex; justify-content: space-between; pointer-events: none; }
  .bar-gridlines span { width: 1px; height: 100%; background: var(--grid); }

  .controls {
    display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
    margin-bottom: 18px;
  }
  .search {
    flex: 1 1 220px;
    min-width: 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 9px 12px;
    font-size: 14px;
    color: var(--text-primary);
  }
  .search:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  .search::placeholder { color: var(--text-muted); }

  .select {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 9px 30px 9px 12px;
    font-size: 14px;
    color: var(--text-primary);
    font-family: inherit;
    cursor: pointer;
  }
  .select:focus { outline: 2px solid var(--accent); outline-offset: -1px; }

  .chip-group { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip {
    font-size: 12.5px; font-weight: 600; padding: 7px 12px; border-radius: 999px;
    background: var(--chip-bg); border: 1px solid var(--border); color: var(--text-secondary);
    cursor: pointer; user-select: none; white-space: nowrap;
  }
  .chip:hover { border-color: var(--accent); }
  .chip[aria-pressed="true"] {
    background: var(--accent); color: #fff; border-color: var(--accent);
  }
  .chip .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
  .chip-sep { width: 1px; align-self: stretch; background: var(--border); margin: 0 4px; }

  section.cat { margin-bottom: 26px; }
  .sprint-head {
    display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
    flex-wrap: wrap;
    padding: 4px 2px 10px;
    border-bottom: 2px solid var(--grid);
    margin-bottom: 0;
  }
  .cat-defaulted .sprint-head { border-bottom-color: var(--accent); }
  .cat-rescheduled .sprint-head { border-bottom-color: var(--status-warning); }
  .sprint-title-group { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .sprint-name { font-size: 17px; font-weight: 800; }
  .cat-swatch { width: 12px; height: 12px; border-radius: 3px; flex: none; }
  .state-badge {
    font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
    padding: 3px 8px; border-radius: 5px;
  }
  .state-badge.rank { background: var(--chip-bg); color: var(--text-muted); border: 1px solid var(--border); font-variant-numeric: tabular-nums; }
  .sprint-range { font-size: 12.5px; color: var(--text-muted); }
  .sprint-count { font-size: 14px; color: var(--text-secondary); font-weight: 600; font-variant-numeric: tabular-nums; }
  .sprint-count b { color: var(--text-primary); font-size: 16px; }

  .table-scroll { overflow-x: auto; border: 1px solid var(--border); border-top: none; border-radius: 0 0 10px 10px; background: var(--surface); }
  table { width: 100%; border-collapse: collapse; font-size: 13.5px; min-width: 780px; }
  thead th {
    position: sticky; top: 0; background: var(--surface-raised);
    text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--text-muted); font-weight: 700; padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    cursor: pointer; white-space: nowrap;
  }
  thead th.num { text-align: right; }
  thead th.tog { cursor: default; width: 34px; padding-inline: 6px; }
  thead th .arrow { opacity: 0.35; font-size: 10px; margin-left: 3px; }
  thead th.sorted .arrow { opacity: 1; color: var(--accent); }
  tbody td { padding: 9px 12px; border-bottom: 1px solid var(--grid); vertical-align: top; }
  tbody td.tog { padding-inline: 6px; width: 34px; }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover { background: var(--row-hover); }
  tbody tr.hist-row:hover { background: transparent; }

  td.key a { color: var(--accent); text-decoration: none; font-weight: 700; font-variant-numeric: tabular-nums; }
  td.key a:hover { text-decoration: underline; }
  td.summary { color: var(--text-primary); max-width: 340px; }
  td.summary .sub-text { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
  td.assignee { color: var(--text-secondary); white-space: nowrap; }
  td.due { color: var(--text-secondary); white-space: nowrap; font-variant-numeric: tabular-nums; }
  td.status .status-pill {
    display: inline-block; font-size: 11.5px; font-weight: 600; padding: 2px 8px;
    border-radius: 5px; background: var(--chip-bg); color: var(--text-secondary); border: 1px solid var(--border);
    white-space: nowrap;
  }
  td.overdue, td.count { text-align: right; white-space: nowrap; }
  .overdue-wrap { display: inline-flex; align-items: center; gap: 6px; justify-content: flex-end; }
  .overdue-num { font-weight: 800; font-variant-numeric: tabular-nums; font-size: 14px; }
  .sev-dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
  .sev-label { font-size: 10.5px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; font-weight: 700; }
  .muted { color: var(--text-muted); }

  .badge { display: inline-block; font-size: 10.5px; font-weight: 700; padding: 2px 7px; border-radius: 5px; white-space: nowrap; }
  td.count .badge { margin-right: 8px; }
  .badge-amber { background: var(--status-warning); color: #0b0b0b; }
  .badge-red { background: var(--status-critical); color: #ffffff; }

  .hist-toggle {
    width: 24px; height: 24px; padding: 0; border-radius: 6px; cursor: pointer;
    border: 1px solid var(--border); background: var(--surface-raised); color: var(--text-secondary); font-size: 12px; line-height: 1;
  }
  .hist-toggle:hover { border-color: var(--accent); color: var(--accent); }
  .hist-box { background: var(--surface-raised); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
  .hist-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 6px; }
  .hist-table { min-width: 0; width: auto; font-size: 12.5px; }
  .hist-table td { padding: 4px 16px 4px 0; border-bottom: none; color: var(--text-secondary); white-space: nowrap; font-variant-numeric: tabular-nums; }
  .hist-table td.move { color: var(--text-primary); font-weight: 600; }

  .empty-row td { text-align: center; color: var(--text-muted); padding: 24px; font-size: 13.5px; }

  footer.note { margin-top: 18px; font-size: 12px; color: var(--text-muted); line-height: 1.6; }
  footer.note code { background: var(--chip-bg); padding: 1px 5px; border-radius: 4px; }

  @media (max-width: 560px) {
    h1 { font-size: 21px; }
    .stat-tile .value { font-size: 22px; }
    td.summary { max-width: 200px; }
    .bar-row-label, .bar-row-spacer { flex-basis: 120px; }
  }
</style>

<div class="wrap">
  <header class="page">
    <p class="eyebrow">ADIRI &middot; Jira Project AD</p>
    <h1>Defaulted Tasks</h1>
    <p class="subtitle">Overdue tasks, and tasks whose due date keeps being pushed, across the last two sprints</p>
  </header>

  <div class="sync-bar" id="sync-bar">
    <span class="sync-dot"></span>
    <span class="sync-text" id="sync-text"></span>
  </div>

  <div class="stats" id="stats"></div>

  <div class="chart-card">
    <p class="chart-title">Defaulted tasks by assignee &mdash; highest to lowest</p>
    <p class="chart-hint">Click a name to filter both task lists below to that assignee. Click again to clear.</p>
    <div class="legend">
      <span><span class="legend-swatch" style="background:var(--accent)"></span>Defaulted (overdue)</span>
      <span><span class="legend-swatch" style="background:var(--status-warning)"></span>Rescheduled (due date pushed)</span>
    </div>
    <div id="bar-chart-assignee"></div>
  </div>

  <div class="controls">
    <input class="search" id="search" type="text" placeholder="Filter by key, summary, or assignee&hellip;" />
    <select class="select" id="assignee-filter">
      <option value="all">All assignees</option>
    </select>
    <div class="chip-group" id="severity-filters" title="Defaulted: days overdue. Rescheduled: days slipped.">
      <button class="chip" data-severity="all" aria-pressed="true">All severities</button>
      <button class="chip" data-severity="Recent"><span class="dot" style="background:var(--status-warning)"></span>Recent (&le;7d)</button>
      <button class="chip" data-severity="Aging"><span class="dot" style="background:var(--status-serious)"></span>Aging (8&ndash;30d)</button>
      <button class="chip" data-severity="Severe"><span class="dot" style="background:var(--status-critical)"></span>Severe (&gt;30d)</button>
    </div>
    <span class="chip-sep"></span>
    <button class="chip" id="resched5-chip" aria-pressed="false">Rescheduled 5+</button>
  </div>

  <div id="sections"></div>

  <footer class="note">
    <b>Defaulted</b> = due date has passed and the task is not done. <b>Rescheduled</b> = due date is today or later, but it was pushed to a later date at least once (from the Jira change history) and the task is not done. A task is in one list only. Severity is days overdue for Defaulted tasks and days slipped (current due date minus original due date) for Rescheduled tasks. Excludes tasks labeled <code>reminder</code>, <code>adiri-monthly</code>, <code>adiri-weekly</code>, <code>salon weekly</code>, <code>salon monthly</code>, <code>bimonthly</code>, <code>daily task</code>, <code>payment duedate</code>, <code>housekeeping</code>, or <code>consumer-loan</code>, and tasks with a comment saying the work is deferred or not required now (overdue tasks in the active sprint are still shown). Click a column header to sort, the arrow at the start of a row to see its due-date history, and a task key to open it in Jira.
  </footer>
</div>

<script>
(function () {
  var DATA = __DASHBOARD_DATA__;
  var SPRINTS = DATA.sprints;
  var TEAM_ROSTER = DATA.roster;
  var ALL_ROWS = DATA.rows;
  var JIRA_BASE = DATA.jiraBase.replace(/\/+$/, "");

  var COLOR_DEFAULTED = "var(--accent)";
  var COLOR_RESCHEDULED = "var(--status-warning)";

  var CATEGORIES = [
    {
      id: "Defaulted", cls: "cat-defaulted", title: "Defaulted (overdue)", color: COLOR_DEFAULTED,
      hint: "Due date has passed and the task is not done",
      cols: [
        { c: "Key", l: "Key" }, { c: "Summary", l: "Summary" }, { c: "Assignee", l: "Assignee" },
        { c: "DueDate", l: "Due date" }, { c: "Status", l: "Status" },
        { c: "RescheduleCount", l: "Rescheduled", num: true }, { c: "DaysOverdue", l: "Days overdue", num: true }
      ],
      defaultSort: { col: "DaysOverdue", dir: "desc" }
    },
    {
      id: "Rescheduled", cls: "cat-rescheduled", title: "Rescheduled (due date pushed)", color: COLOR_RESCHEDULED,
      hint: "Not overdue yet, but the due date has been pushed later at least once",
      cols: [
        { c: "Key", l: "Key" }, { c: "Summary", l: "Summary" }, { c: "Assignee", l: "Assignee" },
        { c: "OriginalDueDate", l: "Original due" }, { c: "DueDate", l: "Current due" },
        { c: "RescheduleCount", l: "Times rescheduled", num: true }, { c: "DaysSlipped", l: "Days slipped", num: true },
        { c: "Status", l: "Status" }
      ],
      defaultSort: { col: "RescheduleCount", dir: "desc" }
    }
  ];

  function rowDays(r) {
    return r.Category === "Defaulted" ? r.DaysOverdue : Math.max(r.DaysSlipped || 0, 0);
  }
  function severityOf(days) {
    if (days <= 7) return "Recent";
    if (days <= 30) return "Aging";
    return "Severe";
  }
  function severityColorVar(sev) {
    if (sev === "Recent") return "var(--status-warning)";
    if (sev === "Aging") return "var(--status-serious)";
    return "var(--status-critical)";
  }
  function fmtDate(iso) {
    if (!iso) return "&mdash;";
    var d = new Date(iso + "T00:00:00");
    if (isNaN(d)) return escapeHtml(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }
  function fmtDateTime(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return escapeHtml(iso);
    return d.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  var state = { search: "", severity: "all", assignee: "all", heavyOnly: false, sort: {}, open: {} };

  function applyFilters(rows) {
    var q = state.search.trim().toLowerCase();
    return rows.filter(function (r) {
      if (state.severity !== "all" && r._severity !== state.severity) return false;
      if (state.assignee !== "all" && r.Assignee !== state.assignee) return false;
      if (state.heavyOnly && r.RescheduleCount < 5) return false;
      if (!q) return true;
      return (
        r.Key.toLowerCase().indexOf(q) !== -1 ||
        r.Summary.toLowerCase().indexOf(q) !== -1 ||
        r.Assignee.toLowerCase().indexOf(q) !== -1
      );
    });
  }

  function sortRows(rows, cat) {
    var s = state.sort[cat.id] || cat.defaultSort;
    var col = s.col, dir = s.dir === "asc" ? 1 : -1;
    return rows.slice().sort(function (a, b) {
      var av = a[col], bv = b[col];
      if (av === null || av === undefined) av = typeof bv === "string" ? "" : -Infinity;
      if (bv === null || bv === undefined) bv = typeof av === "string" ? "" : -Infinity;
      if (typeof av === "string") av = av.toLowerCase();
      if (typeof bv === "string") bv = bv.toLowerCase();
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return a.Key < b.Key ? -1 : a.Key > b.Key ? 1 : 0;
    });
  }

  function countBy(rows, category) {
    return rows.filter(function (r) { return r.Category === category; }).length;
  }

  function renderStats(all) {
    var el = document.getElementById("stats");
    var heavy = all.filter(function (r) { return r.RescheduleCount >= 5; }).length;
    var html =
      '<div class="stat-tile grand"><div class="label">Total Defaulted</div><div class="value">' + countBy(all, "Defaulted") + '</div><div class="sub">overdue and not done</div></div>' +
      '<div class="stat-tile resched"><div class="label">Total Rescheduled</div><div class="value">' + countBy(all, "Rescheduled") + '</div><div class="sub">due date pushed, not yet overdue</div></div>' +
      '<div class="stat-tile heavy"><div class="label">Rescheduled 5+ times</div><div class="value">' + heavy + '</div><div class="sub">tasks, in either list</div></div>';
    SPRINTS.forEach(function (s) {
      var inSprint = all.filter(function (r) { return r.Sprint === s.name; });
      html += '<div class="stat-tile"><div class="label">' + escapeHtml(s.name) + '</div><div class="value">' + inSprint.length + '</div><div class="sub">' +
        countBy(inSprint, "Defaulted") + ' defaulted &middot; ' + countBy(inSprint, "Rescheduled") + ' rescheduled</div></div>';
    });
    el.innerHTML = html;
  }

  function niceStep(rawStep) {
    var mag = Math.pow(10, Math.floor(Math.log(rawStep) / Math.LN10));
    var norm = rawStep / mag;
    var niceNorm = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
    return niceNorm * mag;
  }
  function computeTicks(maxValue, targetCount) {
    if (maxValue <= 0) return { max: 1, ticks: [0, 1] };
    var step = niceStep(maxValue / targetCount);
    var niceMax = Math.ceil(maxValue / step) * step;
    var ticks = [];
    for (var v = 0; v <= niceMax + 1e-9; v += step) ticks.push(Math.round(v));
    return { max: niceMax, ticks: ticks };
  }

  // items: [{ label, badge: {text, cls} | null, total, segments: [{ name, value, color }] }]
  // opts: { clickable, selected, onClick(label) }
  function renderBarChart(elId, items, targetTickCount, opts) {
    opts = opts || {};
    var el = document.getElementById(elId);
    var maxVal = Math.max.apply(null, items.map(function (it) { return it.total; }).concat([0]));
    var scale = computeTicks(maxVal, targetTickCount || 5);
    var hasSelection = !!opts.selected;

    var rows = items.map(function (it) {
      var isSelected = opts.selected === it.label;
      var rowCls = "bar-row" + (opts.clickable ? " bar-row-clickable" : "") + (isSelected ? " selected" : "");
      var breakdown = it.segments.map(function (sg) { return sg.value + " " + sg.name.toLowerCase(); }).join(", ");
      var a11y = opts.clickable ? ' tabindex="0" role="button" aria-pressed="' + isSelected + '" aria-label="Filter task lists to ' + escapeHtml(it.label) + " (" + breakdown + ')"' : "";
      var left = 0;
      var fills = it.segments.map(function (sg) {
        var w = scale.max ? (sg.value / scale.max) * 100 : 0;
        var html = sg.value ? '<div class="bar-fill" style="left:' + left + "%; width:" + w + "%; background:" + sg.color + ';" title="' + escapeHtml(sg.name) + ": " + sg.value + '"></div>' : "";
        left += w;
        return html;
      }).join("");
      return '<div class="' + rowCls + '" data-label="' + escapeHtml(it.label) + '"' + a11y + ">" +
        '<div class="bar-row-label">' +
          '<span class="bar-sprint-name">' + escapeHtml(it.label) + "</span>" +
          (it.badge ? '<span class="state-badge ' + it.badge.cls + '">' + escapeHtml(it.badge.text) + "</span>" : "") +
        "</div>" +
        '<div class="bar-track">' +
          '<div class="bar-gridlines">' + scale.ticks.map(function () { return "<span></span>"; }).join("") + "</div>" +
          fills +
        "</div>" +
        '<span class="bar-value" title="' + escapeHtml(breakdown) + '">' + it.total + "</span>" +
      "</div>";
    }).join("");

    var tickRow = '<div class="bar-ticks-row">' +
      '<div class="bar-row-spacer"></div>' +
      '<div class="bar-ticks-track">' + scale.ticks.map(function (t) { return "<span>" + t + "</span>"; }).join("") + "</div>" +
      '<span class="bar-value-spacer"></span>' +
    "</div>";

    el.innerHTML = '<div class="bar-plot' + (hasSelection ? " has-selection" : "") + '">' + rows + tickRow + "</div>";

    if (opts.clickable && opts.onClick) {
      el.querySelectorAll(".bar-row-clickable").forEach(function (rowEl) {
        var label = rowEl.getAttribute("data-label");
        rowEl.addEventListener("click", function () { opts.onClick(label); });
        rowEl.addEventListener("keydown", function (e) {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); opts.onClick(label); }
        });
      });
    }
  }

  function assigneeCounts(all) {
    var counts = {};
    TEAM_ROSTER.forEach(function (name) { counts[name] = { d: 0, r: 0 }; });
    all.forEach(function (r) {
      var c = counts[r.Assignee] || (counts[r.Assignee] = { d: 0, r: 0 });
      if (r.Category === "Defaulted") c.d++; else c.r++;
    });
    var names = Object.keys(counts).sort(function (a, b) {
      var diff = (counts[b].d + counts[b].r) - (counts[a].d + counts[a].r);
      return diff || (a < b ? -1 : a > b ? 1 : 0);
    });
    return { counts: counts, names: names };
  }

  function renderAssigneeChart(all) {
    var ac = assigneeCounts(all);
    var items = ac.names.map(function (name, i) {
      var c = ac.counts[name];
      return {
        label: name,
        badge: { text: "#" + (i + 1), cls: "rank" },
        total: c.d + c.r,
        segments: [
          { name: "Defaulted", value: c.d, color: COLOR_DEFAULTED },
          { name: "Rescheduled", value: c.r, color: COLOR_RESCHEDULED }
        ]
      };
    });
    renderBarChart("bar-chart-assignee", items, 5, {
      clickable: true,
      selected: state.assignee !== "all" ? state.assignee : null,
      onClick: function (label) {
        state.assignee = state.assignee === label ? "all" : label;
        document.getElementById("assignee-filter").value = state.assignee;
        renderAssigneeChart(ALL_ROWS);
        render();
        var target = document.getElementById("sections");
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }

  function populateAssigneeFilter(all) {
    var sel = document.getElementById("assignee-filter");
    var ac = assigneeCounts(all);
    sel.innerHTML = '<option value="all">All assignees</option>';
    ac.names.forEach(function (name) {
      var opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name + " (" + (ac.counts[name].d + ac.counts[name].r) + ")";
      sel.appendChild(opt);
    });
    sel.value = state.assignee;
  }

  function rescheduleBadge(n) {
    if (n >= 5) return '<span class="badge badge-red">Rescheduled 5+ times</span>';
    if (n >= 3) return '<span class="badge badge-amber">3+ times</span>';
    return "";
  }

  function renderCell(r, col) {
    switch (col) {
      case "Key":
        return '<td class="key"><a href="' + JIRA_BASE + "/browse/" + encodeURIComponent(r.Key) + '" target="_blank" rel="noopener">' + escapeHtml(r.Key) + "</a></td>";
      case "Summary":
        return '<td class="summary">' + escapeHtml(r.Summary) + '<div class="sub-text">' + escapeHtml(r.Sprint) + "</div></td>";
      case "Assignee":
        return '<td class="assignee">' + escapeHtml(r.Assignee) + "</td>";
      case "DueDate":
      case "OriginalDueDate":
        return '<td class="due">' + fmtDate(r[col]) + "</td>";
      case "Status":
        return '<td class="status"><span class="status-pill">' + escapeHtml(r.Status) + "</span></td>";
      case "RescheduleCount":
        return '<td class="count">' + rescheduleBadge(r.RescheduleCount) + (r.RescheduleCount ? '<b>' + r.RescheduleCount + "</b>" : '<span class="muted">0</span>') + "</td>";
      case "DaysOverdue":
      case "DaysSlipped":
        var days = col === "DaysOverdue" ? r.DaysOverdue : r.DaysSlipped;
        if (days === null || days === undefined) return '<td class="overdue"><span class="muted">&mdash;</span></td>';
        var sev = r._severity;
        var shown = col === "DaysSlipped" && days > 0 ? "+" + days : String(days);
        return '<td class="overdue"><span class="overdue-wrap"><span class="sev-dot" style="background:' + severityColorVar(sev) + '"></span><span class="overdue-num">' + shown + 'd</span><span class="sev-label">' + sev + "</span></span></td>";
    }
    return "<td></td>";
  }

  function renderHistory(r) {
    var lines = r.History.map(function (h) {
      var move = fmtDate(h.from) + " &rarr; " + fmtDate(h.to);
      var dir = h.later ? '<span class="badge badge-amber">pushed later</span>' : "";
      return "<tr><td>" + fmtDateTime(h.at) + '</td><td class="move">' + move + "</td><td>by " + escapeHtml(h.by) + "</td><td>" + dir + "</td></tr>";
    }).join("");
    return '<div class="hist-box"><div class="hist-title">Due-date history (oldest first)</div><table class="hist-table"><tbody>' + lines + "</tbody></table></div>";
  }

  function renderRow(r, cat) {
    var hasHist = r.History && r.History.length > 0;
    var open = !!state.open[r.Key] && hasHist;
    var toggle = hasHist
      ? '<button type="button" class="hist-toggle" data-key="' + escapeHtml(r.Key) + '" aria-expanded="' + open + '" aria-label="' + (open ? "Hide" : "Show") + " due-date history for " + escapeHtml(r.Key) + '">' + (open ? "&#9662;" : "&#9656;") + "</button>"
      : "";
    var html = '<tr><td class="tog">' + toggle + "</td>" + cat.cols.map(function (c) { return renderCell(r, c.c); }).join("") + "</tr>";
    if (open) html += '<tr class="hist-row"><td></td><td colspan="' + cat.cols.length + '">' + renderHistory(r) + "</td></tr>";
    return html;
  }

  function renderTable(cat, visible) {
    var sortState = state.sort[cat.id] || cat.defaultSort;
    var thead = '<thead><tr><th class="tog"></th>' + cat.cols.map(function (c) {
      var sorted = sortState.col === c.c;
      var arrow = sorted ? (sortState.dir === "desc" ? "&#9660;" : "&#9650;") : "&#9660;";
      return '<th class="' + (sorted ? "sorted" : "") + (c.num ? " num" : "") + '" data-col="' + c.c + '" data-cat="' + cat.id + '">' + c.l + '<span class="arrow">' + arrow + "</span></th>";
    }).join("") + "</tr></thead>";
    var body = visible.length
      ? visible.map(function (r) { return renderRow(r, cat); }).join("")
      : '<tr class="empty-row"><td colspan="' + (cat.cols.length + 1) + '">No tasks match the current filters.</td></tr>';
    return '<div class="table-scroll"><table>' + thead + "<tbody>" + body + "</tbody></table></div>";
  }

  function render() {
    var html = "";
    CATEGORIES.forEach(function (cat) {
      var rows = ALL_ROWS.filter(function (r) { return r.Category === cat.id; });
      var visible = sortRows(applyFilters(rows), cat);
      html += '<section class="cat ' + cat.cls + '">' +
        '<div class="sprint-head">' +
          '<div class="sprint-title-group">' +
            '<span class="cat-swatch" style="background:' + cat.color + '"></span>' +
            '<span class="sprint-name">' + cat.title + "</span>" +
            '<span class="sprint-range">' + cat.hint + "</span>" +
          "</div>" +
          '<span class="sprint-count"><b>' + visible.length + "</b> / " + rows.length + " shown</span>" +
        "</div>" +
        renderTable(cat, visible) +
        "</section>";
    });
    document.getElementById("sections").innerHTML = html;
  }

  function refreshAll() {
    renderStats(ALL_ROWS);
    renderAssigneeChart(ALL_ROWS);
    populateAssigneeFilter(ALL_ROWS);
    render();
  }

  function wireControls() {
    document.getElementById("search").addEventListener("input", function (e) {
      state.search = e.target.value;
      render();
    });

    document.getElementById("assignee-filter").addEventListener("change", function (e) {
      state.assignee = e.target.value;
      renderAssigneeChart(ALL_ROWS);
      render();
    });

    document.querySelectorAll("#severity-filters .chip").forEach(function (chip) {
      chip.addEventListener("click", function () {
        document.querySelectorAll("#severity-filters .chip").forEach(function (c) { c.setAttribute("aria-pressed", "false"); });
        chip.setAttribute("aria-pressed", "true");
        state.severity = chip.getAttribute("data-severity");
        render();
      });
    });

    var heavyChip = document.getElementById("resched5-chip");
    heavyChip.addEventListener("click", function () {
      state.heavyOnly = !state.heavyOnly;
      heavyChip.setAttribute("aria-pressed", String(state.heavyOnly));
      render();
    });

    document.getElementById("sections").addEventListener("click", function (e) {
      var toggle = e.target.closest(".hist-toggle");
      if (toggle) {
        var key = toggle.getAttribute("data-key");
        state.open[key] = !state.open[key];
        render();
        return;
      }
      var th = e.target.closest("th[data-col]");
      if (!th) return;
      var catId = th.getAttribute("data-cat"), col = th.getAttribute("data-col");
      var def = CATEGORIES.filter(function (c) { return c.id === catId; })[0].defaultSort;
      var cur = state.sort[catId] || def;
      state.sort[catId] = { col: col, dir: cur.col === col && cur.dir === "desc" ? "asc" : "desc" };
      render();
    });
  }

  function showSnapshotInfo() {
    var when = new Date(DATA.generatedAt);
    var stamp = isNaN(when) ? DATA.generatedAt : when.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
    document.getElementById("sync-text").textContent = "Snapshot generated " + stamp + " — re-run generate_defaulted_tasks_dashboard.py to refresh.";
  }

  ALL_ROWS.forEach(function (r) { r._severity = severityOf(rowDays(r)); });
  wireControls();
  showSnapshotInfo();
  refreshAll();
})();
</script>
"""


class JiraClient:
    def __init__(self, url: str, username: str, api_token: str):
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, api_token)
        self.session.headers.update({"Accept": "application/json"})

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Send a request, retrying HTTP 429 with backoff (Retry-After is respected)."""
        for attempt in range(REQUEST_MAX_RETRIES + 1):
            response = self.session.request(method, f"{self.url}{path}", timeout=REQUEST_TIMEOUT, **kwargs)
            if response.status_code != 429 or attempt == REQUEST_MAX_RETRIES:
                break
            delay = retry_delay(response.headers.get("Retry-After"), attempt)
            print(f"  Rate limited by Jira (HTTP 429); retrying in {delay:.0f}s "
                  f"(attempt {attempt + 1}/{REQUEST_MAX_RETRIES})")
            time.sleep(delay)
        response.raise_for_status()
        return response

    def search_all(self, jql: str, fields: List[str], max_results: int = PAGE_SIZE, guard_limit: int = 30,
                   expand: Optional[str] = None) -> List[Dict]:
        """Paginate through /rest/api/3/search/jql (the current Jira Cloud search API;
        the old GET /rest/api/3/search endpoint now returns 410 Gone) until all issues are collected."""
        all_issues: List[Dict] = []
        next_token: Optional[str] = None
        guard = 0
        while True:
            body: Dict[str, Any] = {
                "jql": jql,
                "maxResults": max_results,
                "fields": fields,
            }
            if expand:
                body["expand"] = expand
            if next_token:
                body["nextPageToken"] = next_token
            data = self._request("POST", "/rest/api/3/search/jql", json=body).json()
            issues = data.get("issues", [])
            all_issues.extend(issues)
            guard += 1
            next_token = data.get("nextPageToken")
            if not issues or not next_token or data.get("isLast") or guard >= guard_limit:
                break
        return all_issues

    def get_changelog(self, issue_key: str) -> List[Dict]:
        """Full change history of one issue (paginated), oldest entry first."""
        histories: List[Dict] = []
        start = 0
        while True:
            data = self._request(
                "GET", f"/rest/api/3/issue/{issue_key}/changelog",
                params={"startAt": start, "maxResults": PAGE_SIZE},
            ).json()
            values = data.get("values", [])
            histories.extend(values)
            start += len(values)
            if not values or data.get("isLast") or ("total" in data and start >= data["total"]):
                break
        return histories

    def get_comments(self, issue_key: str) -> List[Dict]:
        """All comments of one issue (paginated); bodies are ADF JSON on Jira Cloud."""
        comments: List[Dict] = []
        start = 0
        while True:
            data = self._request(
                "GET", f"/rest/api/3/issue/{issue_key}/comment",
                params={"startAt": start, "maxResults": PAGE_SIZE},
            ).json()
            batch = data.get("comments", [])
            comments.extend(batch)
            start += len(batch)
            if not batch or start >= data.get("total", 0):
                break
        return comments

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
        users = self._request(
            "GET", "/rest/api/3/user/assignable/search",
            params={"project": project_key, "maxResults": 50},
        ).json()
        names = sorted({
            u["displayName"] for u in users
            if u.get("accountType") == "atlassian" and u.get("displayName")
        })
        return names


def retry_delay(retry_after: Optional[str], attempt: int) -> float:
    """Seconds to wait after a 429: the Retry-After header if it is a number, else exponential backoff."""
    try:
        if retry_after is not None:
            return max(float(retry_after), 0.0)
    except ValueError:
        pass
    return float(min(2 ** attempt, 60))


def cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def parse_jira_datetime(iso: str) -> datetime:
    normalized = iso.replace("Z", "+00:00")
    normalized = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", normalized)  # Jira writes +0000, not +00:00
    return datetime.fromisoformat(normalized)


def fmt_range(start_iso: str, end_iso: str) -> str:
    s = parse_jira_datetime(start_iso)
    e = parse_jira_datetime(end_iso)
    s_mon, e_mon = s.strftime("%b"), e.strftime("%b")
    if s_mon == e_mon:
        return f"{s_mon} {s.day} &ndash; {e.day}, {e.year}"
    return f"{s_mon} {s.day} &ndash; {e_mon} {e.day}, {e.year}"


def build_scope_jql(sprint_ids: List[int]) -> str:
    """Every unfinished, non-excluded AD task in the given sprints, whatever its due date."""
    ids = ",".join(str(i) for i in sprint_ids)
    labels = ", ".join(EXCLUDED_LABELS)
    # "labels not in (...)" alone never matches tasks without labels, so they are allowed explicitly.
    return (
        f"project = {PROJECT_KEY} AND sprint in ({ids}) "
        f"AND statusCategory != Done AND (labels is EMPTY OR labels not in ({labels})) ORDER BY duedate ASC"
    )


# ---- Due-date history ------------------------------------------------------------------

def norm_date(value: Optional[str]) -> Optional[str]:
    """'2026-05-01' (or a longer timestamp starting with it) -> '2026-05-01'; anything else -> None."""
    match = re.match(r"\d{4}-\d{2}-\d{2}", value or "")
    return match.group() if match else None


def to_iso_datetime(value: Optional[str]) -> Optional[str]:
    try:
        return parse_jira_datetime(value).isoformat() if value else None
    except ValueError:
        return None


def history_sort_key(history: Dict) -> Tuple[datetime, int]:
    try:
        when = parse_jira_datetime(history.get("created") or "")
    except ValueError:
        when = datetime.min.replace(tzinfo=timezone.utc)
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    ident = history.get("id")
    return when, int(ident) if str(ident).isdigit() else 0


def parse_due_changes(histories: List[Dict]) -> List[Dict]:
    """Due-date changes from the changelog, oldest first: [{from, to, by, at}]."""
    changes: List[Dict] = []
    for history in sorted(histories, key=history_sort_key):
        for item in history.get("items", []):
            if item.get("field") != "duedate" and item.get("fieldId") != "duedate":
                continue
            changes.append({
                "from": norm_date(item.get("fromString") or item.get("from")),
                "to": norm_date(item.get("toString") or item.get("to")),
                "by": (history.get("author") or {}).get("displayName") or "Unknown",
                "at": to_iso_datetime(history.get("created")),
            })
    return changes


def summarize_due_history(changes: List[Dict], current_due: Optional[str]) -> Dict[str, Any]:
    """original_due_date, reschedule_count (moves to a later date), total_days_slipped and the history."""
    original = current_due
    if changes:
        original = changes[0]["from"] or next((c["to"] for c in changes if c["to"]), current_due)

    count = 0
    previous = original if changes and changes[0]["from"] else None
    history: List[Dict] = []
    for change in changes:
        later = bool(previous and change["to"] and change["to"] > previous)
        count += later
        if change["to"]:
            previous = change["to"]
        history.append({**change, "later": later})

    slipped: Optional[int] = None
    if original and current_due:
        slipped = (date.fromisoformat(current_due) - date.fromisoformat(original)).days
    return {"original": original, "count": count, "slipped": slipped, "history": history}


def categorize(current_due: Optional[str], reschedule_count: int, today: date) -> Optional[str]:
    """Defaulted if overdue; Rescheduled if not overdue but pushed later at least once; else not shown."""
    if not current_due:
        return None
    if current_due < today.isoformat():
        return CATEGORY_DEFAULTED
    return CATEGORY_RESCHEDULED if reschedule_count >= 1 else None


def embedded_histories(issue: Dict) -> Optional[List[Dict]]:
    """Changelog entries embedded by expand=changelog, or None if absent/truncated (fetch it in full)."""
    changelog = issue.get("changelog")
    if not isinstance(changelog, dict):
        return None
    histories = changelog.get("histories") or []
    total = changelog.get("total")
    complete = total == len(histories) if total is not None else len(histories) < CHANGELOG_EMBED_LIMIT
    return histories if complete else None


def build_row(issue: Dict, sprint_ids: List[int], histories: List[Dict], today: date,
              active_sprint_ids: Optional[Set[int]] = None) -> Optional[Dict]:
    fields = issue.get("fields", {})
    current_due = norm_date(fields.get("duedate"))
    summary = summarize_due_history(parse_due_changes(histories), current_due)
    category = categorize(current_due, summary["count"], today)
    if category is None or current_due is None:
        return None

    id_set = set(sprint_ids)
    sprint_match = [s for s in (fields.get(SPRINT_FIELD) or []) if s.get("id") in id_set]
    in_active_sprint = any(s.get("id") in (active_sprint_ids or set()) for s in (fields.get(SPRINT_FIELD) or []))
    assignee = fields.get("assignee") or {}
    status = fields.get("status") or {}
    overdue = (today - date.fromisoformat(current_due)).days if category == CATEGORY_DEFAULTED else 0
    return {
        "Key": issue["key"],
        "Summary": fields.get("summary", ""),
        "Assignee": assignee.get("displayName") or "Unassigned",
        "Status": status.get("name", ""),
        "Sprint": sprint_match[0]["name"] if sprint_match else "Unknown sprint",
        "InActiveSprint": in_active_sprint,
        "Category": category,
        "DueDate": current_due,
        "OriginalDueDate": summary["original"],
        "RescheduleCount": summary["count"],
        "DaysSlipped": summary["slipped"],
        "DaysOverdue": overdue,
        "History": summary["history"],
    }


def collect_candidates(client: JiraClient, issues: List[Dict], sprint_ids: List[int], today: date,
                       active_sprint_ids: Optional[Set[int]] = None) -> List[Dict]:
    """Defaulted and Rescheduled candidates, before the deferral-comment exclusion."""
    rows: List[Dict] = []
    fetched_full = 0
    for issue in issues:
        histories = embedded_histories(issue)
        if histories is None:
            histories = client.get_changelog(issue["key"])
            fetched_full += 1
        row = build_row(issue, sprint_ids, histories, today, active_sprint_ids)
        if row:
            rows.append(row)
    print(f"  Changelogs read for {len(issues)} tasks ({fetched_full} fetched in full via the changelog endpoint)")
    return rows


# ---- Deferral comments -----------------------------------------------------------------

_ADF_BLOCKS = {
    "paragraph", "heading", "blockquote", "codeBlock", "listItem", "bulletList", "orderedList",
    "panel", "table", "tableRow", "tableCell", "tableHeader", "rule", "mediaSingle", "expand",
}


def _collect_adf_text(node: Any, parts: List[str]) -> None:
    if isinstance(node, str):
        parts.append(node)
    elif isinstance(node, list):
        for child in node:
            _collect_adf_text(child, parts)
    elif isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "text":
            parts.append(node.get("text", ""))
        elif node_type in ("mention", "emoji", "status", "inlineCard"):
            attrs = node.get("attrs") or {}
            parts.append(str(attrs.get("text") or attrs.get("shortName") or attrs.get("url") or ""))
        elif node_type == "hardBreak":
            parts.append("\n")
        _collect_adf_text(node.get("content", []), parts)
        if node_type in _ADF_BLOCKS:
            parts.append("\n")


def adf_to_text(body: Any) -> str:
    """Plain text of an Atlassian Document Format tree (or of a plain-string body), whitespace-collapsed."""
    parts: List[str] = []
    _collect_adf_text(body, parts)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def compile_deferral_patterns(phrases: List[str]) -> List[Tuple[str, "re.Pattern[str]"]]:
    """One regex per phrase: whole words only, any run of whitespace between words, case-insensitive."""
    patterns = []
    for phrase in phrases:
        body = r"\s+".join(re.escape(word) for word in phrase.split())
        patterns.append((phrase, re.compile(rf"\b{body}\b", re.IGNORECASE)))
    return patterns


def find_deferral(comments: List[Dict], patterns: List[Tuple[str, "re.Pattern[str]"]]) -> Optional[Dict]:
    """The first comment (oldest first) containing a deferral phrase, as {phrase, author, created}."""
    for comment in sorted(comments, key=lambda c: c.get("created") or ""):
        text = adf_to_text(comment.get("body"))
        for phrase, pattern in patterns:
            if pattern.search(text):
                return {
                    "phrase": phrase,
                    "author": (comment.get("author") or {}).get("displayName") or "Unknown",
                    "created": (comment.get("created") or "")[:10],
                }
    return None


def keeps_despite_deferral(row: Dict) -> bool:
    """An overdue task in the active sprint stays Defaulted even if a comment says it is deferred."""
    return row["Category"] == CATEGORY_DEFAULTED and row["InActiveSprint"]


def split_by_deferral(client: JiraClient, rows: List[Dict],
                      patterns: List[Tuple[str, "re.Pattern[str]"]]) -> Tuple[List[Dict], List[Dict]]:
    """(kept rows, excluded rows with a 'Deferral' entry). Only candidates' comments are fetched."""
    kept: List[Dict] = []
    excluded: List[Dict] = []
    for number, row in enumerate(rows, 1):
        match = None if keeps_despite_deferral(row) else find_deferral(client.get_comments(row["Key"]), patterns)
        if match:
            excluded.append({**row, "Deferral": match})
        else:
            kept.append(row)
        if number % 25 == 0:
            print(f"  Comments checked for {number}/{len(rows)} tasks")
    return kept, excluded


# ---- Output ----------------------------------------------------------------------------

def generate_html(sprints_meta: List[Dict], rows: List[Dict], team_roster: Optional[List[str]] = None,
                  generated_at: Optional[str] = None) -> str:
    data = {
        "generatedAt": generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "jiraBase": JIRA_URL,
        "sprints": sprints_meta,
        "roster": team_roster or [],
        "rows": rows,
    }
    # "<" is escaped so task text like "</script>" or "<!--" can't break out of the <script> block.
    data_js = json.dumps(data, indent=2).replace("<", "\\u003c")
    return BOM + TEMPLATE.replace("__DASHBOARD_DATA__", data_js)


def count_by(rows: List[Dict], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row[key]] = counts.get(row[key], 0) + 1
    return counts


def print_excluded(excluded: List[Dict]) -> None:
    print(f"\nExcluded by deferral comments ({len(excluded)}):")
    for row in excluded:
        d = row["Deferral"]
        print(f"  - {row['Key']} | {row['Summary'][:70]} | matched \"{d['phrase']}\" "
              f"| {d['author']} | {d['created']}")


def print_summary(rows: List[Dict], excluded: List[Dict]) -> None:
    by_category = count_by(rows, "Category")
    print("By category:")
    print(f"  - {CATEGORY_DEFAULTED}: {by_category.get(CATEGORY_DEFAULTED, 0)}")
    print(f"  - {CATEGORY_RESCHEDULED}: {by_category.get(CATEGORY_RESCHEDULED, 0)}")
    print(f"  - Rescheduled {HEAVY_RESCHEDULE_COUNT}+ times (either category): "
          f"{sum(1 for r in rows if r['RescheduleCount'] >= HEAVY_RESCHEDULE_COUNT)}")
    print(f"  - Excluded by deferral comments: {len(excluded)}")

    print("\nBy sprint:")
    for name, count in count_by(rows, "Sprint").items():
        print(f"  - {name}: {count}")
    print("\nBy assignee:")
    for name, count in sorted(count_by(rows, "Assignee").items(), key=lambda x: -x[1]):
        print(f"  - {name}: {count}")

    print("\nTop 5 most-rescheduled tasks:")
    for r in sorted(rows, key=lambda r: -r["RescheduleCount"])[:5]:
        print(f"  - {r['Key']} | {r['RescheduleCount']}x | {r['Category']} | {r['Assignee']} | "
              f"{r['OriginalDueDate']} -> {r['DueDate']} | {r['Summary'][:60]}")


def sort_rows(rows: List[Dict]) -> List[Dict]:
    return sorted(rows, key=lambda r: (r["Category"] != CATEGORY_DEFAULTED, -r["DaysOverdue"], -r["RescheduleCount"]))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # names/summaries may not fit the console codepage
    print("ADIRI Defaulted Tasks Dashboard Generator\n" + "=" * 60)

    if not JIRA_USERNAME or not JIRA_API_TOKEN:
        print("Error: set JIRA_USERNAME and JIRA_API_TOKEN environment variables.")
        print("Get an API token at https://id.atlassian.com/manage-profile/security/api-tokens")
        sys.exit(1)

    client = JiraClient(JIRA_URL, JIRA_USERNAME, JIRA_API_TOKEN)
    today = date.today()

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
    jql = build_scope_jql(sprint_ids)
    print(f"\nFetching unfinished tasks with change history (JQL: {jql})")
    issues = client.search_all(
        jql=jql,
        fields=["summary", "assignee", "duedate", "status", SPRINT_FIELD],
        expand="changelog",
    )
    print(f"  Fetched {len(issues)} unfinished tasks in scope")

    active_sprint_ids = {s["id"] for s in sprints if s.get("state") == "active"}
    candidates = collect_candidates(client, issues, sprint_ids, today, active_sprint_ids)
    print(f"  {len(candidates)} are Defaulted or Rescheduled; checking their comments for deferral phrases...")
    rows, excluded = split_by_deferral(client, candidates, compile_deferral_patterns(DEFERRAL_PHRASES))
    rows = sort_rows(rows)

    sprints_meta = [
        {"name": s["name"], "state": cap(s["state"]), "range": fmt_range(s["startDate"], s["endDate"])}
        for s in sprints
    ]

    html = generate_html(sprints_meta, rows, team_roster)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nDashboard saved to: {OUTPUT_PATH}\n")
    print_summary(rows, excluded)
    print_excluded(excluded)


if __name__ == "__main__":
    main()
