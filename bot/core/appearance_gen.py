import random
from typing import Optional, List, Any

HAIR_COLORS = [
    ["aqua hair", 5], ["black hair", 8], ["blonde hair", 8], ["blue hair", 6],
    ["light blue hair", 5], ["dark blue hair", 4], ["brown hair", 8],
    ["light brown hair", 5], ["green hair", 5], ["dark green hair", 3],
    ["light green hair", 4], ["grey hair", 5], ["orange hair", 5],
    ["pink hair", 7], ["purple hair", 6], ["light purple hair", 4],
    ["red hair", 6], ["white hair", 6],
]

HAIR_MULTI_COLORS = [
    ["multicolored hair", 5], ["colored inner hair", 5], ["gradient hair", 5],
    ["rainbow hair", 3], ["split-color hair", 2], ["streaked hair", 5],
    ["two-tone hair", 5],
]

HAIR_LENGTHS = [
    ["very short hair", 5], ["short hair", 8], ["medium hair", 8],
    ["long hair", 8], ["very long hair", 3], ["absurdly long hair", 2],
    ["big hair", 4],
]

HAIR_STYLES = [
    ["drill hair", 5], ["twin drills", 5], ["hair flaps", 5],
    ["messy hair", 6], ["pointy hair", 4], ["ringlets", 5],
    ["spiked hair", 4], ["straight hair", 7], ["wavy hair", 7],
    ["blunt ends", 5], ["flipped hair", 5], ["curly hair", 6],
]

BRAID_STYLES = [
    ["braid", 5], ["braided bangs", 5], ["front braid", 4], ["side braid", 4],
    ["french braid", 5], ["crown braid", 4], ["single braid", 5],
    ["multiple braids", 4], ["braided ponytail", 5], ["hair bun", 6],
    ["braided bun", 4], ["single hair bun", 5], ["double bun", 5],
    ["hair rings", 4], ["half updo", 5], ["one side up", 5],
    ["two side up", 5], ["ponytail", 7], ["high ponytail", 5],
    ["short ponytail", 4], ["side ponytail", 5], ["twintails", 7],
    ["low twintails", 5], ["short twintails", 5], ["hime cut", 5],
]

BANGS_STYLES = [
    ["arched bangs", 4], ["asymmetrical bangs", 4], ["blunt bangs", 6],
    ["crossed bangs", 3], ["dyed bangs", 4], ["hair over eyes", 4],
    ["hair over one eye", 5], ["long bangs", 5], ["parted bangs", 6],
    ["short bangs", 5], ["swept bangs", 5], ["hair between eyes", 5],
    ["sidelocks", 5], ["ahoge", 6], ["antenna hair", 4], ["cowlick", 4],
]

HAIR_ACCESSORIES = [
    ["hair ribbon", 6], ["hair bow", 6], ["hairband", 5],
    ["headband", 5], ["headdress", 4], ["veil", 3], ["hair scrunchie", 5],
    ["hairclip", 5], ["hairpin", 5],
]

EYE_COLORS = [
    ["aqua eyes", 5], ["black eyes", 5], ["blue eyes", 8], ["brown eyes", 7],
    ["green eyes", 6], ["grey eyes", 6], ["orange eyes", 4], ["purple eyes", 6],
    ["pink eyes", 5], ["red eyes", 6], ["white eyes", 3], ["yellow eyes", 5],
    ["amber eyes", 5],
]

EYE_STYLES = [
    ["heterochromia", 5], ["multicolored eyes", 5], ["ringed eyes", 4],
    ["heart-shaped pupils", 4], ["star-shaped pupils", 4], ["glowing eyes", 5],
    ["sparkling eyes", 6], ["bright pupils", 4],
]

EYE_EXPRESSIONS = [
    ["jitome", 5], ["tareme", 6], ["tsurime", 5], ["sanpaku", 4],
    ["long eyelashes", 6], ["empty eyes", 4], ["half-closed eyes", 5],
]

SKIN_COLORS = [
    ["dark skin", 10], ["very dark skin", 8], ["pale skin", 12], ["tan", 5],
    ["blue skin", 3], ["green skin", 3], ["grey skin", 3], ["pink skin", 3],
    ["purple skin", 3],
]

