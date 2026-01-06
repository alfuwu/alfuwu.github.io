# Generates a name using sonority mappings.

# Output examples:
# əltɛ, reɪd, ˈɛka, and ˈsəl

import nltk
import pandas as pd
from nltk.corpus import words
from eng_to_ipa import convert
from os.path import exists
import random

try:
    # Load English words corpus
    english_words = words.words()
except Exception:
    # Download NLTK words corpus if not downloaded
    nltk.download('words')
    english_words = words.words()

# Helper function to add or strengthen the link between two sounds
def add_link(from_sound : str, to_sound : str):
    global graph_data
    # Check if the link already exists
    existing_link = graph_data[(graph_data['From'] == from_sound) & (graph_data['To'] == to_sound)]
    if existing_link.empty:
        # If the link doesn't exist, add it with initial strength 1
        graph_data = pd.concat([graph_data, pd.DataFrame({'From': [from_sound], 'To': [to_sound], 'LinkStrength': [1]})], ignore_index=True)
    else:
        # If the link exists, strengthen it by incrementing the link strength
        index = existing_link.index[0]
        graph_data.at[index, 'LinkStrength'] += 1

# Create a directed graph DataFrame
if exists('other/etc/graph_data.csv'):
    graph_data = pd.read_csv('other/etc/graph_data.csv')
else:
    graph_data = pd.DataFrame(columns=['From', 'To', 'LinkStrength'])

    # Process each word in the English words corpus
    for word in english_words:
        # Convert word to IPA
        ipa_transcription = convert(word)
        if (ipa_transcription.endswith("*")):
            continue
        # Add links between consecutive sounds
        add_link("START", ipa_transcription[0])
        add_link("END", ipa_transcription[-1])
        for i in range(len(ipa_transcription) - 1):
            add_link(ipa_transcription[i], ipa_transcription[i+1])
        print(f"Linked {word} ({ipa_transcription})")

    # Save graph data to a file
    graph_data.to_csv('other/etc/graph_data.csv', index=False)

# Function to randomly traverse the graph based on link strength
def random_traversal(start_sound : str):
    global graph_data
    current_sound = start_sound
    traversal_path = [current_sound] if start_sound != "START" else []
    for _ in range(4):
        # Get possible next sounds and their link strengths
        possible_next_sounds = graph_data[graph_data['From'] == current_sound]
        if possible_next_sounds.empty:
            # If no next sounds available, stop traversal
            break
        # Group by 'To' column and sum the 'LinkStrength' for each group
        grouped_sounds = possible_next_sounds.groupby('To')['LinkStrength'].sum()
        # Calculate probabilities based on summed link strengths
        probabilities = grouped_sounds / grouped_sounds.sum()
        # Choose next sound based on probabilities
        next_sound = random.choices(grouped_sounds.index, weights=probabilities)[0]
        if next_sound == "END":
            break
        # Add next sound to traversal path
        traversal_path.append(next_sound)
        # Move to the next sound
        current_sound = next_sound
    return traversal_path

while True:
    print("Starting random traversal")
    start_sound = 'START'
    path = random_traversal(start_sound)
    print("Random traversal path:", ''.join(path))
    input()