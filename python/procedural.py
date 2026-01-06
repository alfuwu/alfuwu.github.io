# Generates names procedurally by following a list of rules.

# Output examples:
# Gruesius, Kuwon, Kaejuil, Yael, and Jous

import random
import re

# List of consonants, vowels, and optional affixes
consonants = "bcdfghjklmnpqrstvwxyz"
vowels = "aeiou"

# Allowed consonant clusters to make smoother transitions (e.g., "st", "th", "ch")
consonant_clusters = ["st", "th", "ch", "sh", "ph", "tr", "dr", "cl", "br", "cr", "gr", "fr", "bl", "gl"]

only_one = ["w", "x"]

# Common English-like syllables
common_syllables = ["ar", "el", "an", "en", "er", "or", "al", "in", "on", "ir", "il", "us", "is"]

prefixes = ["Ex", "Al", "Gr", "Ze", "Ka", "Th", "Ari", "Fi", "Val", "For", "Gal", "Gil"]
suffixes = ["dor", "mir", "mar", "ros", "gon", "thas", "lore", "car", "dran", "din", "dain", "or"]

syllable_structures = [
    "CVC",
    "VC",
    "CV",
    "VCV",
    "CCV",
]

def random_consonant(name: str):
    c = random.choice(consonants)
    while (c in only_one and c in name):
        c = random.choice(consonants)
    return c

def random_vowel(last_vowel: str):
    v = random.choice(vowels)
    if (v == last_vowel):
        v = random_vowel(last_vowel)
    return v

def random_consonant_cluster():
    return random.choice(consonant_clusters)

def random_common_syllable():
    return random.choice(common_syllables)

def generate_syllable(structure, current_name):
    """Generate a syllable based on a given structure, using more natural combinations."""
    syllable = ""
    for char in structure:
        if char == "C":
            syllable += random_consonant(current_name + syllable)
        elif char == "V":
            syllable += random_vowel(current_name[:-1] if len(syllable) <= 0 else syllable[:-1])
        elif char == "CC":
            syllable += random_consonant_cluster()
    return syllable

def generate_name():
    """Generate a name by combining random syllables and optional affixes."""
    name = ""

    # Add an optional prefix with a probability of 0.4
    if random.random() < 0.4:
        name += random.choice(prefixes)

    num_syllables = random.randint(1, 2) if random.random() > 0.9 else 1
    for _ in range(num_syllables):
        structure = random.choice(syllable_structures)
        name += generate_syllable(structure, name)

    # Add a common syllable to ensure English-like patterns
    name += random_common_syllable()

    # Add an optional suffix with a probability of 0.4
    if random.random() < 0.03:
        name += random.choice(suffixes)

    return post_process_name(name).capitalize()

def post_process_name(name):
    """Post-process the name to remove awkward consonant or vowel clusters."""
    # Remove awkward 3 or more consonants in a row
    name = re.sub(r"[^aeiou]{3,}", lambda match: match.group(0)[:2], name)

    # Remove awkward 3 or more vowels in a row
    name = re.sub(r"[aeiou]{3,}", lambda match: match.group(0)[:2], name)

    return name

# Generate a list of random names
for _ in range(10):
    print(generate_name())