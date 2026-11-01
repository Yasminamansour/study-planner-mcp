import json
from datetime import date, timedelta
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

# Create the MCP server and give it a name
mcp = FastMCP("study-planner")

# Paths to our data files (works no matter where you run the script from)
DATA_DIR = Path(__file__).parent / "data"
COURSES_FILE = DATA_DIR / "courses.json"
SCHEDULE_FILE = DATA_DIR / "schedule.json"


# Plain helper functions (the real logic).
# The MCP tools call these, and the orchestration logic reuses them.


def load_courses() -> dict:
    return json.loads(COURSES_FILE.read_text())


def load_schedule() -> list:
    """Read the schedule. Missing or blank file = empty schedule."""
    if not SCHEDULE_FILE.exists():
        return []
    text = SCHEDULE_FILE.read_text().strip()
    if not text:  # file exists but is blank
        return []
    return json.loads(text)


def save_schedule(schedule: list) -> None:
    SCHEDULE_FILE.write_text(json.dumps(schedule, indent=2))


def get_course(course_code: str) -> dict:
    """Return info for one course, or raise a clear error if it doesn't exist."""
    courses = load_courses()
    code = course_code.strip().upper()

    if code not in courses:
        available = ", ".join(courses.keys())
        raise ToolError(f"Course '{course_code}' not found. Available courses: {available}")

    course = courses[code]
    exam_date = date.fromisoformat(course["exam_date"])
    return {
        "course_code": code,
        "name": course["name"],
        "exam_date": course["exam_date"],
        "days_left": (exam_date - date.today()).days,
        "topics": course["topics"],
    }


def add_session(course_code: str, session_date: str, topic: str) -> dict:
    """Save one study session, or raise a clear error if it's invalid."""
    course = get_course(course_code)  # also checks the course exists

    # Failure case 1: wrong date format
    try:
        day = date.fromisoformat(session_date)
    except ValueError:
        raise ToolError(f"Invalid date '{session_date}'. Use the format YYYY-MM-DD, e.g. 2026-12-01.")

    # Failure case 2: date in the past
    if day < date.today():
        raise ToolError(f"Date {session_date} is in the past. Choose today or a future date.")

    # Failure case 3: date on or after the exam
    exam_day = date.fromisoformat(course["exam_date"])
    if day >= exam_day:
        raise ToolError(
            f"Date {session_date} is not before the {course['course_code']} exam "
            f"on {course['exam_date']}. Study sessions must be before the exam."
        )

    # Failure case 4: empty topic
    if not topic.strip():
        raise ToolError("Topic cannot be empty.")

    schedule = load_schedule()
    new_session = {"course_code": course["course_code"], "date": session_date, "topic": topic.strip()}

    # Failure case 5: duplicate session
    if new_session in schedule:
        raise ToolError(f"This session already exists: {new_session}")

    schedule.append(new_session)
    save_schedule(schedule)
    return new_session


def plan_prep(course_code: str) -> dict:
    """Orchestration logic: get the course (data), then save one session per topic (action),
    spread from today until the day before the exam, ending with a full review."""
    # Step 1: data logic
    course = get_course(course_code)

    # Step 2: failure case - exam already passed (or is today)
    if course["days_left"] <= 0:
        raise ToolError(
            f"The {course['course_code']} exam was on {course['exam_date']} "
            f"(days left: {course['days_left']}). Cannot plan for an exam that is today or already passed."
        )

    # Step 3: what to study - every topic, then a full review
    items = course["topics"] + ["Full review"]

    # Step 4: spread items over the available days (today ... day before the exam)
    n_days = course["days_left"]
    n_items = len(items)
    today = date.today()

    created, skipped = [], []
    for i, topic in enumerate(items):
        # evenly spaced: first item today, last item (Full review) on the day before the exam
        day_index = round(i * (n_days - 1) / (n_items - 1))
        session_date = (today + timedelta(days=day_index)).isoformat()

        # Step 5: action logic, with error resilience (one failure doesn't stop the plan)
        try:
            created.append(add_session(course["course_code"], session_date, topic))
        except ToolError as e:
            skipped.append({"date": session_date, "topic": topic, "reason": str(e)})

    # Step 6: summary
    return {
        "course_code": course["course_code"],
        "exam_date": course["exam_date"],
        "days_left": course["days_left"],
        "sessions_created": created,
        "sessions_skipped": skipped,
        "summary": f"Created {len(created)} session(s), skipped {len(skipped)}.",
    }

# MCP tools (what the AI sees and can call)

@mcp.tool()
def get_course_info(course_code: str) -> dict:
    """Look up a course's name, exam date, exam topics, and days left until the exam.
    Read-only: this tool does not change anything.

    Args:
        course_code: The course code, e.g. "EECE503P".
    """
    return get_course(course_code)


@mcp.tool()
def add_study_session(course_code: str, session_date: str, topic: str) -> dict:
    """Add ONE study session for a course to the study schedule.
    This changes the schedule (it saves a new session).

    Args:
        course_code: The course code, e.g. "EECE503P".
        session_date: The study date in YYYY-MM-DD format. Must be today or later, and before the exam.
        topic: The topic to study in this session, e.g. "Hash tables".

    Returns:
        The saved session: {"course_code", "date", "topic"}.
    """
    return add_session(course_code, session_date, topic)


@mcp.tool()
def plan_exam_prep(course_code: str) -> dict:
    """Create a full study plan for a course's exam: looks up the course's topics and exam date,
    then schedules one study session per topic, spread from today until the day before the exam,
    ending with a full review. Use this when the user wants a complete plan, not a single session.

    Args:
        course_code: The course code, e.g. "EECE503P".

    Returns:
        The sessions created, any sessions skipped (with the reason), and a short summary.
    """
    return plan_prep(course_code)

# MCP resource (read by the client/app, not called by the AI)

@mcp.resource("schedule://all")
def full_schedule() -> str:
    """The complete study schedule: every saved study session, as JSON. Read-only."""
    return json.dumps(load_schedule(), indent=2)


if __name__ == "__main__":
    mcp.run()