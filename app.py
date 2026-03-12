from flask import Flask, render_template, request, jsonify, send_file
import time
import os
from datetime import datetime
import threading
import json

app = Flask(__name__)

jobs = {}

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
        'status': 'completed',
        'progress': 100,
        'results': ['টেস্ট কুকি - শুধু ডেমো'],
        'total': len(credentials)
    }
    
    return jsonify({'job_id': job_id})

@app.route('/api/status/<job_id>')
def status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'জব পাওয়া যায়নি'}), 404
    return jsonify(jobs[job_id])

@app.route('/api/download/<job_id>')
def download(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'ফাইল রেডি নয়'}), 400
    
    results = jobs[job_id]['results']
    filename = f"cookies_{job_id}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(result + '\n')
    
    return send_file(filename, as_attachment=True, download_name=f"instagram_cookies_{job_id}.txt")

if __name__ == '__main__':
    app.run(debug=True)
