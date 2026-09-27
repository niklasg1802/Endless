"""Writers' room.

Episode 3 felt random because 240 shots shared 36 pictures and 13 spoken lines,
86 of those shots named nobody, and the same nine rooms were cloned to fill
twenty minutes. `validate` rejects that shape. `proof_scene` is a short episode
that passes: one flaw, one premise that punishes it, and a different picture
in every shot.

    python -m pipeline.story selftest
    python -m pipeline.story proof --out scenes/proof-the-errand.json
    python -m pipeline.story check scenes/proof-the-errand.json
    python -m pipeline.story write "a premise" --out scenes/from-premise.json
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from pipeline.cast import CAST, DIALOGUE, STYLE_BLOCK, apply  # noqa: E402
from pipeline import llm  # noqa: E402


class StoryError(ValueError):
    pass


def _character(key):
    spec = CAST[key]
    return {
        "sheet": spec["sheet"],
        "sheet_prompt": spec["sheet_prompt"],
        "lock": spec["lock"],
        "voice": spec["voice"],
        "negative": spec["negative"],
    }


def _shot(sid, location, characters, action, dialogue, seconds=5):
    """One shot. The picture is the action in a place, not a reused room string."""
    who = " and ".join(characters) if characters else "nobody"
    keyframe = (
        f"{action} The background is a fully drawn {location}, with furniture and "
        f"walls, not a plain grey backdrop. In frame: {who}."
    )
    return {
        "id": sid,
        "location": location,
        "characters": list(characters),
        "seconds": seconds,
        "action": action,
        "dialogue": [{"speaker": s, "line": line} for s, line in dialogue],
        "keyframe_prompt": keyframe,
    }


def _motion(shot):
    parts = [
        "Animate this still. Keep each character's design identical to the still: "
        "same hair silhouette, face, and clothes. Flat 2D cel animation. "
        "Do not restyle anyone and do not add a new person."
    ]
    parts.append(shot["action"])
    for line in shot["dialogue"]:
        spec = CAST[line["speaker"]]
        parts.append(f'{line["speaker"]}, {spec["voice"]}, says: "{line["line"]}"')
    if not shot["characters"]:
        parts.append("No people enter the frame.")
    else:
        parts.append(
            "Mouths move on the spoken lines. Hands and props move only as the "
            "action describes. The camera does not wander off to a new place."
        )
    return "\n\n".join(parts)


def _assemble(title, shots, seed=7, premise=None, slug=None):
    if slug is None and title.startswith("The Errand"):
        slug = "proof-the-errand"
    scene = {
        "title": title,
        "slug": slug,
        "backend": "local",
        "width": 864,
        "height": 480,
        "seed": seed,
        "style_block": STYLE_BLOCK,
        "premise": premise or (
            "Rick would rather break a room than be told what to do in it. "
            "He promises Morty a twenty-minute errand to dodge a therapy "
            "appointment, and the errand is the appointment."
        ),
        "characters": {
            key: _character(key)
            for key in dict.fromkeys(
                name
                for shot in shots
                for name in (shot.get("characters") or [])
                if name in CAST
            )
        },
        "shots": shots,
    }
    if scene["slug"] is None:
        del scene["slug"]
    for shot in scene["shots"]:
        shot["motion_prompt"] = _motion(shot)
    return scene


def proof_scene():
    """Eight shots, one story. Morty's question and Rick's refusal are the same question."""
    shots = [
        _shot(
            "co1", "garage", ["morty", "rick"],
            "Morty stands in the garage doorway holding his phone out toward Rick. "
            "Rick is already aiming a portal gun at the wall calendar and does not look at the phone.",
            [
                ("rick", "Twenty minutes. In and out. Nobody has a feeling about it."),
                ("morty", "The text says the appointment is now, Rick."),
            ],
        ),
        _shot(
            "a1", "garage", ["rick", "morty"],
            "A swirling green portal opens in the garage wall, burning the paper "
            "calendar off at the edges. Rick looks pleased. Morty looks at the ashes, not the portal.",
            [
                ("rick", "See? I handled it."),
                ("morty", "You handled the calendar."),
            ],
        ),
        _shot(
            "a2", "waiting room", ["morty", "rick"],
            "They step through into a waiting room that is their own living room "
            "copied in a line forever. In every copy a Rick is already sitting, pretending he just got there.",
            [
                ("morty", "Why do they all have your face?"),
                ("rick", "Because I'm early. I'm always early. That's the opposite of a problem."),
            ],
        ),
        _shot(
            "a3", "waiting room", ["morty", "rick"],
            "Morty sits in the single empty chair. Rick stays standing beside it, "
            "portal gun pointed at the floor, refusing the chair next to Morty.",
            [
                ("morty", "There's a chair."),
                ("rick", "Chairs are for people who are staying. I'm a corridor."),
            ],
        ),
        _shot(
            "a4", "waiting room", ["rick", "morty"],
            "A door at the far end opens a crack and a paper sign slides out that "
            "reads SAY WHY YOU CAME. Rick burps at the sign. The door shuts.",
            [
                ("rick", "We came because the door was there."),
                ("morty", "It says why. It doesn't say a place."),
            ],
        ),
        _shot(
            "a5", "waiting room", ["morty", "rick"],
            "The other Ricks are gone. Two chairs remain. Morty looks at Rick and "
            "does not look away. The portal gun in Rick's hand has no swirl. It is dead.",
            [
                ("morty", "You didn't want me to go in alone."),
                ("rick", "I didn't want you to come back worse. That's not the same sentence. Don't combine them."),
            ],
        ),
        _shot(
            "r1", "garage", ["morty", "rick"],
            "The portal dumps them onto the garage floor. Morty's phone buzzes "
            "APPOINTMENT ENDED. Rick is already reaching for a wrench on the bench.",
            [
                ("morty", "We missed it."),
                ("rick", "We attended a different one. I'm counting it."),
            ],
        ),
        _shot(
            "tag", "garage", ["morty", "rick"],
            "The portal gun coughs and one waiting-room chair drops onto the workbench "
            "between them. Morty looks at the chair. Rick looks at the wrench.",
            [
                ("morty", "That's the chair."),
                ("rick", "It's a chair. Chairs don't mean things. Hand me the wrench."),
            ],
        ),
    ]
    scene = _assemble("The Errand", shots)
    scene["slug"] = "proof-the-errand"
    validate(scene)
    return scene


def the_check_scene():
    """Three minutes. Rick will not pay for bringing Morty. The bill is the episode."""
    g = (
        "cluttered suburban garage laboratory, closed garage door, concrete floor, "
        "pegboard of tools, stained workbench, one shop light, not a hallway and not an office"
    )
    booth = (
        "one red-vinyl diner booth with a formica table, a dark parking-lot window, "
        "a ketchup bottle, and no one else in the aisle"
    )
    shots = [
        _shot(
            "co1", g, ["morty", "rick"],
            "Morty stands at the workbench holding a long crumpled diner check out toward Rick. "
            "Rick is hunched over a portal gun and will not look at the paper.",
            [
                ("rick", "That's not a bill. Bills are for people who ordered."),
                ("morty", "It has my name on it. I didn't order being scared."),
            ],
            seconds=10,
        ),
        _shot(
            "a1", g, ["rick", "morty"],
            "Rick fires the portal gun at the check. The paper flies into a small green swirl "
            "and comes back out larger, with a fresh line of ink still wet.",
            [
                ("rick", "I disputed it."),
                ("morty", "You disputed it into a longer one."),
            ],
            seconds=12,
        ),
        _shot(
            "a2", "narrow American diner with vinyl booths, a checkered floor, and menus that are old checks",
            ["morty", "rick"],
            "They step out of a green portal into the diner aisle. The only waiter is another Rick "
            "in a stained apron. Morty stays beside the portal. Rick is already offended.",
            [
                ("morty", "Why is the waiter you?"),
                ("rick", "Because I'm not tipping a stranger for my own face."),
            ],
            seconds=12,
        ),
        _shot(
            "a3", booth, ["rick", "morty"],
            "Waiter-Rick slaps down a plate of pancakes with one candle and a check as long as the table. "
            "One printed line reads BROUGHT THE KID. Morty stares at the candle. Rick stares at the line.",
            [
                ("rick", "I didn't order pancakes. I ordered you to stop reading."),
                ("morty", "There's a candle in them. That's a birthday. That's worse."),
            ],
            seconds=14,
        ),
        _shot(
            "a4", booth, ["rick", "morty"],
            "Rick stabs one line of the check with a pen. A new line prints itself underneath "
            "while the pen is still touching the paper. Morty leans away from the growing page.",
            [
                ("rick", "I'm not paying for a portal I built."),
                ("morty", "You're not paying for the part where I threw up in it, and that line is in pen."),
            ],
            seconds=14,
        ),
        _shot(
            "a5", "diner cash register on a linoleum counter, a bell, a tip jar, booths behind",
            ["morty", "rick"],
            "Morty lays one ordinary dollar on the counter. The register swallows it and spits out "
            "a small photo of Morty. Rick plucks the photo out of the tray.",
            [
                ("morty", "That was a real dollar."),
                ("rick", "Nothing that fits in a register is real. I'll expense the photo."),
            ],
            seconds=12,
        ),
        _shot(
            "a6", "diner aisle between two rows of booths",
            ["morty", "rick"],
            "Fill every red booth with a seated Rick, each one holding a huge check and not eating. "
            "Morty stands in the near aisle. Our Rick stands center with his arms folded. "
            "The other Ricks must be visible in the seats, not an empty diner.",
            [
                ("morty", "None of them are eating."),
                ("rick", "Eating is how they get you to agree you were here."),
            ],
            seconds=14,
        ),
        _shot(
            "a7", "diner pass-through window",
            ["morty", "rick"],
            "Through the pass window the kitchen is their own garage workbench. A cook who is Rick "
            "refuses to plate a plain breakfast. Morty points. Rick does not look surprised.",
            [
                ("morty", "That's our garage."),
                ("rick", "It's a kitchen that happens to be right. Don't get sentimental about a bench."),
            ],
            seconds=12,
        ),
        _shot(
            "a8", booth, ["morty", "rick"],
            "Morty puts a fork into Rick's hand and points at the single pancake. "
            "Rick holds the fork like it is a weapon he did not design.",
            [
                ("morty", "One bite you didn't invent. Then we leave."),
                ("rick", "I don't finish meals. Meals finish people who stay."),
            ],
            seconds=14,
        ),
        _shot(
            "a9", booth, ["rick", "morty"],
            "Rick opens a tiny green portal on the plate and drops the bite through it. "
            "The plate doubles. Two pancakes. Two candles. Morty's face falls.",
            [
                ("rick", "Handled."),
                ("morty", "Now there are two birthdays."),
            ],
            seconds=12,
        ),
        _shot(
            "a10", "narrow tiled diner exit with a metal turnstile",
            ["morty", "rick"],
            "Morty has passed through the turnstile. Rick is stuck on the near side because "
            "his lab coat is plastered with printed charges. He reaches after Morty.",
            [
                ("morty", "It let me through."),
                ("rick", "Because you're a line item, not a customer. Get back here."),
            ],
            seconds=14,
        ),
        _shot(
            "a11", "narrow tiled diner exit with a metal turnstile",
            ["rick", "morty"],
            "Rick finds the charge that reads BROUGHT THE KID and tears that strip off his coat. "
            "The turnstile clicks open. Rick looks ill. Morty watches from the far side.",
            [
                ("rick", "I'm not paying that. I'm removing it."),
                ("morty", "Tearing it off isn't the same as it not being true."),
            ],
            seconds=14,
        ),
        _shot(
            "a12", g, ["morty", "rick"],
            "They are dumped on the garage floor. The same check lies on the workbench and is "
            "still printing a fresh line. Morty watches the paper grow. Rick refuses to watch it.",
            [
                ("morty", "It's still printing."),
                ("rick", "Printers are cowards. They only run when you look at them."),
            ],
            seconds=12,
        ),
        _shot(
            "tag", g, ["morty", "rick"],
            "The portal gun coughs one pancake onto the check. Rick does not touch it. "
            "He holds a wrench out toward Morty and looks at the wrench, not the food.",
            [
                ("morty", "That's the bite."),
                ("rick", "It's a pancake. Pancakes don't mean things. Hand me the wrench."),
            ],
            seconds=14,
        ),
    ]
    scene = _assemble(
        "The Check", shots, seed=21, slug="the-check",
        premise=(
            "Rick will not pay for anything he did, including bringing Morty. "
            "A diner itemizes the cost. The way home opens only when he tears off "
            "the true line instead of paying it, and the bite he refused is still on the bench."
        ),
    )
    validate(scene)
    total = sum(s["seconds"] for s in scene["shots"])
    if total != 180:
        raise StoryError(f"The Check must be 180s, got {total}")
    return scene


def the_spot_scene():
    """Three minutes. Rick parks in the house so he never has to admit Jerry was right."""
    ship = "cramped green-lit spacecraft cockpit with two seats and a windshield, not a car"
    living = "suburban living room with a beige couch, a television, carpet, and a front door"
    kitchen = "suburban kitchen with a round table, a fridge, and a doorway to the living room"
    bed = "small teenage bedroom with one bed, posters, and a window"
    shots = [
        _shot(
            "co1", ship, ["morty", "rick"],
            "Rick is driving a small green-metal spacecraft straight at the Smith house. "
            "Morty is braced in the passenger seat, one hand on the dash.",
            [
                ("morty", "Rick, that's the house."),
                ("rick", "It's a gap. Burp. Gaps don't have mortgages."),
            ],
            seconds=12,
        ),
        _shot(
            "a1", living, ["jerry", "rick"],
            "The spacecraft is parked in the living room between the couch and the television. "
            "Jerry stands holding a remote, blocked by the hull. Rick is half out of the hatch.",
            [
                ("jerry", "The TV is behind your bumper."),
                ("rick", "Then watch the bumper."),
            ],
            seconds=14,
        ),
        _shot(
            "a2", kitchen, ["beth", "rick"],
            "Beth sits at the kitchen table and does not look up. Through the doorway the "
            "spacecraft is visible in the living room. Rick leans on the doorframe.",
            [
                ("beth", "The neighbors can see it."),
                ("rick", "Neighbors are weather."),
            ],
            seconds=12,
        ),
        _shot(
            "a3", kitchen, ["summer", "rick"],
            "Summer sits on the kitchen counter filming the spacecraft through the doorway. "
            "Rick reaches for her phone. She holds it out of reach.",
            [
                ("summer", "Somebody commented therapy."),
                ("rick", "Delete the neighbor."),
            ],
            seconds=12,
        ),
        _shot(
            "a4", living, ["morty", "rick"],
            "A huge white spacecraft hull blocks the staircase from wall to wall. "
            "Morty cannot step past the metal. Rick stands on top of the hull. No pole, no column.",
            [
                ("morty", "I can't get upstairs."),
                ("rick", "Sleep in the ship. It's deductible."),
            ],
            seconds=14,
        ),
        _shot(
            "a5", kitchen, ["jerry"],
            "Jerry stands at the open fridge holding up a milk carton like a trophy. "
            "He is delighted. The spacecraft is not in this room.",
            [
                ("jerry", "Expired. I called it Tuesday."),
            ],
            seconds=12,
        ),
        _shot(
            "a6", living, ["rick", "jerry"],
            "The huge white spacecraft fills the living room and its lights flash. Rick flinches beside it. "
            "Only Jerry, in the dark green striped shirt, stands in the kitchen doorway holding milk. "
            "No boy. No second Jerry.",
            [
                ("rick", "Stop being right."),
                ("jerry", "I didn't do it on purpose."),
            ],
            seconds=14,
        ),
        _shot(
            "a7", bed, ["morty", "rick"],
            "A metal spacecraft nose, not a person, lies across Morty's bed. The bed is empty. "
            "Morty stands at the foot of the bed. Rick stands beside the metal nose.",
            [
                ("morty", "It's on my pillow."),
                ("rick", "Pillows are soft parking. You're welcome."),
            ],
            seconds=14,
        ),
        _shot(
            "a8", bed, ["morty", "rick"],
            "Morty looks up at Rick and does not finish the sentence. Rick is already "
            "turning away inside the hatch. The bed is still under the hull.",
            [
                ("morty", "Can you just—"),
                ("rick", "No."),
            ],
            seconds=10,
        ),
        _shot(
            "a9", kitchen, ["beth", "jerry"],
            "Beth stands in the kitchen doorway. Jerry is at the table holding the milk carton "
            "up for her to admire. She is not admiring it.",
            [
                ("beth", "Put the milk down."),
                ("jerry", "The milk parked a spaceship."),
            ],
            seconds=14,
        ),
        _shot(
            "a10", living, ["summer", "rick"],
            "Summer stands in front of the parked spacecraft, phone lowered, unimpressed. "
            "Rick sits on the hull with his arms folded.",
            [
                ("summer", "We're eating cereal in a parking lot."),
                ("rick", "Cereal was already a mistake."),
            ],
            seconds=14,
        ),
        _shot(
            "a11", bed, ["morty", "rick"],
            "Rick sits on the bedroom floor because the craft will not move. Morty sits "
            "on the edge of the bed, under the hull, feet not touching the floor.",
            [
                ("morty", "You can whisper it."),
                ("rick", "Burp. I'm not sponsoring dairy."),
            ],
            seconds=12,
        ),
        _shot(
            "a12", kitchen, ["jerry", "rick"],
            "Morning. Jerry has set the milk carton on the table like a reserved sign. "
            "He is proud. Rick walks past and does not look at him.",
            [
                ("jerry", "I saved you a spot."),
                ("rick", "It's my spot. You curdled next to it."),
            ],
            seconds=14,
        ),
        _shot(
            "tag", living, ["summer", "rick"],
            "The same huge white spacecraft is parked in the living room, the biggest object there, "
            "one light flashing. Jerry in the green striped shirt waves from the kitchen doorway. "
            "Summer films the ship. Rick stands beside her and refuses to look at it.",
            [
                ("summer", "He's waving at it."),
                ("rick", "Don't wave back. It learns."),
            ],
            seconds=12,
        ),
    ]
    scene = _assemble(
        "The Spot", shots, seed=44, slug="the-spot",
        premise=(
            "Rick parks the ship in the house so he never has to wait, or admit Jerry "
            "was right about anything. The ship only answers to Jerry being right. "
            "Rick would rather sleep under it."
        ),
    )
    validate(scene)
    total = sum(s["seconds"] for s in scene["shots"])
    if total != 180:
        raise StoryError(f"The Spot must be 180s, got {total}")
    return scene


def validate(scene):
    """Raise StoryError listing every way this scene would render as a random episode."""
    problems = []
    shots = scene.get("shots") or []
    if len(shots) < 4:
        problems.append(f"only {len(shots)} shots; a story needs a cold open, a turn, a price, and a tag")
    prompts = [s.get("keyframe_prompt", "") for s in shots]
    if len(set(prompts)) != len(prompts):
        problems.append(
            f"{len(prompts) - len(set(prompts))} cloned keyframe prompts "
            "(padding a runtime by repeating a picture)"
        )
    lines = []
    for shot in shots:
        dialogue = shot.get("dialogue") or []
        present = set(shot.get("characters") or [])
        for line in dialogue:
            speaker = line.get("speaker")
            lines.append(line.get("line", ""))
            if speaker not in present:
                problems.append(
                    f"{shot.get('id')}: {speaker} speaks but is not in the shot"
                )
            if speaker and speaker not in (scene.get("characters") or {}):
                problems.append(f"{shot.get('id')}: unknown speaker {speaker}")
        if dialogue and not present:
            problems.append(f"{shot.get('id')}: dialogue with nobody in frame")
        if not shot.get("location"):
            problems.append(f"{shot.get('id')}: no location, so the renderer cannot tell shots apart")
        if not shot.get("action"):
            problems.append(f"{shot.get('id')}: no action, so the picture is only a room")
    if lines and len(set(lines)) != len(lines):
        problems.append("repeated dialogue lines")
    # A location may hold a scene. It may not be the whole episode.
    from collections import Counter
    locs = Counter(s.get("location") for s in shots)
    if shots and locs.most_common(1)[0][1] > max(4, len(shots) // 2):
        loc, n = locs.most_common(1)[0]
        problems.append(f"location {loc!r} is {n}/{len(shots)} shots; the episode is stuck in one room")
    if problems:
        shown = problems[:8]
        extra = len(problems) - len(shown)
        msg = "; ".join(shown)
        if extra:
            msg += f"; and {extra} more"
        raise StoryError(msg)
    return scene


def write_with_llm(premise, target_shots=8):
    """Ask the text model for a scene, then refuse it unless `validate` passes."""
    if not llm.available():
        raise StoryError(llm.describe())
    system = (
        "You write a short original episode in the speech rhythm of Rick and Morty. "
        "Return one JSON object only. Do not copy a plot or a line from the show. "
        "The premise punishes one flaw. The family B-plot asks the same question "
        "at the kitchen table. Every shot is a different picture. Do not repeat a "
        "line or pad the runtime by cloning a room. "
        "Each speaker must be listed in that shot's characters. "
        "Allowed characters: rick, morty, beth, jerry, summer. "
        + DIALOGUE
    )
    user = f"""Premise: {premise}

