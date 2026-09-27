"""Locked designs for the two leads.

The sheets used for episodes 1–3 were a generic old man in a lab coat and a
generic boy in a yellow shirt. Keyframes then copied those sheets, and one
shared clothing sentence ("yellow t-shirt, white lab coat") painted Morty's
shirt onto Rick in close-ups. These locks are the designs the sheets and the
keyframes both have to agree with. Local generation may name the characters;
cloud moderation is a different path and is not used here.
"""

STYLE_BLOCK = (
    "2D American adult animated sitcom frame, flat cel colors, thick clean "
    "black outlines, hard-edged shadow shapes, limited flat palette, no "
    "gradients, no texture, no 3D, no photorealism, cutout-style character "
    "animation, big white eyes with small black pupils."
)

CAST = {
    "rick": {
        "sheet": "sheets/rick.png",
        "voice": "raspy, contemptuous, talking too fast, with a wet burp inside the sentence",
        "lock": (
            "Rick is the tall thin older man: wild spiky light-blue hair with a "
            "bald crown and one long spit-curl on the forehead, a thick unibrow, "
            "half-closed eyelids, a string of drool, an open white lab coat over "
            "a light-blue collared shirt, brown pants, a black belt, black shoes. "
            "Not a black shirt. Not a teal collar. Not soft cloud-shaped hair."
        ),
        "sheet_prompt": (
            "Full-body front view of Rick Sanchez, centered, standing, plain flat "
            "grey background. Very tall and thin. Yellow-tan skin. Wild spiky "
            "light-blue hair: bald crown, spikes around the sides and back, one "
            "long thin spit-curl hanging onto the forehead. Thick single unibrow. "
            "Heavy half-closed eyelids, small black pupils in large white eyes. "
            "A visible string of drool from the mouth. Open white lab coat over a "
            "light-blue collared shirt, not a black shirt and not a teal V-neck. "
            "Brown trousers, black belt, black shoes. Flat cel-shaded 2D television "
            "animation, thick black outlines, no gradients."
        ),
        "negative": (
            "photorealistic, 3d, einstein, doc brown, black shirt, black turtleneck, "
            "teal trim, teal collar, soft painterly hair, brown hair, beard, glasses, "
            "text, watermark, yellow shirt"
        ),
    },
    "morty": {
        "sheet": "sheets/morty.png",
        "voice": "nervous, voice cracking, apologizing for asking",
        "lock": (
            "Morty is the short boy: oversized round head, small body, brown bowl-cut "
            "hair with a flat top and a tiny cowlick, huge circular white eyes with "
            "tiny pupils, a small nose, a worried mouth, a bright yellow short-sleeve "
            "t-shirt, blue pants, white sneakers."
        ),
        "sheet_prompt": (
            "Full-body front view of Morty Smith, centered, standing, plain flat "
            "grey background. Short teenage boy with an oversized round head and a "
            "small body. Brown hair in a flat bowl cut with a tiny cowlick. Huge "
            "circular white eyes, tiny black pupils, small nose, small worried "
            "mouth. Bright yellow short-sleeve t-shirt, blue pants, white sneakers. "
            "Flat cel-shaded 2D television animation, thick black outlines, no gradients."
        ),
        "negative": (
            "photorealistic, 3d, adult, tall, spiky hair, black hair, lab coat, "
            "text, watermark, chibi sticker, gradient shading"
        ),
    },
    "beth": {
        "sheet": "sheets/beth.png",
        "voice": "flat, tired, adult, already disappointed, does not raise her voice",
        "lock": (
            "Beth is the adult woman: shoulder-length blonde hair, tired sharp face, "
            "yellow-tan skin, a red collared shirt, blue pants, white shoes. "
            "Not a lab coat. Not a yellow shirt. Not a pink tank top."
        ),
        "sheet_prompt": (
            "Full-body front view of Beth Smith, centered, standing, plain flat grey "
            "background. Adult woman, yellow-tan skin, shoulder-length straight blonde "
            "hair, tired sharp face, small nose, large white eyes with small black "
            "pupils. Red short-sleeve collared shirt, blue pants, white shoes. "
            "Flat cel-shaded 2D television animation, thick black outlines, no gradients."
        ),
        "negative": (
            "photorealistic, 3d, lab coat, yellow shirt, pink tank top, orange hair, "
            "child, spiky blue hair, text, watermark, gradient shading"
        ),
    },
    "jerry": {
        "sheet": "sheets/jerry.png",
        "voice": "eager, nasal, trying to sound reasonable, laughs in the wrong place",
        "lock": (
            "Jerry is the average adult man: dark brown hair with a side part, "
            "clean-shaven long face, dimples, a dark green shirt with one brown-and-beige "
            "stripe across the chest, light blue pants, black shoes. "
            "Not a lab coat. Not blonde. Not a yellow shirt."
        ),
        "sheet_prompt": (
            "Full-body front view of Jerry Smith, centered, standing, plain flat grey "
            "background. Average adult man, yellow-tan skin, dark brown hair with a "
            "side part, clean-shaven long face, dimples, worried polite smile. "
            "Dark green short-sleeve shirt with a single horizontal brown and beige "
            "stripe across the chest, light blue pants, black shoes. "
            "Flat cel-shaded 2D television animation, thick black outlines, no gradients."
        ),
        "negative": (
            "photorealistic, 3d, lab coat, blonde hair, yellow shirt, spiky hair, "
            "beard, muscular, text, watermark, gradient shading"
        ),
    },
    "summer": {
        "sheet": "sheets/summer.png",
        "voice": "bored, dry, teenage, one flat sentence, not excited",
        "lock": (
            "Summer is the teenage girl: orange hair in a high ponytail, oval head, "
            "pointed nose, no long eyelashes, a magenta tank top, white capri pants, "
            "black slip-on shoes. Not a yellow shirt. Not blonde. Not a lab coat."
        ),
        "sheet_prompt": (
            "Full-body front view of Summer Smith, centered, standing, plain flat "
            "grey background. Teenage girl, yellow-tan skin, oval head, pointed nose, "
            "no long eyelashes, orange hair pulled into a high ponytail. Magenta tank "
            "top, white capri pants, black slip-on shoes. Flat cel-shaded 2D television "
            "animation, thick black outlines, no gradients."
        ),
        "negative": (
            "photorealistic, 3d, lab coat, yellow shirt, blonde hair, blue spiky hair, "
            "long eyelashes, child, text, watermark, gradient shading"
        ),
    },
}


# How the show's people actually talk. Used by the writers' room.
# The picture carries the theme. A line that could be a caption is cut.
DIALOGUE = (
    "Talk past each other. Rick does not answer the question he was asked. "
    "He burps inside the clause and ends on something short and mean. "
    "Morty says Rick's name and does not finish the brave version of the sentence. "
    "Beth is already tired and does not raise her voice. "
    "Jerry wants credit for showing up and laughs in the wrong place. "
    "Summer is on her phone and says the true thing in one flat sentence. "
    "Lines are short. Never state the theme. Never write an aphorism. "
    "One speaker per shot is enough. The other person does not have to reply."
)


def apply(scene):
    """Fill missing style and character locks. Does not invent shots."""
    scene.setdefault("style_block", STYLE_BLOCK)
    chars = scene.setdefault("characters", {})
    for key, spec in CAST.items():
        if key not in chars:
            continue
        ch = chars[key]
        for field in ("sheet", "voice", "lock", "sheet_prompt", "negative"):
            ch.setdefault(field, spec[field])
    return scene
