from http.server import BaseHTTPRequestHandler
import json
import subprocess
import tempfile
import os
import uuid
import urllib.parse
import requests
import sys
import site

class handler(BaseHTTPRequestHandler):
    
    def setup_ytdlp(self):
        """Pastikan yt-dlp tersedia"""
        try:
            # Cek apakah yt-dlp ada di PATH
            subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
            return 'yt-dlp'
        except:
            # Kalo gak ada, cari di site-packages
            site_packages = site.getsitepackages()[0]
            ytdlp_path = os.path.join(site_packages, 'yt_dlp', '__main__.py')
            if os.path.exists(ytdlp_path):
                return ['python', '-m', 'yt_dlp']
            else:
                # Fallback: install manual
                subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'yt-dlp'], 
                             capture_output=True)
                return 'yt-dlp'
    
    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        
        parsed_path = urlparse(self.path)
        query = parse_qs(parsed_path.query)
        
        # Handle CORS preflight
        if self.headers.get('Access-Control-Request-Method'):
            self.do_OPTIONS()
            return
        
        # Health check
        if parsed_path.path == '/api/convert' and not query:
            self.send_json(200, {
                'status': 'ok',
                'message': 'YTMP3 API is running',
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
        
        self.handle_conversion(url)
    
    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path != '/api/convert':
            self.send_error(404, 'Not found')
            return
        
        # Handle CORS preflight
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
            
            self.handle_conversion(youtube_url)
            
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
    
    def handle_conversion(self, youtube_url):
        try:
            # Validasi URL
            if not ('youtube.com' in youtube_url or 'youtu.be' in youtube_url):
                self.send_json(400, {'error': 'Bukan URL YouTube yang valid'})
                return
            
            # Setup yt-dlp
            ytdlp_cmd = self.setup_ytdlp()
            
            # Buat temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                file_id = str(uuid.uuid4())[:8]
                
                # Pake subprocess dengan yt-dlp
                if isinstance(ytdlp_cmd, list):
                    cmd = ytdlp_cmd + [
                        '-f', 'bestaudio/best',
                        '--extract-audio',
                        '--audio-format', 'mp3',
                        '--audio-quality', '0',
                        '-o', os.path.join(temp_dir, f'%(title)s_{file_id}.%(ext)s'),
                        '--no-playlist',
                        '--quiet',
                        youtube_url
                    ]
                else:
                    cmd = [
                        ytdlp_cmd,
                        '-f', 'bestaudio/best',
                        '--extract-audio',
                        '--audio-format', 'mp3',
                        '--audio-quality', '0',
                        '-o', os.path.join(temp_dir, f'%(title)s_{file_id}.%(ext)s'),
                        '--no-playlist',
                        '--quiet',
                        youtube_url
                    ]
                
                # Jalankan dengan timeout lebih panjang
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=180  # 3 menit
                )
                
                if result.returncode != 0:
                    error_msg = result.stderr[:200] if result.stderr else 'Unknown error'
                    self.send_json(500, {'error': f'Gagal konversi: {error_msg}'})
                    return
                
                # Cari file MP3
                mp3_files = [f for f in os.listdir(temp_dir) if f.endswith('.mp3')]
                if not mp3_files:
                    self.send_json(500, {'error': 'File MP3 tidak ditemukan'})
                    return
                
                mp3_file = mp3_files[0]
                file_path = os.path.join(temp_dir, mp3_file)
                
                # Baca file
                with open(file_path, 'rb') as f:
                    file_content = f.read()
                
                # Upload ke hosting
                file_url = self.upload_to_temp_host(file_content, mp3_file)
                
                if not file_url:
                    self.send_json(500, {'error': 'Gagal upload file'})
                    return
                
                # Title dari filename
                title = mp3_file.replace(f'_{file_id}.mp3', '').replace('_', ' ')
                
                self.send_json(200, {
                    'success': True,
                    'title': title,
                    'file_name': mp3_file,
                    'download_url': file_url,
                    'file_size': len(file_content),
                    'format': 'mp3'
                })
                
        except subprocess.TimeoutExpired:
            self.send_json(504, {'error': 'Waktu proses habis (video terlalu panjang)'})
        except Exception as e:
            self.send_json(500, {'error': f'Internal error: {str(e)}'})
    
    def upload_to_temp_host(self, file_content, filename):
        """Upload file ke temporary hosting"""
        
        # Coba upload ke tmp.ninja dulu
        try:
            files = {
                'file': (filename, file_content, 'audio/mpeg')
            }
            
            response = requests.post(
                'https://tmp.ninja/upload.php',
                files=files,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('file'):
                    return f"https://tmp.ninja/{data['file']}"
        except:
            pass
        
        # Fallback ke file.io
        try:
            files = {
                'file': (filename, file_content, 'audio/mpeg')
            }
            
            response = requests.post(
                'https://file.io',
                files=files,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success') and data.get('link'):
                    return data['link']
        except:
            pass
        
        return None
    
    def send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
