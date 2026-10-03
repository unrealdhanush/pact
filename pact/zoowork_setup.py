"""Create (or update) and start the ZooWork merchant agent.

    uv run python -m pact.zoowork_setup           # create once, reuse after
    uv run python -m pact.zoowork_setup --update  # push changed instructions/tools
"""
import asyncio
import json
import sys

from dotenv import load_dotenv

from .agents.zoowork_merchant import agent_resource
from .zoowork import STATE_FILE, ZooWorkClient, load_agent_id


async def main() -> None:
    load_dotenv()
    client = ZooWorkClient()
    try:
        agent_id = load_agent_id()
        if agent_id and "--update" in sys.argv:
            await client.update_agent(agent_id, agent_resource())
            print(f"updated {agent_id}")
        elif not agent_id:
            created = await client.create_agent(agent_resource(), idempotency_key="pact:merchant-agent:v1")
            agent_id = created.get("agent_id") or created.get("id")
            STATE_FILE.parent.mkdir(exist_ok=True)
            STATE_FILE.write_text(json.dumps({"agent_id": agent_id}, indent=2))
            print(f"created {agent_id}")
        started = await client.start_agent(agent_id)
        print("started", started.get("warnings") or "")
        agent = await client.get_agent(agent_id)
        print({k: agent.get(k) for k in ("agent_id", "name", "desired_state", "actual_state")})
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