ANIMAL_FEATURES = [
    ["cat ears, cat tail", 10], ["fox ears, fox tail", 10], ["dog ears, dog tail", 8],
    ["rabbit ears", 8], ["wolf ears, wolf tail", 7], ["horse ears, horse tail", 5],
    ["dragon horns, dragon tail", 7], ["demon horns, demon tail", 7],
    ["elf, pointy ears", 9], ["elf, long pointy ears", 7],
    ["dark elf, pointy ears", 6], ["oni, oni horns", 7],
    ["angel", 6], ["fairy", 5], ["tiger ears, tiger tail", 6],
    ["bear ears", 6], ["cow ears, cow horns, cow tail", 5],
    ["sheep ears, sheep horns", 5], ["raccoon ears, raccoon tail", 5],
    ["squirrel ears, squirrel tail", 5],
]

BODY_FEATURES = [
    ["forehead", 4], ["collarbone", 5], ["neck", 5], ["narrow waist", 5],
    ["wide hips", 5], ["thighs", 5], ["thick thighs", 5], ["thick eyebrows", 4],
    ["stomach", 4], ["plump", 4], ["scar", 3], ["petite", 5], ["muscular", 4],
    ["mature", 6], ["mole under eye", 5], ["mole under mouth", 5], ["mole", 4],
    ["freckles", 5], ["curvy", 5], ["abs", 4], ["toned", 4], ["skinny", 5], ["tall", 5],
]

BREAST_SIZES = [
    ["flat chest", 5], ["small breasts", 10], ["medium breasts", 10],
    ["large breasts", 6], ["huge breasts", 3],
]

FACIAL_EXPRESSIONS = [
    ["smile", 8], ["light smile", 6], ["smug", 5], ["smirk", 4],
    ["serious", 6], ["expressionless", 5], ["happy", 7], ["shy", 5],
    ["blush", 6], ["light blush", 5], ["pout", 5], ["grin", 5],
    ["frown", 4], ["embarrassed", 5], ["laughing", 4], ["closed eyes", 4],
    ["half-closed eyes", 5], ["seductive smile", 4], ["sleepy", 4],
    ["angry", 4], ["surprised", 4], ["nervous", 4], ["parted lips", 5],
    ["tongue out", 4], ["tears", 3], ["wide-eyed", 4],
]


def _weighted_choice(options: List[List]) -> Any:
    total = sum(opt[1] for opt in options)
    r = random.randint(1, total)
    cumulative = 0
    for opt in options:
        cumulative += opt[1]
        if r <= cumulative:
            return opt[0]
    return options[-1][0]


def _finalize(tags: List[str]) -> str:
    seen: set = set()
    result = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return ", ".join(result)


def generate_appearance(
    gender: str = "f",
    include_animal: bool = True,
    only_face: bool = False,
    seed: Optional[int] = None,
) -> str:
    if seed is not None:
        random.seed(seed)

    tags: List[str] = []

    if include_animal and random.random() < 0.10:
        tags.append(_weighted_choice(ANIMAL_FEATURES))

    if random.random() < 0.40:
        tags.append(_weighted_choice(SKIN_COLORS))

    if random.random() < 0.80:
        tags.append(_weighted_choice(EYE_COLORS))

    if random.random() < 0.15:
        tags.append(_weighted_choice(EYE_STYLES))

    if random.random() < 0.25:
        tags.append(_weighted_choice(EYE_EXPRESSIONS))

    if random.random() < 0.80:
        tags.append(_weighted_choice(HAIR_LENGTHS))

    if random.random() < 0.70:
        tags.append(_weighted_choice(HAIR_COLORS))

    if random.random() < 0.10:
        tags.append(_weighted_choice(HAIR_MULTI_COLORS))
        if random.random() < 0.70:
            tags.append(_weighted_choice(HAIR_COLORS))

    if random.random() < 0.50:
        tags.append(_weighted_choice(BRAID_STYLES))

    if random.random() < 0.15:
        tags.append(_weighted_choice(HAIR_STYLES))

    if random.random() < 0.25:
        tags.append(_weighted_choice(BANGS_STYLES))

    if random.random() < 0.25:
        tags.append(_weighted_choice(HAIR_ACCESSORIES))

    if only_face:
        return _finalize(tags)

    if gender == "f" and random.random() < 0.50:
        tags.append(_weighted_choice(BREAST_SIZES))

    body_count_options = [[0, 20], [1, 50], [2, 25], [3, 5]]
    n_body = _weighted_choice(body_count_options)
    for _ in range(n_body):
        tags.append(_weighted_choice(BODY_FEATURES))

    if random.random() < 0.60:
        tags.append(_weighted_choice(FACIAL_EXPRESSIONS))

    return _finalize(tags)
