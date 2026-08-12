"""Weather agent: an LLM with access to live weather data.

The script calls the Anthropic API, lets the model use two tools
(city geocoding and a weather forecast, both backed by the free
Open-Meteo API) and feeds the tool results back to the model until
it produces a final answer.

Usage:
    python homework_1.py                  interactive window (or double-click)
    python homework_1.py "Bratislava"
    python homework_1.py --verbose "Ake bude pocasie v Rime?"
"""

import argparse
import json
import os
import sys

import anthropic
import requests
from dotenv import load_dotenv

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HTTP_TIMEOUT = 10   # seconds
MAX_ROUNDS = 8      # hard stop so a confused model cannot loop forever

SYSTEM_PROMPT = """\
You are a concise weather assistant. Reply in the language of the user's
question; default to Slovak.

1. Treat any user message that could name a place - even a single word or
   a misspelling - as a weather question: call find_city with it right away.
   Never ask what the user meant before trying find_city. Then call
   get_forecast (3 days unless the user asks otherwise).
2. Summarise the forecast in 3-5 sentences of plain text: city and country,
   temperatures, and whatever matters that day (rain, storms, strong wind,
   big temperature swings). Add practical advice when useful.
3. Never invent weather data - the tools are your only source. If several
   cities match the name, ask the user which one they meant (numbered list);
   when they answer with a number or partial name, continue with that city.
4. Whenever you wait for the user's reply, end your message with one short
   line telling them exactly what to type, e.g. "Zvolte cislo mesta (1-5):".
   A finished answer that needs no reply must not end with ":" or "?".
5. Your output goes to a plain terminal - no Markdown, no ** or # or bullets."""

# Open-Meteo reports weather as bare WMO codes; translate them so the model
# does not have to guess what "61" means.
WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "dense drizzle",
    56: "freezing drizzle", 57: "dense freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "heavy freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}

# Tool schemas shown to the model. The descriptions say not only what each
# tool does but *when* to call it - that is what drives the model's choices.
TOOLS = [
    {
        "name": "find_city",
        "description": (
            "Look up geographic coordinates for a city name. Always call this "
            "first when the user asks about weather - the forecast needs "
            "coordinates. Returns several candidates; if the name is ambiguous, "
            "ask the user which city they meant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "City name, e.g. 'Bratislava'."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_forecast",
        "description": (
            "Daily weather forecast (temperatures, precipitation, wind, sky "
            "condition) for the given coordinates. Get the coordinates from "
            "find_city first. Never guess the weather - without this tool you "
            "have no access to current data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"},
                "days": {"type": "integer", "description": "Forecast length in days (1-7), default 3."},
            },
            "required": ["latitude", "longitude"],
        },
    },
]


class ToolError(Exception):
    """Expected tool failure - reported back to the model instead of crashing."""


def find_city(name: str) -> list[dict]:
    """Resolve a city name to coordinates via the Open-Meteo geocoder."""
    if not name.strip():
        raise ToolError("City name is empty.")
    try:
        resp = requests.get(
            GEOCODING_URL,
            params={"name": name, "count": 5, "language": "sk"},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ToolError(f"Geocoding service unavailable: {exc}")

    results = resp.json().get("results")
    if not results:
        raise ToolError(f"No match for '{name}'. Try a different spelling or add a country.")
    keys = ("name", "country", "admin1", "latitude", "longitude")
    return [{k: r.get(k) for k in keys} for r in results]


def get_forecast(latitude: float, longitude: float, days: int = 3) -> dict:
    """Fetch a daily forecast for the given coordinates from Open-Meteo."""
    if not 1 <= days <= 7:
        raise ToolError(f"Forecast length must be 1-7 days, got {days}.")
    try:
        resp = requests.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "forecast_days": days,
                "timezone": "auto",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                         "precipitation_sum,wind_speed_10m_max",
            },
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ToolError(f"Weather service unavailable: {exc}")

    daily = resp.json().get("daily")
    if not daily:
        raise ToolError("The weather service returned no forecast for these coordinates.")
    return {
        "days": [
            {
                "date": date,
                "weather": WMO_CODES.get(code, f"unknown (code {code})"),
                "temp_max_c": tmax,
                "temp_min_c": tmin,
                "precipitation_mm": rain,
                "wind_max_kmh": wind,
            }
            for date, code, tmax, tmin, rain, wind in zip(
                daily["time"], daily["weather_code"],
                daily["temperature_2m_max"], daily["temperature_2m_min"],
                daily["precipitation_sum"], daily["wind_speed_10m_max"],
            )
        ]
    }


