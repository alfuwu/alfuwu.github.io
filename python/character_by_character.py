# A character-by-character machine learning name generator.

# Output examples:
# Laxly, Costan, Hambert, Jean-Chrislik, Jarvy, Remmerso, and Sephyn

import numpy as np
from keras.models import Sequential, load_model
from keras.layers import LSTM, Dense, Embedding, Bidirectional
from nltk import download as download_nltk_model
from nltk.corpus import names
from pickle import load, dump
from os.path import exists
from os import makedirs
from random import choice

# get name corpora
try:
    MALE = names.words("male.txt")
    FEMALE = names.words("female.txt")
except Exception:
    download_nltk_model("names")
    MALE = names.words("male.txt")
    FEMALE = names.words("female.txt")

male_names = [name + "\0" for name in MALE]
female_names = [name + "\0" for name in FEMALE]

# Concatenate all names and create a character set
all_names = male_names + female_names
chars = sorted(list(set(''.join(all_names))))

# Create character to index and index to character dictionaries
char_to_index = {char: i for i, char in enumerate(chars)}
index_to_char = {i: char for i, char in enumerate(chars)}

# Create sequences for training
max_len = max([len(name) for name in all_names])
male_sequences = []
male_next_chars = []
female_sequences = []
female_next_chars = []
for name in male_names:
    for i in range(len(name) - 1):
        seq = name[:i + 1]
        male_sequences.append(seq)
        male_next_chars.append(name[i + 1])
for name in female_names:
    for i in range(len(name) - 1):
        seq = name[:i + 1]
        female_sequences.append(seq)
        female_next_chars.append(name[i + 1])

# Vectorize sequences
X_male = np.zeros((len(male_sequences), max_len, len(chars)), dtype=bool)
y_male = np.zeros((len(male_sequences), len(chars)), dtype=bool)
for i, seq in enumerate(male_sequences):
    for t, char in enumerate(seq):
        X_male[i, t, char_to_index[char]] = 1
    y_male[i, char_to_index[male_next_chars[i]]] = 1

X_female = np.zeros((len(female_sequences), max_len, len(chars)), dtype=bool)
y_female = np.zeros((len(female_sequences), len(chars)), dtype=bool)
for i, seq in enumerate(female_sequences):
    for t, char in enumerate(seq):
        X_female[i, t, char_to_index[char]] = 1
    y_female[i, char_to_index[female_next_chars[i]]] = 1

# Create and compile the LSTM model
male_model = Sequential(layers=[
    LSTM(128, input_shape=(max_len, len(chars))),
    Dense(len(chars), activation='softmax')
])

male_model.compile(loss='categorical_crossentropy', optimizer='adam')

female_model = male_model

def generate_name(gender: int = 0):
    generated = choice(male_names)[:2] # first two characters
    while len(generated) < max_len:
        x_pred = np.zeros((1, max_len, len(chars)))
        for t, char in enumerate(generated):
            x_pred[0, t, char_to_index[char]] = 1
        preds = (male_model if gender == 0 else female_model).predict(x_pred, verbose=0)[0]
        next_index = np.random.choice(len(chars), p=preds)
        next_char = index_to_char[next_index]
        if next_char == '\0': # End of name
            # lazy way to ensure that the names don't just end immediately
            if len(generated) >= choice([2, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4]): break
            else: continue
        
        generated += next_char
    return generated

def batch_generate_names(amount: int = 10, gender: int = 0) -> list:
    names = []
    for _ in range(amount):
        names.append(generate_name(gender))
    return names

while True:
    # Train the model
    male_model.fit(X_male, y_male, epochs=20, batch_size=64)

    # Generating a name
    # Note: Due to the fact that the model is only training on male names here, attempting to generate a female name will cause the model to freak out and give you gibberish
    # Some examples of gibberish names: ArJ-GGz l-YwJigw, Roue, Piick Cslz Z'CKA, Re-jXaGoLfLubMkX, HiCw-sQ vRmEdiYE, ThIB yGF, BrFwD'wDAsF-FiCv, Krr-scmpaVyVK, and ChA S'pIeYdTRIjA
    # Very gibberish indeed
    gen_names = batch_generate_names(95, 0)
    print("names:")
    for name in gen_names:
        print(" - " + name + " (" + ((name + "\x00") in male_names and "known" or "unknown") + ")")

    if input().lower() in ["s", "save", "save model", "export"]:
        if not exists(f"models/name-gen/v2/"):
            makedirs(f"models/name-gen/v2")
        with open(f"models/name-gen/v2/binary.bin", "wb") as file:
            dump(male_model, file)
        male_model.save(f"models/name-gen/v2/model.keras")
        male_model.save(f"models/name-gen/v2/model.h5")
        male_model.save(f"models/name-gen/v2/model.tf")
        male_model.save_weights(f"models/name-gen/v2/weights")
        male = gen_names + batch_generate_names(95, 0)
        with open(f"models/name-gen/v2/male.txt", "w") as file:
            file.writelines([name + "\n" for name in male])