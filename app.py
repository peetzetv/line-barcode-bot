import os
import re
import hashlib
import hmac
import base64
import tempfile
import threading
import requests
from PIL import Image
from pyzbar.pyzbar import decode as pyzbar_decode
import pytesseract
from flask import Flask, request, abort, jsonify

app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = 'zeCZtd+RVUewEwnasgAK+X+KKg1W71S+aGhIm2KUZl/hA3qTrKijATBkgztocG30LG9eBYXhKmGhS+zfgRvISin6SHaOlrgsCVxKNhLiz5RfrZjUo7oE/6jvCFaudG5yHKInQjvRaVrItp/JLM/GCwdB04t89/1O/w1cDnyilFU='
CHANNEL_SECRET = '7bff53db505373bb984d50f2538143f9'
DESTINATION_USER_ID = 'U09bc8083418b9ef24efd93aa09058337'


def verify_signature(body, signature):
    hash = hmac.new(
        CHANNEL_SECRET.encode('utf-8'),
        body.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(hash).decode('utf-8') == signature


def download_image(message_id):
    url = f'https://api-data.line.me/v2/bot/message/{message_id}/content'
    headers = {'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}'}
    resp = requests.get(url, headers=headers)
    content_type = resp.headers.get('Content-Type', '')
    print(f'Content-Type: {content_type}, Size: {len(resp.content)} bytes')
    ext = '.png'
    if 'jpeg' in content_type or 'jpg' in content_type:
        ext = '.jpg'
    fd, path = tempfile.mkstemp(suffix=ext, dir='/tmp')
    with os.fdopen(fd, 'wb') as f:
        f.write(resp.content)
    print(f'Saved to: {path}')
    return path


def decode_barcode(image_path):
    img = Image.open(image_path)
    print(f'Image size: {img.size}')
    results = []

    decoded_objects = pyzbar_decode(img)
    print(f'pyzbar original: {len(decoded_objects)} objects')
    for obj in decoded_objects:
        print(f'  Type: {obj.type}, Data: {obj.data.decode("utf-8")}')
        results.append({'data': obj.data.decode('utf-8'), 'type': obj.type})

    if not results:
        gray = img.convert('L')
        decoded_objects = pyzbar_decode(gray)
        print(f'pyzbar grayscale: {len(decoded_objects)} objects')
        for obj in decoded_objects:
            print(f'  Type: {obj.type}, Data: {obj.data.decode("utf-8")}')
            results.append({'data': obj.data.decode('utf-8'), 'type': obj.type})

    if not results:
        for thresh in [100, 128, 160, 200]:
            gray = img.convert('L')
            threshold = gray.point(lambda p, t=thresh: 255 if p > t else 0)
            decoded_objects = pyzbar_decode(threshold)
            if decoded_objects:
                print(f'pyzbar threshold {thresh}: {len(decoded_objects)} objects')
                for obj in decoded_objects:
                    print(f'  Type: {obj.type}, Data: {obj.data.decode("utf-8")}')
                    results.append({'data': obj.data.decode('utf-8'), 'type': obj.type})
                break

    if not results:
        for scale in [2, 3]:
            gray = img.convert('L')
            resized = gray.resize((gray.width * scale, gray.height * scale), Image.LANCZOS)
            decoded_objects = pyzbar_decode(resized)
            if decoded_objects:
                print(f'pyzbar scale {scale}x: {len(decoded_objects)} objects')
                for obj in decoded_objects:
                    print(f'  Type: {obj.type}, Data: {obj.data.decode("utf-8")}')
                    results.append({'data': obj.data.decode('utf-8'), 'type': obj.type})
                break

    if not results:
        for angle in [90, 180, 270]:
            rotated = img.rotate(angle, expand=True)
            decoded_objects = pyzbar_decode(rotated)
            if decoded_objects:
                print(f'pyzbar rotate {angle}: {len(decoded_objects)} objects')
                for obj in decoded_objects:
                    print(f'  Type: {obj.type}, Data: {obj.data.decode("utf-8")}')
                    results.append({'data': obj.data.decode('utf-8'), 'type': obj.type})
                break

    if results:
        return [results[0]]

    print('No barcode found, trying OCR...')
    try:
        gray = img.convert('L')
        w, h = gray.size
        if w < 800:
            scale = 800 // w + 1
            gray = gray.resize((w * scale, h * scale), Image.LANCZOS)

        for thresh_val in [100, 128, 160]:
            threshold = gray.point(lambda p, t=thresh_val: 255 if p > t else 0)
            for psm in [7, 8, 6]:
                try:
                    text = pytesseract.image_to_string(threshold, config=f'--psm {psm}')
                    clean = re.sub(r'[^A-Za-z0-9]', '', text)
                    print(f'OCR thresh={thresh_val} psm={psm}: [{clean}]')

                    match = re.search(r'[A-Z]{2}\d{9}[A-Z]{2}', clean)
                    if match:
                        print(f'OCR EMS: {match.group(0)}')
                        return [{'data': match.group(0), 'type': 'OCR'}]

                    match = re.search(r'[A-Z]{1,4}\d{8,15}', clean)
                    if match:
                        print(f'OCR tracking: {match.group(0)}')
                        return [{'data': match.group(0), 'type': 'OCR'}]

                    match = re.search(r'\d{12,20}', clean)
                    if match:
                        print(f'OCR number: {match.group(0)}')
                        return [{'data': match.group(0), 'type': 'OCR'}]

                except Exception as e:
                    print(f'OCR error: {e}')

    except Exception as e:
        print(f'OCR error: {e}')

    return results


def reply_message(token, text):
    url = 'https://api.line.me/v2/bot/message/reply'
    headers = {
        'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'replyToken': token,
        'messages': [{'type': 'text', 'text': text}]
    }
    requests.post(url, headers=headers, json=payload)


def push_message(user_id, text):
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'to': user_id,
        'messages': [{'type': 'text', 'text': text}]
    }
    requests.post(url, headers=headers, json=payload)


@app.route("/callback", methods=['GET', 'POST'])
def callback():
    body = request.get_data(as_text=True)
    signature = request.headers.get('X-Line-Signature', '')

    if not verify_signature(body, signature):
        abort(400)

    events = request.get_json().get('events', [])
    print(f'Events received: {len(events)}')

    for event in events:
        if event['type'] == 'message' and event['message']['type'] == 'image':
            message_id = event['message']['id']
            reply_token = event['replyToken']
            t = threading.Thread(target=process_image, args=(message_id, reply_token))
            t.start()

    return 'OK'


def process_image(message_id, reply_token):
    try:
        reply_message(reply_token, 'กำลังประมวลผล...')
        image_path = download_image(message_id)
        results = decode_barcode(image_path)

        print(f'Decode results: {results}')

        if results:
            result_text = results[0]['data']
        else:
            result_text = 'ไม่พบรหัส Barcode หรือ QR Code ในรูป'

        push_message(DESTINATION_USER_ID, result_text)
    except Exception as e:
        print(f'Error: {e}')


@app.route("/", methods=['GET'])
def home():
    return 'Barcode Reader Bot is running!'


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port)