Return JSON with keys title, premise, shots.
shots is a list of {target_shots} objects, each with:
  id, location, characters (list drawn from rick, morty, beth, jerry, summer),
  action (one sentence: the picture, different from every other shot),
  dialogue (list of {{"speaker","line"}}, one line is normal, two is the maximum).
No keyframe_prompt and no motion_prompt; those are filled in afterwards.
"""
    text, _usage = llm.complete(user, system=system, json_mode=True, temperature=0.7)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise StoryError(f"model did not return JSON: {e}") from None
    shots = []
    for raw in data.get("shots") or []:
        dialogue = [(d["speaker"], d["line"]) for d in raw.get("dialogue") or []]
        shots.append(_shot(
            raw["id"], raw["location"], raw.get("characters") or [],
            raw["action"], dialogue,
        ))
    scene = _assemble(data.get("title") or "Untitled", shots)
    scene["premise"] = data.get("premise") or premise
    validate(scene)
    return scene


def _bad_episode():
    """The episode-3 failure, shrunk: one room, cloned pictures, a speaker who isn't there."""
    room = "a pretzel kiosk. the carousel, a clipboard."
    shots = []
    for i in range(6):
        shots.append({
            "id": f"s{i}",
            "location": "kiosk",
            "characters": [] if i % 2 == 0 else ["scientist"],
            "seconds": 5,
            "keyframe_prompt": room,
            "action": "",
            "dialogue": [{"speaker": "rick", "line": "It's twenty minutes."}],
            "motion_prompt": "Real movement in the frame: hands, coats, wind, machinery.",
        })
    return {
        "title": "bad",
        "characters": {"scientist": {"sheet": "sheets/rick.png"}},
        "shots": shots,
    }


