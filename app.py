import pennylane as qml
import numpy as np
import requests
import random
import sys
import io
import base64
from PIL import Image
import httpx
import logging
import os
import json
from datetime import datetime
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.textfield import MDTextField
from kivy.uix.image import AsyncImage
from concurrent.futures import ThreadPoolExecutor
import asyncio

with open('configopenai.json', 'r') as f:
    config = json.load(f)

openai_api_key = config['openai_api_key']
logging.basicConfig(level=logging.INFO)
num_qubits = 6
dev = qml.device('default.qubit', wires=num_qubits)

@qml.qnode(dev)
def quantum_circuit(color_code, datetime_factor):
    r, g, b = [int(color_code[i:i+2], 16) for i in (1, 3, 5)]
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    qml.RY(r * np.pi, wires=0)
    qml.RY(g * np.pi, wires=1)
    qml.RY(b * np.pi, wires=2)
    qml.RY(datetime_factor * np.pi, wires=3)
    qml.CNOT(wires=[0, 1])
    qml.CNOT(wires=[1, 2])
    qml.CNOT(wires=[2, 3])
    return qml.state()

def mixed_state_to_color_code(mixed_state):

    mixed_state = np.array(mixed_state)


    probabilities = np.abs(mixed_state)**2


    probabilities /= np.sum(probabilities)


    r_prob = probabilities[:len(probabilities)//3]
    g_prob = probabilities[len(probabilities)//3:2*len(probabilities)//3]
    b_prob = probabilities[2*len(probabilities)//3:]


    r = int(np.sum(r_prob) * 255)
    g = int(np.sum(g_prob) * 255)
    b = int(np.sum(b_prob) * 255)


    return f'#{r:02x}{g:02x}{b:02x}'


class QuantumImageApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.root = MDScreen()
        self.image_display = AsyncImage(source="")
        self.create_gui()

    def create_gui(self):
        layout = MDBoxLayout(orientation="vertical")
        self.text_box = MDTextField(hint_text="Enter your mood")
        self.checkout_time_picker = MDTextField(hint_text="Enter checkout time (YYYY-MM-DD HH:MM)")
        run_button = MDRaisedButton(text="Generate Visual", on_press=self.generate_visual)
        layout.add_widget(self.text_box)
        layout.add_widget(self.checkout_time_picker)
        layout.add_widget(run_button)
        layout.add_widget(self.image_display)
        self.root.add_widget(layout)

    def generate_visual(self, instance):
        mood_text = self.text_box.text
        checkout_time_str = self.checkout_time_picker.text
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            asyncio.run, self.process_mood_and_time(mood_text, checkout_time_str)
        )
        future.add_done_callback(self.on_visual_generated)

    def on_visual_generated(self, future):
        try:
            color_code, datetime_factor = future.result()
            quantum_state = quantum_circuit(color_code, datetime_factor)
            image_path = generate_image_from_quantum_data(quantum_state)
            if image_path:
                self.image_display.source = image_path
        except Exception as e:
            logging.error(f"Error in visual generation: {e}")

    async def process_mood_and_time(self, mood_text, checkout_time_str):
        try:
            emotion_color_map = await self.generate_emotion_color_mapping()
            datetime_factor = self.calculate_datetime_factor(checkout_time_str)
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_api_key}"},
                    json={
                        "model": "gpt-4",
                        "messages": [
                            {"role": "system", "content": "Determine the sentiment of the following text."},
                            {"role": "user", "content": mood_text}
                        ]
                    }
                )
                response.raise_for_status()
                result = response.json()
                sentiment = self.interpret_gpt4_sentiment(result)
                return emotion_color_map.get(sentiment, "#808080"), datetime_factor
        except Exception as e:
            logging.error(f"Error in mood and time processing: {e}")
            return "#808080", 1

    def calculate_datetime_factor(self, checkout_time_str):
        try:
            checkout_time = datetime.strptime(checkout_time_str, "%Y-%m-%d %H:%M")
            now = datetime.now()
            time_diff = (checkout_time - now).total_seconds()
            return max(0, 1 - time_diff / (24 * 3600))  # Normalize to a factor between 0 and 1
        except Exception as e:
            logging.error(f"Error in calculating datetime factor: {e}")
            return 1

    async def generate_emotion_color_mapping(self):
        prompt = "Create a mapping of emotions to colors based on color psychology. Include emotions like happy, sad, excited, angry, calm, and neutral."
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_api_key}"},
                    json={
                        "model": "gpt-4",
                        "messages": [{"role": "system", "content": prompt}]
                    }
                )
                response.raise_for_status()
                result = response.json()
                return self.parse_emotion_color_mapping(result)
            except Exception as e:
                logging.error(f"Error in generating emotion-color mapping: {e}")
                return {}

    def parse_emotion_color_mapping(self, gpt4_response):
        try:
            response_text = gpt4_response['choices'][0]['message']['content']
            emotion_color_map = {}
            for line in response_text.split(','):
                emotion, color = line.strip().split(':')
                emotion_color_map[emotion.strip().lower()] = color.strip()
            return emotion_color_map
        except Exception as e:
            logging.error(f"Error in parsing emotion-color mapping: {e}")
            return {}

    def interpret_gpt4_sentiment(self, gpt4_response):
        try:
            response_text = gpt4_response['choices'][0]['message']['content'].lower()
            if "positive" in response_text:
                return "happy"
            elif "negative" in response_text:
                return "sad"
            else:
                return "neutral"
        except Exception as e:
            logging.error(f"Error in interpreting sentiment: {e}")
            return "neutral"

import re
import base64
from PIL import Image
import io

def generate_image_from_quantum_data(quantum_state):
    try:
        color_code = mixed_state_to_color_code(quantum_state)
        prompt = f"Generate an image with predominant color {color_code}"
        url = 'http://127.0.0.1:7860/sdapi/v1/txt2img'
        payload = {
            "prompt": prompt,
            "steps": 121,
            "seed": random.randrange(sys.maxsize),
            "enable_hr": "false",
            "denoising_strength": "0.7",
            "cfg_scale": "7",
            "width": 966,
            "height": 1356,
            "restore_faces": "true",
        }
        response = requests.post(url, json=payload)
        response.raise_for_status()
        r = response.json()

        if 'images' in r and r['images']:

            base64_data = r['images'][0]
            image_bytes = base64.b64decode(base64_data)
            image = Image.open(io.BytesIO(image_bytes))
            image_path = f"output_{random.randint(0, 10000)}.png"
            image.save(image_path)
            return image_path
        else:
            logging.error("No images found in the response")
            return None
    except Exception as e:
        logging.error(f"Error in image generation: {e}")
        return None
    
if __name__ == "__main__":
    app = QuantumImageApp()
    app.run()
