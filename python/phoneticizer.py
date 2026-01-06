# Attempts to convert plain English text into its respective IPA format.

from os import makedirs, system
from os.path import exists
try:
    import numpy as np
except ImportError:
    system("pip install numpy")
    import numpy as np
try:
    from keras.preprocessing.text import Tokenizer
    from keras.utils import pad_sequences#, to_categorical
    from keras.models import Sequential
    from keras.layers import Embedding, Bidirectional, GRU, TimeDistributed, Dense, Dropout
    from keras.callbacks import EarlyStopping, ModelCheckpoint
    #import keras.backend as K
except ImportError:
    system("pip install keras tensorflow")
    from keras.preprocessing.text import Tokenizer
    from keras.utils import pad_sequences
    from keras.models import Sequential
    from keras.layers import Embedding, Bidirectional, GRU, TimeDistributed, Dense, Dropout
    from keras.callbacks import EarlyStopping, ModelCheckpoint
    #import keras.backend as K
try:
    from eng_to_ipa import mode_type, cmu_to_ipa
except ImportError:
    system("pip install eng_to_ipa")
    from eng_to_ipa import mode_type, cmu_to_ipa
from pickle import load, dump
from math import ceil

def fetch_all_words(mode="sql") -> list[tuple[str, list[str]]]:
    """fetches a list of words from the database"""
    asset = mode_type(mode)
    if mode.lower() == "sql":
        asset.execute("SELECT word, phonemes FROM dictionary")
        result = asset.fetchall()
        return result
    if mode.lower() == "json":
        result = []
        for k, v in asset.items():
            result.append((k, v))
        return result

def get_all_cmu(mode="sql") -> tuple[list[str], list[list[str]]]:
    """query the SQL database for all shtiu ifdkf"""
    all_words = fetch_all_words(mode=mode)
    result = {}
    for word, phoneme in all_words:
        if word in result:
            result[word].append(phoneme)
        else:
            result[word] = [phoneme]
    return list(result.keys()), list(result.values())

def ipa_list_all(stress_marks="both", mode="sql") -> tuple[list[str], list[list[str]]]:
    """Returns a list of all the discovered IPA transcriptions for every word."""
    words, cmu = get_all_cmu(mode=mode)
    ipa = cmu_to_ipa(cmu, stress_marking=stress_marks)
    return words, ipa

def get_all(stress_marks="both", mode="sql"):
    return ipa_list_all(
        stress_marks=stress_marks,
        mode=mode
    )

def create_model():
    input_texts, output_raw_texts = get_all()
    output_texts = [i[0] for i in output_raw_texts]
    print("Created target data")

    # Initialize tokenizers for input and target
    input_tokenizer = Tokenizer(char_level=True)
    output_tokenizer = Tokenizer(char_level=True)

    # Fit the tokenizers on the texts
    input_tokenizer.fit_on_texts(input_texts)
    output_tokenizer.fit_on_texts(output_texts)
    print("Fit tokenizers")

    # Convert texts to sequences
    input_sequences = input_tokenizer.texts_to_sequences(input_texts)
    output_sequences = output_tokenizer.texts_to_sequences(output_texts)
    print("Converted texts to sequences")

    # Pad the sequences
    max_sequence_length = ceil(sum([len(seq) for seq in input_sequences + output_sequences]) / len(input_sequences + output_sequences)) + 1
    input_tokenizer.max_sequence_length = max_sequence_length
    output_tokenizer.max_sequence_length = max_sequence_length
    print("Obtained max sequence length")

    ti = []
    to = []
    for in_seq, out_seq in zip(input_sequences, output_sequences):
        if len(in_seq) <= max_sequence_length and len(out_seq) <= max_sequence_length:
            ti.append(in_seq)
            to.append(out_seq)
    input_sequences = np.full((len(ti), max_sequence_length), 0, dtype=int)
    output_sequences = np.full((len(to), max_sequence_length), 0, dtype=int)
    for i, seq in enumerate(ti):
        input_sequences[i, :len(seq)] = seq
    for i, seq in enumerate(to):
        output_sequences[i, :len(seq)] = seq

    input_sequences = pad_sequences(input_sequences, maxlen=max_sequence_length, padding='post')
    output_sequences = pad_sequences(output_sequences, maxlen=max_sequence_length, padding='post')
    print("Padded sequences")

    # Convert target sequences to categorical
    #num_decoder_tokens = len(output_tokenizer.word_index) + 1
    #output_data = np.array([to_categorical(seq, num_classes=num_decoder_tokens) for seq in output_sequences])

    print("Creating model...")
    # Build the model
    model = Sequential([
        Embedding(len(input_tokenizer.word_index) + 1, 64, input_length=max_sequence_length),
        Dropout(0.2),
        Bidirectional(GRU(2048, return_sequences=True)),
        Bidirectional(GRU(512, return_sequences=True)),
        #Dense(128),
        TimeDistributed(Dense(len(output_tokenizer.word_index) + 1, activation="softmax"))
    ])

    # Compile the model
    model.compile(optimizer='adam', loss='sparse_categorical_crossentropy', metrics=['accuracy'])

    # Print the model summary
    model.summary()

    # Early stopping to prevent overfitting
    early_stopping = EarlyStopping(monitor='val_loss', patience=3, restore_best_weights=True)

    output_sequences = np.expand_dims(output_sequences, -1)

    # Check the shape of the data
    print("Shape of input_sequences:", input_sequences.shape)
    print("Shape of output_sequences:", output_sequences.shape)
    model.fit(input_sequences, output_sequences, epochs=10, batch_size=64, validation_split=0.2, callbacks=[early_stopping])
    return model, input_tokenizer, output_tokenizer

if exists("models/phoneticizer/model.keras") and exists("models/phoneticizer/input_tokenizer.bin") and exists("models/phoneticizer/output_tokenizer.bin"):
    with open("models/phoneticizer/model.keras", "rb") as f:
        model = load(f)
    with open("models/phoneticizer/input_tokenizer.bin", "rb") as f:
        input_tokenizer = load(f)
    with open("models/phoneticizer/output_tokenizer.bin", "rb") as f:
        output_tokenizer = load(f)
else:
    model, input_tokenizer, output_tokenizer = create_model()

max_sequence_length = input_tokenizer.max_sequence_length

# Preprocess the input text
def preprocess_input(text):
    input_seq = input_tokenizer.texts_to_sequences([text])
    input_seq = pad_sequences(input_seq, maxlen=max_sequence_length, padding='post')
    return input_seq

# Interactive input
while True:
    input_text = input("Enter text to phoneticize (or 'quit' to exit): ")
    if input_text.lower() == 'quit':
        break

    input_seq = preprocess_input(input_text)
    predicted_sequence = model.predict(input_seq)
    predicted_tokens = np.argmax(predicted_sequence, axis=-1)
    print("Tokens:", predicted_tokens)
    ipa_transcription = ""
    for token in predicted_tokens[0]:
        ipa_transcription += output_tokenizer.index_word.get(token, f"[unk: {token}]" if token != 0 else "")
    print(f"IPA Transcription: {ipa_transcription.strip()}")

makedirs("models/phoneticizer", exist_ok=True)
model.save("models/phoneticizer/model.keras")
with open("models/phoneticizer/input_tokenizer.bin", "wb") as f:
    dump(input_tokenizer, f)
with open("models/phoneticizer/output_tokenizer.bin", "wb") as f:
    dump(output_tokenizer, f)