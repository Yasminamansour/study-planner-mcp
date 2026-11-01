# Study Planner: an MCP Toolkit (FastMCP + OpenAI Agents SDK)

A small MCP server that helps a student prepare for exams, connected to an AI agent built with the
OpenAI Agents SDK. The server exposes **exactly three tools** (one Data, one Action, one Orchestration)
and **one resource**.

## The toolkit

| Type | Name | What it does |
|---|---|---|
| **Data tool** | `get_course_info(course_code)` | Looks up a course's name, exam date, topics, and days left. Read-only. |
| **Action tool** | `add_study_session(course_code, session_date, topic)` | Saves **one** study session to the schedule. |
| **Orchestration tool** | `plan_exam_prep(course_code)` | Looks up the course, then schedules one session per topic from today until the day before the exam, ending with a full review. |
| **Resource** | `schedule://all` | The full study schedule (read-only). Read by the client, not called by the AI. |

### Failure cases (clear errors, never silent)

| Tool | Failure | Error message (example) |
|---|---|---|
| `get_course_info` | Unknown course | `Course 'EECE999' not found. Available courses: ...` |
| `add_study_session` | Bad date format | `Invalid date '12/05/2026'. Use the format YYYY-MM-DD ...` |
| | Date in the past | `Date ... is in the past. Choose today or a future date.` |
| | Date on/after the exam | `... Study sessions must be before the exam.` |
| | Empty topic | `Topic cannot be empty.` |
| | Duplicate session | `This session already exists: ...` |
| `plan_exam_prep` | Exam already passed | `... Cannot plan for an exam that is today or already passed.` |
| | One session fails (e.g. duplicate) | Recorded under `sessions_skipped` with the reason; the plan continues. |

## Architecture

```
agent.py (MCP Host: OpenAI Agents SDK)                server.py (MCP Server: FastMCP)
 ├── AI model: decides which tool to call   ──MCP──►   ├── get_course_info    (tool)
 └── MCP client (MCPServerStdio)            (stdio)    ├── add_study_session  (tool)
                                                       ├── plan_exam_prep     (tool)
                                                       └── schedule://all     (resource)
                                                                │
                                                       data/courses.json  (read only)
                                                       data/schedule.json (written by the action tool)
```

The client starts `server.py` as a local process (stdio transport), discovers its tools at runtime
(`list_tools`), and the agent calls them as needed. Tools run on the server; results come back through
the client to the agent.

## Project structure

```
.
├── server.py            # FastMCP server: 3 tools + 1 resource
├── agent.py             # OpenAI Agents SDK agent (MCP host/client), interactive chat
├── data/
│   ├── courses.json     # courses, exam dates, topics
│   └── schedule.json    # saved study sessions (starts as [])
├── tests/
│   └── test_tools.py    # pytest tests, including all failure cases
├── requirements.txt
└── README.md
```

## Setup

Requires Python 3.10+ and an OpenAI API key.

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your OpenAI API key
$env:OPENAI_API_KEY="sk-..."   # Windows PowerShell
# export OPENAI_API_KEY="sk-..."   # macOS / Linux
```

Make sure `data/schedule.json` exists and contains `[]`.

## Run the agent

```bash
python agent.py
```

The terminal shows each tool call the agent makes (`->`) and what the server returned (`<-`).

Example questions:

| Ask | Expected tool |
|---|---|
| `When is my data structures exam?` | `get_course_info` (Data) |
| `Add a study session for EECE503P on 2026-11-20 about MCP` | `add_study_session` (Action) |
| `Help me prepare for my Academic English exam` | `plan_exam_prep` (Orchestration) |
| `Plan my EECE290 exam` | Failure case: exam already passed |

Chat commands (these use the **resource**, read by the client, not by the AI):

- `/schedule` — print the full schedule from `schedule://all`
- `/review` — read `schedule://all` and pass it to the agent for feedback
- `exit` — quit

## Run the tests

```bash
pytest -v
```

The tests use temporary data files with dates relative to today, so they never modify your real
`data/` files. They cover every tool, every failure case, and the MCP layer itself
(discovery, a tool call through the client, and reading the resource).

## Design notes

- **Single-purpose tools:** only the orchestration tool combines steps. The data tool only reads; the
  action tool saves exactly one session.
- **Shared logic:** each tool is a thin wrapper around a plain helper function (`get_course`,
  `add_session`, `plan_prep`). The orchestration logic reuses the same helpers, so validation and error
  handling live in one place.