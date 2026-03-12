from flask import Flask, render_template, request, jsonify, send_file
from instagrapi import Client
import time
import os
from datetime import datetime
import threading
import tempfile

app = Flask(__name__)

# অস্থায়ী স্টোরেজ
jobs = {}

class InstagramCookieJob:
    def __init__(self, credentials, job_id):
        self.credentials = credentials
        self.job_id = job_id
        self.results = []
        self.status = "processing"
        self.progress = 0

def process_cookies(job_id, credentials_list):
    """ব্যাকগ্রাউন্ডে কুকি জেনারেট করার ফাংশন"""
    results = []
    total = len(credentials_list)
    
    for i, cred in enumerate(credentials_list):
        try:
            if '|' not in cred:
                continue
                
            username, password = cred.split('|', 1)
            username = username.strip()
            password = password.strip()
            
            # instagrapi দিয়ে লগিন
            cl = Client()
            cl.delay_range = [1, 3]
            cl.login(username, password)
            time.sleep(2)
            
            # কুকি জেনারেট
            session_data = cl.get_session_data()
            cookie_string = f"sessionid={session_data.get('sessionid', '')}; "
            cookie_string += f"csrftoken={session_data.get('csrftoken', '')}; "
            cookie_string += f"ds_user_id={session_data.get('ds_user_id', '')}"
            
            results.append(f"{username}|{password}|{cookie_string}")
            
        except Exception as e:
            results.append(f"{username}|{password}|ERROR: {str(e)}")
        
        # প্রোগ্রেস আপডেট
        jobs[job_id]['progress'] = int((i + 1) / total * 100)
        time.sleep(3)
    
    jobs[job_id]['results'] = results
    jobs[job_id]['status'] = "completed"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit():
    data = request.json
    credentials = data.get('credentials', '').strip().split('\n')
    credentials = [c.strip() for c in credentials if c.strip()]
    
    if not credentials:
        return jsonify({'error': 'কোনো ডাটা দেওয়া হয়নি'}), 400
    
    job_id = datetime.now().strftime("%Y%m%d%H%M%S")
    jobs[job_id] = {
        'status': 'processing',
        'progress': 0,
        'results': [],
        'total': len(credentials)
    }
    
    # ব্যাকগ্রাউন্ডে প্রসেসিং শুরু
    thread = threading.Thread(target=process_cookies, args=(job_id, credentials))
    thread.start()
    
    return jsonify({'job_id': job_id})

@app.route('/api/status/<job_id>')
def status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(jobs[job_id])

@app.route('/api/download/<job_id>')
def download(job_id):
    if job_id not in jobs or jobs[job_id]['status'] != 'completed':
        return jsonify({'error': 'File not ready'}), 400
    
    results = jobs[job_id]['results']
    
    # টেম্প ফাইল তৈরি
    filename = f"cookies_{job_id}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(result + '\n')
    
    return send_file(filename, as_attachment=True, download_name=f"instagram_cookies_{job_id}.txt")

if __name__ == '__main__':
    app.run(debug=True)