def selftest():
    proof = proof_scene()
    validate(proof)
    try:
        validate(_bad_episode())
    except StoryError as e:
        bad_msg = str(e)
    else:
        raise SystemExit("validator accepted the cloned episode")
    needed = ("cloned keyframe", "speaks but is not", "no action")
    missing = [n for n in needed if n not in bad_msg]
    if missing:
        raise SystemExit(f"validator missed {missing}: {bad_msg}")
    ep3 = pathlib.Path(__file__).resolve().parent.parent / "scenes" / "episode3.json"
    if ep3.exists():
        try:
            validate(json.loads(ep3.read_text()))
        except StoryError as e:
            ep3_msg = str(e)
        else:
            raise SystemExit("validator accepted episode3.json")
        if "cloned keyframe" not in ep3_msg:
            raise SystemExit(f"episode3 failure was not the clone: {ep3_msg}")
    print("selftest ok")
    print(f"proof: {proof['title']}  {len(proof['shots'])} shots  "
          f"{sum(s['seconds'] for s in proof['shots'])}s")
    if ep3.exists():
        print(f"episode3 rejected: {ep3_msg}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Endless writers' room")
    p.add_argument("command", choices=["proof", "check", "selftest", "write", "the-check", "the-spot"])
    p.add_argument("premise", nargs="?", default="")
    p.add_argument("--out")
    p.add_argument("--shots", type=int, default=8)
    a = p.parse_args(argv)
    if a.command == "selftest":
        return selftest()
    if a.command == "check":
        path = pathlib.Path(a.premise or a.out or "")
        scene = json.loads(path.read_text())
        apply(scene)
        validate(scene)
        print(f"ok  {scene.get('title')}  {len(scene['shots'])} shots")
        return 0
    try:
        if a.command == "proof":
            scene = proof_scene()
        elif a.command == "the-check":
            scene = the_check_scene()
        elif a.command == "the-spot":
            scene = the_spot_scene()
        else:
            if not a.premise:
                raise StoryError("write needs a premise string")
            scene = write_with_llm(a.premise, a.shots)
    except StoryError as e:
        print(f"story error: {e}", file=sys.stderr)
        return 1
    text = json.dumps(scene, indent=2) + "\n"
    if a.out:
        out = pathlib.Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"wrote {out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
