"""
Study Planner agent (MCP Host + Client) built with the OpenAI Agents SDK.

Run:  python agent.py
Needs the OPENAI_API_KEY environment variable to be set.

Commands inside the chat:
  /schedule  -> the CLIENT reads the resource schedule://all and prints it (no AI involved)
  /review    -> the CLIENT reads schedule://all and passes it to the agent for feedback
  exit       -> quit
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

from agents import Agent, Runner
from agents.mcp import MCPServerStdio

SERVER_PATH = Path(__file__).parent / "server.py"

# Shows what the agent did 
def clean_output(output) -> str:
    """Remove the SDK's {'type': 'text', 'text': ...} wrapper and keep only the text."""
    if isinstance(output, dict) and "text" in output:
        return output["text"]
    if isinstance(output, list):
        return "\n".join(clean_output(part) for part in output)
    return str(output)


def show_round_trip(result) -> None:
    """Print every tool call the agent made, so the round trip is visible."""
    for item in result.new_items:
        if item.type == "tool_call_item":
            print(f"  -> [agent asks to call] {item.raw_item.name}({item.raw_item.arguments})")
        elif item.type == "tool_call_output_item":
            output = clean_output(item.output)
            print(f"  <- [server returned]   {output[:300]}{'...' if len(output) > 300 else ''}")


# Here the client reads the resource
async def read_schedule_resource(server) -> str:
    """The CLIENT reads the resource directly (the AI cannot do this itself)."""
    result = await server.session.read_resource("schedule://all") # we are getting resources at a certain address like an API 
    return result.contents[0].text

# we start the MCP connection 
async def main() -> None:
    # 1) CLIENT: start server.py as a separate process and connect to it over MCP
    async with MCPServerStdio(  # we connect to the serve using stdio
        name="study-planner",
        params={"command": sys.executable, "args": [str(SERVER_PATH)]},
        cache_tools_list=True,
    ) as server:

        # Dynamic discovery: the client asks the server what tools does he offer
        tools = await server.list_tools()
        # printing a list of the offered tools
        print("Connected to MCP server. Tools discovered:", [t.name for t in tools])

        # 2) HOST: the agentthat decides which tool to call
        agent = Agent(
            name="Study Planner",
            instructions=(
                f"You are a helpful study planning assistant. Today's date is {date.today().isoformat()}. "
                "Use the tools to answer questions about courses, exams, and study sessions. "
                "Never guess course information: look it up with get_course_info. "
                "Use add_study_session to add ONE session, and plan_exam_prep when the user wants a full plan. "
                "Dates passed to tools must be in YYYY-MM-DD format. "
                "If a tool returns an error, explain it clearly to the user and suggest what to do."
            ),
            mcp_servers=[server], # we are giving the agent access to the tools the server offers,
                                  # connecting the agent to my tools.
        )
        # shows the first message on the screen.
        print("\nAsk me about your courses and study plan. Commands: /schedule, /review, exit")
        history = []

        # 3) Chat loop
        while True:
            user_input = input("\nYou: ").strip()
            if not user_input: # ignore empty messages
                continue
            if user_input.lower() in {"exit", "quit"}: # users wants to quit
                break

            # Resource used by the CLIENT only
            if user_input == "/schedule":
                print(await read_schedule_resource(server))
                continue

            # Resource read by the CLIENT, then handed to the AI inside the message
            if user_input == "/review":
                schedule = await read_schedule_resource(server)
                user_input = (
                    f"Here is my current study schedule (JSON):\n{schedule}\n\n"
                    "Review it: am I studying enough for each exam? Give short, concrete advice."
                )

            result = await Runner.run(agent, history + [{"role": "user", "content": user_input}])
            show_round_trip(result)
            print(f"\nAgent: {result.final_output}")
            history = result.to_input_list()  # keep the conversation so follow-ups work


if __name__ == "__main__":
    asyncio.run(main())