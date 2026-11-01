"""
Tests for the study-planner MCP server.

Run from the project folder:   pytest -v

Each test uses its OWN temporary courses.json and schedule.json (with dates relative
to today), so the tests never touch your real data files and never go out of date.
"""
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "import server" works

import server
from fastmcp import Client
from fastmcp.exceptions import ToolError

TODAY = date.today()


def days_from_today(n: int) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


@pytest.fixture(autouse=True)
def temp_data(tmp_path, monkeypatch):
    """Point the server at temporary data files for every test."""
    courses = {
        "TEST101": {  # exam in 10 days, 3 topics
            "name": "Test Course",
            "exam_date": days_from_today(10),
            "topics": ["Topic A", "Topic B", "Topic C"],
        },
        "PAST100": {  # exam already passed
            "name": "Past Course",
            "exam_date": days_from_today(-5),
            "topics": ["Old topic"],
        },
    }
    courses_file = tmp_path / "courses.json"
    schedule_file = tmp_path / "schedule.json"
    courses_file.write_text(json.dumps(courses))
    schedule_file.write_text("[]")

    monkeypatch.setattr(server, "COURSES_FILE", courses_file)
    monkeypatch.setattr(server, "SCHEDULE_FILE", schedule_file)
    return schedule_file


def read_schedule(schedule_file: Path) -> list:
    return json.loads(schedule_file.read_text())



def test_get_course_info_returns_details():
    info = server.get_course("TEST101")
    assert info["name"] == "Test Course"
    assert info["days_left"] == 10
    assert info["topics"] == ["Topic A", "Topic B", "Topic C"]


def test_get_course_info_accepts_lowercase_and_spaces():
    assert server.get_course("  test101 ")["course_code"] == "TEST101"


def test_get_course_info_unknown_course_fails_clearly():
    with pytest.raises(ToolError, match="not found"):
        server.get_course("NOPE999")


def test_get_course_info_does_not_change_schedule(temp_data):
    server.get_course("TEST101")
    assert read_schedule(temp_data) == []  # read-only



def test_add_session_saves_to_schedule(temp_data):
    session = server.add_session("TEST101", days_from_today(2), "Topic A")
    assert session == {"course_code": "TEST101", "date": days_from_today(2), "topic": "Topic A"}
    assert read_schedule(temp_data) == [session]


def test_add_session_bad_date_format():
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        server.add_session("TEST101", "12/05/2026", "Topic A")


def test_add_session_date_in_past():
    with pytest.raises(ToolError, match="in the past"):
        server.add_session("TEST101", days_from_today(-1), "Topic A")


def test_add_session_date_after_exam():
    with pytest.raises(ToolError, match="before the exam"):
        server.add_session("TEST101", days_from_today(15), "Topic A")


def test_add_session_empty_topic():
    with pytest.raises(ToolError, match="empty"):
        server.add_session("TEST101", days_from_today(2), "   ")


def test_add_session_duplicate(temp_data):
    server.add_session("TEST101", days_from_today(2), "Topic A")
    with pytest.raises(ToolError, match="already exists"):
        server.add_session("TEST101", days_from_today(2), "Topic A")
    assert len(read_schedule(temp_data)) == 1  # nothing extra was saved


def test_add_session_unknown_course():
    with pytest.raises(ToolError, match="not found"):
        server.add_session("NOPE999", days_from_today(2), "Topic A")



def test_plan_creates_one_session_per_topic_plus_review(temp_data):
    plan = server.plan_prep("TEST101")
    created = plan["sessions_created"]

    assert len(created) == 4  # 3 topics + Full review
    assert [s["topic"] for s in created] == ["Topic A", "Topic B", "Topic C", "Full review"]
    assert created[0]["date"] == days_from_today(0)        # first session today
    assert created[-1]["date"] == days_from_today(9)       # review the day before the exam
    assert plan["sessions_skipped"] == []
    assert len(read_schedule(temp_data)) == 4


def test_plan_twice_skips_duplicates_without_crashing():
    server.plan_prep("TEST101")
    second = server.plan_prep("TEST101")
    assert second["sessions_created"] == []
    assert len(second["sessions_skipped"]) == 4
    assert "already exists" in second["sessions_skipped"][0]["reason"]


def test_plan_exam_already_passed_fails_clearly(temp_data):
    with pytest.raises(ToolError, match="already passed"):
        server.plan_prep("PAST100")
    assert read_schedule(temp_data) == []  # nothing was saved


def test_plan_unknown_course_fails_clearly():
    with pytest.raises(ToolError, match="not found"):
        server.plan_prep("NOPE999")


def test_mcp_discovery_lists_three_tools_and_the_resource():
    async def run():
        async with Client(server.mcp) as client:
            tools = {t.name for t in await client.list_tools()}
            resources = {str(r.uri) for r in await client.list_resources()}
            return tools, resources

    tools, resources = asyncio.run(run())
    assert tools == {"get_course_info", "add_study_session", "plan_exam_prep"}
    assert "schedule://all" in resources


def test_mcp_tool_call_and_error_through_client():
    async def run():
        async with Client(server.mcp) as client:
            ok = await client.call_tool("get_course_info", {"course_code": "TEST101"})
            with pytest.raises(Exception, match="not found"):
                await client.call_tool("get_course_info", {"course_code": "NOPE999"})
            return ok

    result = asyncio.run(run())
    assert result.data["course_code"] == "TEST101"


def test_mcp_resource_returns_schedule():
    async def run():
        server.add_session("TEST101", days_from_today(1), "Topic B")
        async with Client(server.mcp) as client:
            contents = await client.read_resource("schedule://all")
            return json.loads(contents[0].text)

    schedule = asyncio.run(run())
    assert schedule == [{"course_code": "TEST101", "date": days_from_today(1), "topic": "Topic B"}]