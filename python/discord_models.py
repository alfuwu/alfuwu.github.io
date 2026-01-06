# Various models created using a locally downloaded Discord server as its dataset.
# Discord servers can be downloaded locally using the Discord Eternalizer utility program.

# Models include message content embeddings, channel classification, author fingerprinting,
# reaction prediction, temporal activity forecasting (broken), and message clustering (broken).

import os
import json
import numpy as np
import pandas as pd
os.environ["CUDNN_PATH"] = "/usr/local/cuda/bin"
os.environ["LD_LIBRARY_PATH"] = "/usr/local/cuda/lib64"
import tensorflow as tf
from tensorflow.python.util.tf_export import keras_export
#from tensorflow import keras
#from tensorflow.keras import layers
#from tensorflow.keras.models import Sequential
from keras import layers
from keras.models import Sequential, load_model
from keras.callbacks import EarlyStopping, Callback

@keras_export("keras.callbacks.UserStop")
class UserStop(Callback):
    def __init__(self):
        super().__init__()

    def on_epoch_end(self, epoch, logs=None):
        if input(" Stop training? (y/N) ").lower() == 'y':
            self.model.stop_training = True

if os.name == "nt":
    BASE_DIR = r"D:/Data/Archives/Hyleus/New Hyleus/2025-08-29 15։53։06"
    OUTPUT_DIR = "models/discord"
else: # wsl directory
    BASE_DIR = "/mnt/d/Data/Archives/Hyleus/New Hyleus/2025-08-29 15։53։06"
    OUTPUT_DIR = "/mnt/d/Projects/Python/models/discord"

IGNORE_FILES = {
    "Server Channels.json",
    "Server Emojis.json",
    "Server Info.json",
    "Server Roles.json",
    "Server Users.json",
    "Category Info.json"
}

