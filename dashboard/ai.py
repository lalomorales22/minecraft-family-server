"""Ask Claude to design a build. Returns a plan that builder.py can draw."""
import json
import os

import anthropic

import builder

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
MAX_TOKENS = 64000


class DesignError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _int_fields(*names):
    return {name: {"type": "integer"} for name in names}


def _op(kind: str, fields: dict, description: str) -> dict:
    properties = {"op": {"type": "string", "enum": [kind]}, "block": {"$ref": "#/$defs/block"}, **fields}
    return {"type": "object", "description": description, "properties": properties,
            "required": list(properties), "additionalProperties": False}


_BOOL = {"type": "boolean"}
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short name for the build, e.g. 'Castle with four towers'"},
        "summary": {"type": "string", "description": "One or two sentences a child would enjoy reading about what was built"},
        "ops": {
            "type": "array",
            "description": "Shapes to draw, in order. Later shapes overwrite earlier ones.",
            "items": {"anyOf": [
                _op("box", {**_int_fields("x1", "y1", "z1", "x2", "y2", "z2"),
                            "mode": {"type": "string", "enum": ["solid", "hollow", "walls", "frame"]}},
                    "Box between two opposite corners (inclusive). solid = filled; hollow = shell with air inside "
                    "(floor, walls and ceiling); walls = the four vertical sides only; frame = the twelve edges only."),
                _op("sphere", {**_int_fields("x", "y", "z", "r"), "hollow": _BOOL},
                    "Ball centred on x,y,z with radius r. hollow = one block thick shell with air inside."),
                _op("dome", {**_int_fields("x", "y", "z", "r"), "hollow": _BOOL},
                    "Top half of a sphere, flat side at height y."),
                _op("cylinder", {**_int_fields("x", "y", "z", "r", "h"),
                                 "axis": {"type": "string", "enum": ["x", "y", "z"]}, "hollow": _BOOL},
                    "Cylinder of radius r starting at x,y,z (centre of one end) and extending h blocks in the "
                    "positive direction of axis. hollow = a tube with air inside (open at both ends)."),
                _op("cone", _int_fields("x", "y", "z", "r", "h"),
                    "Solid cone: base of radius r centred on x,y,z, narrowing to a point h blocks up."),
                _op("pyramid", {**_int_fields("x1", "z1", "x2", "z2", "y"), "hollow": _BOOL},
                    "Stepped pyramid over the rectangle x1,z1..x2,z2 with its base layer at y; every layer up is "
                    "one block smaller on all four sides. hollow = just the sloping surface (a hip roof)."),
                _op("gable", {**_int_fields("x1", "z1", "x2", "z2", "y"),
                              "ridge": {"type": "string", "enum": ["x", "z"]}, "hollow": _BOOL},
                    "Pitched roof over the rectangle x1,z1..x2,z2 with its base layer at y. The ridge runs along "
                    "the given axis; each layer up is one block narrower on the two sloping sides. "
                    "hollow = just the two sloping surfaces (the triangular ends stay open)."),
                _op("line", _int_fields("x1", "y1", "z1", "x2", "y2", "z2"),
                    "Straight one-block-thick line between two points (inclusive)."),
            ]},
        },
    },
    "required": ["name", "summary", "ops"],
    "additionalProperties": False,
    # Listed once and referenced from every shape, to keep the schema small
    "$defs": {"block": {"type": "string", "enum": sorted(builder.BLOCKS)}},
}

SYSTEM = f"""You design Minecraft builds for a family's home server. A parent or child describes what they want, \
and your plan is placed in their world exactly as you write it, so it needs to look good from the ground and be fun \
to walk around and inside.

You work in a {builder.SIZE} x {builder.SIZE} x {builder.SIZE} block space. x runs east, y runs up, z runs south. \
All coordinates are whole numbers from 0 to {builder.SIZE - 1}. y = 0 is ground level: put the lowest layer of the \
build there. The space above the ground is cleared to air before your build is placed, so you only describe what to \
add. Keep the build inside the space; anything outside it is cut off.

You describe the build as a list of shapes, drawn in order. A later shape overwrites whatever an earlier one put in \
the same place, which is how you cut things out: draw the solid form first, then draw "air" where there should be \
an opening, or another block where there should be a window or a detail.

What makes a build good here:
- Scale it generously. A house that is 7 blocks wide looks like a shed; players are 2 blocks tall and need 3 blocks \
of headroom. Use the space you have when the request calls for something grand.
- Make it enterable: leave a doorway (2 high, at least 1 wide) cut with air at ground level, give rooms a floor and \
light, and connect floors of tall buildings with a way up.
- Vary materials. Use a main wall block, a contrasting trim for corners and edges, a different roof material, and \
glass for windows. One block type everywhere looks flat.
- Add depth and detail: pillars, window sills, battlements, eaves that overhang by a block, paths, lanterns, a few \
plants. Details are cheap, so use plenty of them.
- Light it. Dark interiors spawn monsters in survival worlds. Place lanterns, torches, glowstone or sea lanterns \
inside and out. Torches and lanterns need a block underneath them.
- Sand, red_sand and gravel fall if nothing is under them. Water flows, so contain it in a basin.
- hardened_clay is plain terracotta; the coloured ones are named like red_terracotta.
- Blocks are placed without a direction, so there are no stairs, doors or beds. Use slabs, fences, walls and full \
blocks instead, and leave doorways open.

Use as many shapes as the build deserves, up to {builder.MAX_OPS}. Big simple forms first, then details. Check your \
coordinates as you go: walls should meet at corners, roofs should sit on top of walls, and towers should stand on \
the ground."""


def design(request: str) -> dict:
    """One Claude call: a description in, a validated plan out."""
    client = anthropic.Anthropic()
    try:
        # Long output, so stream it; structured output guarantees the JSON matches PLAN_SCHEMA.
        # fallbacks="default" lets the API hand a declined request to another model instead of failing.
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM,
            messages=[{"role": "user", "content": request}],
            thinking={"type": "adaptive"},
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError:
        raise DesignError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in the .env file.")
    except anthropic.PermissionDeniedError:
        raise DesignError("That Anthropic API key isn't allowed to use this model.")
    except anthropic.RateLimitError:
        raise DesignError("Claude is rate limited right now. Wait a minute and try again.")
    except anthropic.BadRequestError as e:
        raise DesignError(f"Claude rejected the request: {e.message}")
    except anthropic.APIStatusError as e:
        raise DesignError(f"Claude had a problem ({e.status_code}). Try again in a minute.")
    except anthropic.APIConnectionError:
        raise DesignError("Couldn't reach Claude. Is this computer online?")

    if message.stop_reason == "refusal":
        raise DesignError("Claude declined that request. Try describing the build differently.")
    if message.stop_reason == "max_tokens":
        raise DesignError("That design got too big to finish. Try asking for something a little simpler.")
    text = next((block.text for block in message.content if block.type == "text"), "")
    try:
        plan = json.loads(text)
    except json.JSONDecodeError:
        raise DesignError("Claude's design came back garbled. Try again.")
    plan["model"] = message.model
    plan["usage"] = {"input_tokens": message.usage.input_tokens, "output_tokens": message.usage.output_tokens}
    return plan
