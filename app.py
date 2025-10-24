from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import subprocess
import os
from dotenv import load_dotenv
from flask_httpauth import HTTPBasicAuth
from flask_cors import CORS

load_dotenv()
app = Flask(__name__, static_folder='build/static', static_url_path='/static')
CORS(app, resources={r"/*": {"origins": "*"}})  # Permite CORS para fetch desde frontend

queue = []  # Cola simple

auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username, password):
    return username == os.getenv('AUTH_USERNAME') and password == os.getenv('AUTH_PASSWORD')

sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=os.getenv('SPOTIFY_CLIENT_ID'), client_secret=os.getenv('SPOTIFY_CLIENT_SECRET')))

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('q')
    results = sp.search(q=query, limit=20, type='track')['tracks']['items']
    processed = [{
        'id': track['id'],
        'name': track['name'],
        'artists': [{'name': a['name']} for a in track['artists']],
        'album': {'images': [{'url': track['album']['images'][0]['url']}] if track['album']['images'] else []}
    } for track in results]
    return jsonify(processed)

@app.route('/stream', methods=['GET'])
@auth.login_required
def get_stream():
    track = request.args.get('track')
    cmd = ['yt-dlp', '--quiet', '--format', 'bestaudio', '--get-url', f'ytsearch:{track}']
    url = subprocess.check_output(cmd).decode().strip()
    return jsonify({'stream_url': url})

@app.route('/download', methods=['GET'])  # Cambia a GET para simplicidad en fetch; usa query param
@auth.login_required
def download():
    track = request.args.get('track')
    filename = f"{track.replace(' ', '_')}.mp3"  # Nombre limpio para attachment

    def generate():
        cmd = ['yt-dlp', '--quiet', '--format', 'bestaudio[ext=m4a]', '--no-playlist', f'ytsearch:{track}']
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=-1)
        for chunk in iter(lambda: proc.stdout.read(4096), b''):
            yield chunk
        proc.wait()

    return Response(stream_with_context(generate()), headers={
        'Content-Type': 'audio/mpeg',
        'Content-Disposition': f'attachment; filename="{filename}"'
    })

@app.route('/queue', methods=['POST', 'GET'])
@auth.login_required
def manage_queue():
    if request.method == 'POST':
        queue.append(request.json['track'])
        return jsonify({'queue': queue})
    return jsonify({'queue': queue})

# Rutas para frontend estático
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.root_path, 'build', path)):
        return send_from_directory('build', path)
    else:
        return send_from_directory('build', 'index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
