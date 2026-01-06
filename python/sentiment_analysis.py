# Tiny sentiment analysis script using a pre-trained model from Hugging Face

from os import environ
environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
from transformers import pipeline

classifier = pipeline("sentiment-analysis", model="bhadresh-savani/bert-base-go-emotion")
tokenizer_kwargs = {'padding': True, 'truncation': True, 'max_length': 128}

def analyze_emotion(text):
    result = classifier(text, **tokenizer_kwargs)[0]

    return {
        'emotion': result['label'],
        'confidence': round(result['score'] * 100, 2)
    }

if __name__ == "__main__":
    while True:
        user_input = input("Enter a message: ")
        result = analyze_emotion(user_input)
        print(f"Primary Emotion: {result['emotion']} ({result['confidence']}%)")