def load_json_messages(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []

def load_users(base_dir: str):
    user_file = os.path.join(base_dir, "Server Users.json")
    lookup = {}
    if os.path.exists(user_file):
        try:
            with open(user_file, "r", encoding="utf-8") as f:
                users = json.load(f)
            for uid, u in users.items():
                name = u.get("display_name") or u.get("username") or u.get("name") or str(uid)
                if uid is not None:
                    lookup[int(uid)] = name
        except Exception:
            pass

    return lookup

def collect_all_messages(base_dir: str):
    all_messages = []
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file in IGNORE_FILES or not file.endswith('.json'):
                continue
            path = os.path.join(root, file)
            msgs = load_json_messages(path)
            if msgs:
                for m in msgs:
                    # attach source filename for diagnostics
                    m['_source_file'] = file
                all_messages.extend(msgs)
            print(f"read {file}")
    return all_messages

lookalikes = {
    # correlate alt accounts to their main accounts here, if any alt accounts are present in the dataset
}

data = collect_all_messages(BASE_DIR)
users = load_users(BASE_DIR)
df = pd.DataFrame(data)
df["author"] = df["author"].replace(lookalikes)

# count messages per author
author_counts = df["author"].value_counts()

# keep only authors with at least 100 messages
valid_authors = author_counts[author_counts >= 100].index

# filter the dataframe
df = df[df["author"].isin(valid_authors)].reset_index(drop=True)

max_tokens = 20000
sequence_length = 256

vectorizer = layers.TextVectorization(
    standardize=None,
    max_tokens=max_tokens,
    output_mode="int",
    output_sequence_length=sequence_length
)

vectorizer.adapt(df["clean_content"].astype(str))

def message_content_embedding_model():
    embedding_model = Sequential([
        vectorizer,
        layers.Embedding(max_tokens, 128),
        layers.Bidirectional(layers.LSTM(64)),
        layers.Dense(128, activation="relu")
    ])

    embeddings = embedding_model.predict(df["clean_content"].astype(str).fillna("").to_numpy())
    return embeddings, embedding_model

def channel_classification_model(epochs=5, batch_size=32):
    channel_ids = df["channel"].astype("category").cat.codes
    num_channels = channel_ids.nunique()

    model = Sequential([
        vectorizer,
        layers.Embedding(max_tokens, 128),
        layers.GlobalAveragePooling1D(),
        layers.Dense(128, activation="relu"),
        layers.Dense(num_channels, activation="softmax")
    ])

    model.compile(
        optimizer="adam",
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"]
    )

    model.fit(
        df["clean_content"].astype(str).fillna("").to_numpy(),
        channel_ids,
        epochs=epochs,
        batch_size=batch_size,
        validation_split=0.1,
        callbacks=[
            EarlyStopping(
                monitor="val_loss",
                patience=5,
                restore_best_weights=True
            )
        ]
    )

    return model

def author_fingerprinting_model(size=1.0, epochs=5, batch_size=32):
    df["author_code"] = df["author"].astype("category").cat.codes
    num_authors = df["author_code"].nunique()
    print("Unique authors:", num_authors)

    model = Sequential([
        vectorizer,

        layers.Embedding(
            input_dim=max_tokens,
            output_dim=int(256 * size),
            mask_zero=False
        ),
        #layers.Embedding(max_tokens, int(256 * size)),
        layers.Bidirectional(layers.LSTM(int(64 * size))),
        layers.Dense(int(512 * size), activation="relu"),
        layers.Dropout(0.5),
        layers.Dense(int(256 * size), activation="relu"),
        layers.Dropout(0.4),
        layers.Dense(num_authors, activation="softmax")
    ])

    model.compile(
        optimizer="adam",
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"]
    )

    model.fit(
        df["clean_content"].astype(str).fillna("").to_numpy(),
        df["author_code"],
        epochs=epochs,
        batch_size=batch_size,
        validation_split=0.1,
        callbacks=[
            EarlyStopping(
                monitor="val_loss",
                patience=5,
                restore_best_weights=True
            ),
            #UserStop()
        ]
    )

    return model

def reaction_prediction_model(epochs=5, batch_size=32):
    df["reaction_count"] = df["reactions"].apply(lambda r: len(r) if isinstance(r, list) else 0)
    df["has_reaction"] = (df["reaction_count"] > 0).astype(int)

    model = Sequential([
        vectorizer,
        layers.Embedding(max_tokens, 128),
        layers.GlobalMaxPooling1D(),
        layers.Dense(64, activation="relu"),
        layers.Dense(1, activation="sigmoid")
    ])

    model.compile(
        optimizer="adam",
        loss="binary_crossentropy",
        metrics=["accuracy"]
    )

    model.fit(
        df["clean_content"].astype(str).fillna("").to_numpy(),
        df["has_reaction"],
        epochs=epochs,
        batch_size=batch_size
    )

    return model

def temporal_activity_forecast(epochs=20, batch_size=32):
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["hour"] = df["created_at"].dt.hour
    df["dayofweek"] = df["created_at"].dt.dayofweek

    X = df[["hour", "dayofweek"]].values.astype("float32")
    y = np.ones(len(X))

    model = Sequential([
        layers.Dense(32, activation="relu", input_shape=(2,)),
        layers.Dense(32, activation="relu"),
        layers.Dense(1)
    ])

    model.compile(
        optimizer="adam",
        loss="mse"
    )

    model.fit(X, y, epochs=epochs, batch_size=batch_size)
    return model

def message_clustering(epochs=10, batch_size=32):
    encoder = Sequential([
        layers.Embedding(max_tokens, 128, mask_zero=True),
        layers.LSTM(128),
        layers.Dense(64, activation="relu")
    ])

    decoder = Sequential([
        layers.RepeatVector(sequence_length),
        layers.LSTM(128, return_sequences=True),
        layers.Dense(max_tokens, activation="softmax")
    ])

    autoencoder = Sequential([encoder, decoder])
    autoencoder.compile(
        optimizer="adam",
        loss="sparse_categorical_crossentropy"
    )

    # Vectorize ONCE, outside the model
    X_text = df["clean_content"].astype(str).fillna("").to_numpy()
    X_tokens = vectorizer(X_text)

    autoencoder.fit(
        X_tokens,
        X_tokens,
        epochs=epochs,
        batch_size=batch_size
    )

    return autoencoder

if __name__ == "__main__":
    inp = input("Select model to train (1-6):\n"
                "1. Message Content Embedding\n"
                "2. Channel Classification\n"
                "3. Author Fingerprinting\n"
                "4. Reaction Prediction\n"
                "5. Temporal Activity Forecast\n"
                "6. Message Clustering\n"
                " > ")
    model = None
    try:
        if inp == "1":
            embeddings, model = message_content_embedding_model()

            print("Sample Embedding for first message:")
            print(embeddings[0])
        elif inp == "2":
            model = channel_classification_model()

            while True:
                test_msg = input("Enter message to classify channel (or 'exit' to quit): ")
                if test_msg.lower() == 'exit':
                    break
                predictions = model.predict(tf.constant([test_msg]))
                predicted_channel_id = np.argmax(predictions, axis=1)[0]
                channel_code = df["channel"].astype("category").cat.categories[predicted_channel_id]
                print(f"Predicted Channel ID: {channel_code}")
        elif inp == "3":
            model = author_fingerprinting_model(size=1, epochs=5, batch_size=32)

            while True:
                test_msg = input("Enter message to identify author (or 'exit' to quit): ")
                if test_msg.lower() == 'exit':
                    break
                predictions = model.predict(tf.constant([test_msg]))
                predicted_author_id = np.argmax(predictions, axis=1)[0]
                author_code = df["author"].astype("category").cat.categories[predicted_author_id]
                user = users.get(author_code, "Unknown User")
                print(f"Predicted Author: {user} ({author_code} - {predicted_author_id})")
            exit()
        elif inp == "4":
            model = reaction_prediction_model()

            while True:
                test_msg = input("Enter message to predict reaction (or 'exit' to quit): ")
                if test_msg.lower() == 'exit':
                    break
                prediction = model.predict(tf.constant([test_msg]))
                reaction_prob = prediction[0][0]
                print(f"Predicted Reaction Probability: {reaction_prob:.4f}")
        elif inp == "5":
            model = temporal_activity_forecast()

            while True:
                hour = int(input("Enter hour of day (0-23): "))
                dayofweek = int(input("Enter day of week (0=Monday, 6=Sunday): "))
                test_vector = np.array([[hour, dayofweek]], dtype="float32")
                prediction = model.predict(test_vector)
                activity_level = prediction[0][0]
                print(f"Predicted Activity Level: {activity_level:.4f}")
        elif inp == "6":
            model = message_clustering()

            while True:
                test_msg = input("Enter message to encode/decode (or 'exit' to quit): ")
                if test_msg.lower() == 'exit':
                    break
                encoded = model.layers[0].predict(tf.constant([test_msg]))
                decoded = model.layers[1].predict(encoded)
                decoded_msg = tf.argmax(decoded, axis=-1).numpy()[0]
                decoded_text = vectorizer.get_vocabulary()
                reconstructed_msg = " ".join([decoded_text[i] for i in decoded_msg if i < len(decoded_text)])
                print(f"Reconstructed Message: {reconstructed_msg}")
    except BaseException as e:
        from traceback import print_exception
        print(f"An error occurred during model training or inference ({type(e)}):")
        print_exception(type(e), e, e.__traceback__)
    
    if model != None:
        print("Model training complete.")
        model.save(f"{OUTPUT_DIR}/discord{inp}.keras")
    else:
        print("Invalid input. Exiting...")