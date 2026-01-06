# Attempts to classify the gender of a name.

import numpy as np
from keras.preprocessing.text import Tokenizer
from keras.utils import pad_sequences
from keras.models import Sequential, load_model
from keras.layers import Embedding, Flatten, Dense
from nltk import download as download_nltk_model
from nltk.corpus import names
from os.path import isfile
from string import punctuation

# get name corpora
try:
    MALE = names.words("male.txt")
    FEMALE = names.words("female.txt")
except Exception:
    download_nltk_model("names")
    MALE = names.words("male.txt")
    FEMALE = names.words("female.txt")

# labelling
male_names = [(name.strip(), 0) for name in MALE]  # assign a value of 0 to male names
female_names = [(name.strip(), 1) for name in FEMALE]  # assign a value of 1 to female names
special_characters = [(c, 0.5) for c in punctuation] # punctuation in names is gender neutral

# combine and shuffle
all_names = male_names + female_names + special_characters
np.random.shuffle(all_names)

tokenizer = Tokenizer(char_level=True)
texts = [name[0] for name in all_names]
tokenizer.fit_on_texts(texts)

# convert list to sequence
sequences = tokenizer.texts_to_sequences(texts)

max_len = 50
refresh = input("Refresh:\n > ").lower().strip() in ["y", "yes"]
if not isfile("models/gender classification.keras") or refresh:
    padded_sequences = pad_sequences(sequences, maxlen=max_len, padding='post')

    labels = np.array([name[1] for name in all_names])

    model = Sequential(layers=[
        Embedding(len(tokenizer.word_index) + 1, 32, input_length=max_len),
        Flatten(),
        Dense(16, activation="relu"),
        Dense(1, activation="sigmoid")
    ])

    model.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])

    model.summary()

    model.fit(padded_sequences, labels, epochs=int(input("Epochs:\n > ")), batch_size=int(input("Batch Size:\n > ")), validation_split=0.2)
    model.save("models/gender classification.keras")
else:
    model = load_model("models/gender classification.keras")

def display_errors():
    failed_names = []
    seqs = tokenizer.texts_to_sequences([name[0] for name in all_names])
    padded_seqs = pad_sequences(seqs, maxlen=max_len, padding="post")

    predictions = model.predict(padded_seqs)
    for i, prediction in enumerate(predictions):
        if prediction > 0.5 and all_names[i][1] == 0 or prediction <= 0.5 and all_names[i][1] == 1:
            failed_names.append((all_names[i], prediction))
    for name in failed_names:
        print(f" {name[0][0]:>14} - prediction: {'female,' if name[1] > 0.5 else 'male,  '} confidence: {(name[1][0] if name[1] > 0.5 else 1 - name[1][0]) * 100:.15f}%")

if input("Errors:\n > ").lower().strip() in ["y", "yes"]:
    display_errors()

while True:
    name = input(" > ")
    seq = tokenizer.texts_to_sequences([name])
    print(tokenizer.sequences_to_texts(seq)) # detokenize
    padded_seq = pad_sequences(seq, maxlen=max_len, padding="post")

    prediction = model.predict(padded_seq)
    print(f"The predicted gender for '{name}' is {'female' if prediction > 0.5 else 'male'} ({(prediction[0][0] if prediction > 0.5 else 1 - prediction[0][0]) * 100}%)")