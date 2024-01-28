import base64
import requests
import json
import sys
import os
from datetime import datetime
import numpy as np
import pennylane as qml
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.boxlayout import MDBoxLayout
from kivy.uix.image import AsyncImage
from kivy.clock import Clock
from concurrent.futures import ThreadPoolExecutor
import asyncio
import threading
import logging
import httpx

# Load configuration
with open('configopenai.json', 'r') as f:
    config = json.load(f)

openai_api_key = config['openai_api_key']
stable_url = config['stable_url']
logging.basicConfig(level=logging.INFO)

# Quantum circuit setup
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
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "BlueGray"
        self.root = MDScreen()
        self.image_display = AsyncImage(source="")
        self.create_gui()

    def create_gui(self):
        self.layout = MDBoxLayout(orientation="vertical", md_bg_color=[0, 0, 0, 1])
        self.text_box = MDTextField(hint_text="Enter your mood", hint_text_color=[1, 1, 1, 1])
        self.checkout_time_picker = MDTextField(hint_text="Enter checkout time (YYYY-MM-DD HH:MM)", hint_text_color=[1, 1, 1, 1])
        run_button = MDRaisedButton(text="Generate Visual", on_press=self.generate_visual, text_color=[1, 1, 1, 1])
        
        self.image_display = AsyncImage(source="", allow_stretch=True, keep_ratio=True)
        self.image_display.size_hint_y = None
        self.image_display.height = 0

        self.layout.add_widget(self.text_box)
        self.layout.add_widget(self.checkout_time_picker)
        self.layout.add_widget(run_button)
        self.layout.add_widget(self.image_display)
        self.root.add_widget(self.layout)

    def generate_visual(self, instance):
        mood_text = self.text_box.text
        checkout_time_str = self.checkout_time_picker.text
        future = self.executor.submit(
            self.async_process_wrapper, mood_text, checkout_time_str
        )
        future.add_done_callback(self.on_visual_generated)

    def async_process_wrapper(self, mood_text, checkout_time_str):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            self.process_mood_and_time(mood_text, checkout_time_str)
        )

    def on_visual_generated(self, future):
        result = future.result()
        Clock.schedule_once(lambda dt: self.update_ui_after_processing(result))

    def update_ui_after_processing(self, result):
        color_code, datetime_factor = result
        quantum_state = quantum_circuit(color_code, datetime_factor)
        image_path = generate_image_from_quantum_data(quantum_state)
        if image_path:
            self.update_image(image_path)
        else:
            logging.error("Image path not received")

    def update_image(self, image_path):
        if image_path and os.path.exists(image_path):
            self.image_display.source = image_path
            self.image_display.size_hint_y = 1
            self.image_display.height = 200
        else:
            self.image_display.source = ""
            self.image_display.size_hint_y = None
            self.image_display.height = 0

    async def process_mood_and_time(self, mood_text, checkout_time_str):
        emotion_color_map = await self.generate_emotion_color_mapping(mood_text)
        datetime_factor = self.calculate_datetime_factor(checkout_time_str)
        return emotion_color_map.get(mood_text, "#808080"), datetime_factor

    def calculate_datetime_factor(self, checkout_time_str):
        try:
            checkout_time = datetime.strptime(checkout_time_str, "%Y-%m-%d %H:%M")
            now = datetime.now()
            time_diff = (checkout_time - now).total_seconds()
            return max(0, 1 - time_diff / (24 * 3600)) 
        except Exception as e:
            logging.error(f"Error in calculating datetime factor: {e}")
            return 1

    async def generate_emotion_color_mapping(self, mood_text):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_api_key}"},
                json={
                    "model": "gpt-4",
                    "messages": [
                        {"role": "system", "content": "Determine the sentiment of the following text. Provide HTML color codes."},
                        {"role": "user", "content": mood_text}
                    ]
                }
            )
            response.raise_for_status()
            result = response.json()
            return self.parse_emotion_color_mapping(result)

    def parse_emotion_color_mapping(self, gpt4_response):
        response_text = gpt4_response['choices'][0]['message']['content']
        emotion_color_map = {}
        for line in response_text.split('\n'):
            if ':' in line:
                emotion, color = line.split(':', 1)
                emotion_color_map[emotion.strip().lower()] = color.strip()
        return emotion_color_map

    async def interpret_gpt4_sentiment(self, image_path):
        # Encode the image in base64
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')

        # Formulate a prompt for GPT-4 Vision to interpret the sentiment
        prompt = "What is the sentiment conveyed in this image?"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_api_key}"},
                json={
                    "model": "gpt-4-vision-preview",
                    "messages": [
                        {"role": "system", "content": "Analyze the sentiment of the following image."},
                        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}],
                        {"role": "user", "content": prompt}
                    ]
                }
            )
            response.raise_for_status()
            result = response.json()

        # Extract the sentiment from GPT-4's response
        sentiment = result['choices'][0]['message']['content'].strip().lower()
        return sentiment

def generate_image_from_quantum_data(quantum_state):
    color_code = mixed_state_to_color_code(quantum_state)
    prompt = f"Generate an image with predominant color {color_code}"
    url = stable_url
    payload = {
        "prompt": prompt,
        "steps": 121,
        "seed": random.randrange(sys.maxsize),
        "enable_hr": "false",
        "denoising_strength": "0.7",
        "cfg_scale": "7",
        "width": 666,
        "height": 456,
        "restore_faces": "true",
    }
    response = requests.post(url, json=payload)
    response.raise_for_status()
    r = response.json()

    if 'images' in r and r['images']:
        base64_data = r['images'][0]
        image_bytes = base64.b64decode(base64_data)
        image_path = f"output_{random.randint(0, 10000)}.png"
        with open(image_path, "wb") as image_file:
            image_file.write(image_bytes)
        return image_path
    else:
        return None

if __name__ == "__main__":
    app = QuantumImageApp()
    app.run()
