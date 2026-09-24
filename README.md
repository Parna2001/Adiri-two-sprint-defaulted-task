# ADIRI Defaulted Tasks Dashboard

A Python script that generates a self-contained HTML dashboard of unfinished tasks across the last two sprints of the ADIRI Jira project (`AD`), in two lists:

- **Defaulted** - the current due date has passed and the task is not done.
- **Rescheduled** - the due date is today or later, but it was pushed to a later date at least once (read from the Jira change history) and the task is not done. There is no upper limit on how many times.

A task appears in one list only. Tasks with a comment such as "not required now", "on hold" or "postponed" (see `DEFERRAL_PHRASES` in the script) are left out and printed to the console so you can check the rule.

The dashboard shows summary cards, a stacked per-assignee bar chart (Defaulted + Rescheduled), and sortable, filterable task tables with links back to Jira and an expandable due-date history per task.

## Files

- `generate_defaulted_tasks_dashboard.py` – fetches the data from Jira and writes the dashboard.
- `index.html` – the generated dashboard (can be served with GitHub Pages).

## Requirements

- Python 3.8+
- `requests` (`pip install requests`)
- A Jira Cloud account with access to the `AD` project and an [API token](https://id.atlassian.com/manage-profile/security/api-tokens)

## Usage

Set your Jira credentials as environment variables (never commit them), then run the script.

PowerShell:

```powershell
$env:JIRA_USERNAME = "you@example.com"
$env:JIRA_API_TOKEN = "your-api-token"
python generate_defaulted_tasks_dashboard.py
```

macOS / Linux:

```bash
export JIRA_USERNAME="you@example.com"
export JIRA_API_TOKEN="your-api-token"
python generate_defaulted_tasks_dashboard.py
```

The script writes the result to `index.html`; open it in a browser. It also prints the counts per category, the tasks excluded by deferral comments, and the five most-rescheduled tasks.
