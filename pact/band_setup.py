"""Register the shopper and merchant as BAND remote agents (once).

    uv run python -m pact.band_setup

Uses the human BAND_API_KEY; stores each agent's own id + key in
.local/band.json (gitignored).
"""
import asyncio
import json

from band_rest import AgentRegisterRequest, AsyncRestClient

from .band import AGENTS, STATE_FILE, human_client, load_band_agents


async def main() -> None:
    state = load_band_agents() or {}
    client: AsyncRestClient = human_client()
    for name, description in AGENTS.items():
        if name in state:
            print(f"{name}: already registered ({state[name]['agent_id']})")
            continue
        res = await client.human_api_agents.register_my_agent(
            agent=AgentRegisterRequest(name=name, description=description))
        creds = res.data
        state[name] = {"agent_id": creds.agent.id, "api_key": creds.credentials.api_key}
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))  # save after each so a failure keeps progress
        print(f"{name}: registered ({state[name]['agent_id']})")


if __name__ == "__main__":
    asyncio.run(main())