TOOL_FUNCTIONS = {"find_city": find_city, "get_forecast": get_forecast}


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    """Execute one tool call; return (result_json, is_error).

    Failures do not crash the agent - they are sent back to the model as an
    error result, so it can retry with different input or explain the problem.
    """
    try:
        return json.dumps(TOOL_FUNCTIONS[name](**args), ensure_ascii=False), False
    except ToolError as exc:
        return str(exc), True
    except Exception as exc:  # unknown tool, bad arguments from the model, ...
        return f"{type(exc).__name__}: {exc}", True


def run_agent(client: anthropic.Anthropic, model: str, messages: list, verbose: bool = False) -> str:
    """The tool-use loop: call the LLM, run requested tools, feed results back.

    Works on the caller's message list in place, so the interactive mode can
    keep one continuous conversation - e.g. answering "1" to pick a city from
    the candidates the model listed a turn earlier.
    """
    for round_no in range(1, MAX_ROUNDS + 1):
        if verbose:
            print(f"\n-> LLM (round {round_no})")

        # max_tokens also covers the model's internal reasoning (on by
        # default for claude-opus-5), so it needs headroom beyond the answer.
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Every assistant turn goes into the history: tool_use blocks must be
        # paired with results, and final answers keep context for follow-ups.
        messages.append({"role": "assistant", "content": response.content})

        # No more tool calls - the model has its final answer.
        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return text or f"[model stopped: {response.stop_reason}]"

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if verbose:
                print(f"  <- tool_use: {block.name}({json.dumps(block.input, ensure_ascii=False)})")
            output, is_error = run_tool(block.name, block.input)
            if verbose:
                shown = output if len(output) <= 250 else output[:250] + " ..."
                print(f"  -> tool_result{' (ERROR)' if is_error else ''}: {shown}")
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": is_error,
            })
        messages.append({"role": "user", "content": results})

    return f"No final answer after {MAX_ROUNDS} rounds - aborting."


def main() -> None:
    parser = argparse.ArgumentParser(description="Weather agent - an LLM with live Open-Meteo data.")
    parser.add_argument("question", nargs="*", help='city or question, e.g. "Bratislava"')
    parser.add_argument("-v", "--verbose", action="store_true", help="print every tool call")
    args = parser.parse_args()

    load_dotenv()
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Chýba ANTHROPIC_API_KEY - skopíruj .env.example na .env a doplň svoj kľúč.")
        input("Stlač Enter na zavretie okna...")  # keep it readable on double-click
        sys.exit(1)

    client = anthropic.Anthropic()
    model = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")

    # One-shot mode: python homework_1.py "Bratislava"
    if args.question:
        history = [{"role": "user", "content": " ".join(args.question)}]
        try:
            print("\n" + run_agent(client, model, history, verbose=args.verbose))
        except anthropic.APIError as exc:
            sys.exit(f"Chyba Anthropic API: {exc}")
        return

    # Interactive mode - also what you get when double-clicking the file.
    # One shared history for the whole session, so the user can answer the
    # model's clarifying questions; an empty line quits.
    history = []
    prompt = "\nMesto: "
    print("Agent na počasie - tvoj asistent na sledovanie počasia kdekoľvek na svete.")
    print("Zadaj mesto a agent preň vyhľadá aktuálnu predpoveď na najbližšie 3 dni")
    print("a zhrnie ti ju v pár vetách. Prázdny riadok program ukončí.")
    while True:
        try:
            question = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        history.append({"role": "user", "content": question})
        try:
            answer = run_agent(client, model, history, verbose=args.verbose)
        except anthropic.APIError as exc:
            print(f"Chyba Anthropic API: {exc}")
            continue
        print("\n" + answer)
        # The system prompt makes the model end anything that awaits a reply
        # (e.g. picking a city candidate) with ":" or "?" - switch the input
        # prompt so it is obvious we expect an answer, not a new city.
        prompt = "Odpoveď: " if answer.endswith((":", "?")) else "\nMesto: "


if __name__ == "__main__":
    # The Windows console defaults to a legacy code page; without UTF-8 the
    # degree sign and Slovak diacritics in the answer would crash the print.
    # Some shells (IDLE) replace sys.stdout with an object that cannot be
    # reconfigured but already handles Unicode - skip it there.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except Exception:  # on double-click the window would vanish before the
        import traceback  # traceback can be read - keep it open
        traceback.print_exc()
        input("\nStlač Enter na zavretie okna...")
