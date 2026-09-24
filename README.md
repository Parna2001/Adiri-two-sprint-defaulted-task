# ADIRI Defaulted Tasks Dashboard

A Python script that generates a self-contained HTML dashboard of defaulted tasks (overdue and not yet Done) across the last two sprints of the ADIRI Jira project (`AD`).

The dashboard shows totals per sprint, a per-assignee bar chart, and sortable, filterable task tables with links back to Jira.

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

The script writes the result to `index.html`; open it in a browser.
