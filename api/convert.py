from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
import requests
import time
from urllib.parse import quote

class handler(BaseHTTPRequestHandler):
    
    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        
        parsed_path = urlparse(self.path)
        query = parse_qs(parsed_path.query)
        
        # Handle CORS
        if self.headers.get('Access-Control-Request-Method'):
            self.do_OPTIONS()
            return
        
        # Health check
        if parsed_path.path == '/api/convert' and not query:
            self.send_json(200, {
                'status': 'ok',
                'message': 'YTMP3 API Proxy is running',
                'usage': {
                    'get': 'GET /api/convert?url=YOUTUBE_URL',
                    'post': 'POST /api/convert with JSON body {"url": "youtube_url"}'
                }
            })
            return
        
        # Handle GET dengan parameter url
        url = query.get('url', [None])[0]
        if not url:
            self.send_json(400, {'error': 'Parameter url diperlukan'})
            return
        
        self.handle_conversion_proxy(url)
    
    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path != '/api/convert':
            self.send_error(404, 'Not found')
            return
        
        # Handle CORS
        if self.headers.get('Access-Control-Request-Method'):
            self.do_OPTIONS()
            return
        
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            data = json.loads(post_data.decode('utf-8'))
            youtube_url = data.get('url')
            
            if not youtube_url:
                self.send_json(400, {'error': 'URL diperlukan'})
                return
            
            self.handle_conversion_proxy(youtube_url)
            
        except json.JSONDecodeError:
            self.send_json(400, {'error': 'Invalid JSON'})
        except Exception as e:
            self.send_json(500, {'error': f'Internal error: {str(e)}'})
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def handle_conversion_proxy(self, youtube_url):
        """Proxy ke API publik yang udah ada"""
        
        # Daftar API publik yang bisa dipake (urut berdasarkan prioritas)
        apis = [
            self.convert_via_akuari,
            self.convert_via_lolhuman,
            self.convert_via_yt1s,
            self.convert_via_ssyoutube
        ]
        
        for api_func in apis:
            try:
                result = api_func(youtube_url)
                if result and result.get('success'):
                    self.send_json(200, result)
                    return
            except Exception as e:
                print(f"API {api_func.__name__} gagal: {e}")
                continue
        
        # Kalo semua gagal, kasih error
        self.send_json(500, {'error': 'Semua API konverter gagal, coba lagi nanti'})
    
    def convert_via_akuari(self, url):
        """Pake API akuari.my.id"""
        try:
            api_url = f"https://api.akuari.my.id/downloader/ytmp3?link={quote(url)}"
            response = requests.get(api_url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('result') and data['result'].get('link'):
                    return {
                        'success': True,
                        'title': data['result'].get('title', 'Unknown'),
                        'file_name': f"{data['result'].get('title', 'audio')}.mp3",
                        'download_url': data['result']['link'],
                        'file_size': data['result'].get('size', 5000000),
                        'format': 'mp3',
                        'source': 'akuari'
                    }
        except:
            pass
        return None
    
    def convert_via_lolhuman(self, url):
        """Pake API lolhuman.xyz"""
        try:
            # Pake API key gratis yang available
            api_key = "ayakavip"  # API key publik
            api_url = f"https://api.lolhuman.xyz/api/ytaudio2?apikey={api_key}&url={quote(url)}"
            response = requests.get(api_url, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 200 and data.get('result'):
                    result = data['result']
                    if result.get('link_download'):
                        return {
                            'success': True,
                            'title': result.get('title', 'Unknown'),
                            'file_name': f"{result.get('title', 'audio')}.mp3",
                            'download_url': result['link_download'],
                            'file_size': result.get('size', 5000000),
                            'format': 'mp3',
                            'source': 'lolhuman'
                        }
        except:
            pass
        return None
    
    def convert_via_yt1s(self, url):
        """Pake API yt1s.io (coba pake endpoint mereka)"""
        try:
            # Extract video ID
            video_id = self.extract_video_id(url)
            if not video_id:
                return None
            
            # Pake endpoint yt1s
            api_url = "https://yt1s.io/api/ajaxSearch"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            data = {
                'q': url,
                'vt': 'home'
            }
            
            response = requests.post(api_url, data=data, headers=headers, timeout=15)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('status') == 'ok':
                    # Dapetin link MP3
                    links = result.get('links', {}).get('mp3', {})
                    if links:
                        # Ambil kualitas terbaik
                        kualitas = list(links.keys())[-1]
                        link_data = links[kualitas]
                        return {
                            'success': True,
                            'title': result.get('title', 'Unknown'),
                            'file_name': f"{result.get('title', 'audio')}.mp3",
                            'download_url': link_data.get('link'),
                            'file_size': link_data.get('size', 5000000),
                            'format': 'mp3',
                            'source': 'yt1s'
                        }
        except:
            pass
        return None
    
    def convert_via_ssyoutube(self, url):
        """Pake API ssyoutube.com"""
        try:
            # Convert ke short URL kalo perlu
            api_url = f"https://www.ssyoutube.com/api/convert?url={quote(url)}&format=mp3"
            response = requests.get(api_url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0'
            })
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success') and data.get('url'):
                    return {
                        'success': True,
                        'title': data.get('title', 'Unknown'),
                        'file_name': f"{data.get('title', 'audio')}.mp3",
                        'download_url': data['url'],
                        'file_size': data.get('size', 5000000),
                        'format': 'mp3',
                        'source': 'ssyoutube'
                    }
        except:
            pass
        return None
    
    def extract_video_id(self, url):
        """Extract YouTube video ID dari berbagai format URL"""
        patterns = [
            r'(?:youtube\.com\/watch\?v=)([\w-]+)',
            r'(?:youtu\.be\/)([\w-]+)',
            r'(?:youtube\.com\/embed\/)([\w-]+)',
            r'(?:youtube\.com\/v\/)([\w-]+)'
        ]
        
        import re
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
