from flask import Flask, render_template, request, Response, send_file, redirect, url_for
from flask_httpauth import HTTPBasicAuth
import yt_dlp
import os
import io

app = Flask(__name__)
auth = HTTPBasicAuth()

# Configuración de credenciales desde variables de entorno
USERS = {
    os.environ.get('SPOTSPOF_USERNAME', 'admin'): os.environ.get('SPOTSPOF_PASSWORD', 'password')
}

@auth.verify_password
def verify_password(username, password):
    if username in USERS and USERS[username] == password:
        return username

# Configuración básica de yt-dlp
YDL_OPTS_SEARCH = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'auto',
    'extract_flat': 'auto',
    'force_generic_extractor': True,
}

YDL_OPTS_DOWNLOAD_STREAM = { # Opciones para descargar a un buffer para streaming directo
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'logger': app.logger # Para ver logs de yt-dlp si debug=True
}

@app.route('/')
@auth.login_required
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
@auth.login_required
def search():
    query = request.form['query']
    results = []
    try:
        # Búsqueda general con yt-dlp, que soporta YouTube, Bandcamp y muchos otros
        # Limitamos a 10 resultados para no sobrecargar
        search_query = f"{query} | ytsearch10" # Primero busca en YouTube
        with yt_dlp.YoutubeDL(YDL_OPTS_SEARCH) as ydl:
            yt_info = ydl.extract_info(search_query, download=False)
            if yt_info and 'entries' in yt_info:
                for entry in yt_info['entries']:
                    if entry: # Asegurarse de que el entry no sea None
                        # Determinar la fuente de manera más robusta
                        source = 'Unknown'
                        if 'youtube.com' in entry.get('webpage_url', ''):
                            source = 'YouTube'
                        elif 'bandcamp.com' in entry.get('webpage_url', ''):
                            source = 'Bandcamp'
                        
                        results.append({
                            'source': source,
                            'id': entry.get('id'),
                            'title': entry.get('title'),
                            'url': entry.get('webpage_url'),
                            'duration': entry.get('duration_string'),
                            'thumbnail': entry.get('thumbnail')
                        })
        
        # Opcional: una búsqueda más específica para Bandcamp si se desea.
        # yt-dlp ya lo maneja en la búsqueda general, pero si quieres priorizarlo
        # o tener resultados separados, podrías añadir algo como:
        # bc_search_query = f"{query} | bandcampsearch10"
        # bc_info = ydl.extract_info(bc_search_query, download=False)
        # ... y procesar de manera similar, asegurando que no haya duplicados.

    except Exception as e:
        app.logger.error(f"Error searching: {e}")
        return f"An error occurred during search: {e}", 500

    return render_template('index.html', query=query, results=results)

@app.route('/stream_html/<source>/<track_id>')
@auth.login_required
def stream_html(source, track_id):
    # La URL completa es necesaria para yt-dlp
    track_url = ""
    if source == 'YouTube':
        track_url = f"https://www.youtube.com/watch?v={track_id}"
    elif source == 'Bandcamp':
        # Para Bandcamp, el 'id' a menudo ya es la URL, o necesita ser reconstruida.
        # Aquí asumimos que track_id es suficiente para yt-dlp si es un Bandcamp URL directo
        # Si 'id' es solo un identificador, necesitarías la URL completa del resultado de la búsqueda.
        # Para simplificar, si la búsqueda devuelve una URL, la usaremos directamente.
        # O, si Bandcamp es la fuente, y el id es un slug, quizás buscar por el slug.
        # Por ahora, para Bandcamp, es mejor tener la URL completa en el ID o en el resultado.
        # Como yt-dlp ya maneja urls, la forma más sencilla es que el `track_id` sea la url para Bandcamp
        # o que la busquemos de nuevo usando el `id` original de la búsqueda.
        # Por simplicidad, asumiremos que track_id puede ser tratado como un identificador para yt-dlp.
        track_url = track_id # Puede ser una URL completa o un ID que yt-dlp pueda resolver
    
    if not track_url:
        return "Source or track_id not sufficient for streaming.", 400

    try:
        ydl_opts_stream = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'logger': app.logger # Para ver logs de yt-dlp si debug=True
        }
        with yt_dlp.YoutubeDL(ydl_opts_stream) as ydl:
            # Si track_id es una URL completa (como para Bandcamp a veces), yt-dlp lo acepta directamente.
            # Si es solo un ID de YouTube, la construcción de la URL está bien.
            info = ydl.extract_info(track_url, download=False)
            if 'url' in info:
                # Flask redirigirá al navegador a esta URL de streaming
                return redirect(info['url'])
            else:
                return "No se pudo encontrar la URL de streaming directo para el reproductor HTML5.", 404
    except Exception as e:
        app.logger.error(f"Error streaming HTML: {e}")
        return f"Ocurrió un error al intentar obtener la URL de streaming: {e}", 500

@app.route('/stream_direct/<source>/<track_id>')
@auth.login_required
def stream_direct(source, track_id):
    track_url = ""
    if source == 'YouTube':
        track_url = f"https://www.youtube.com/watch?v={track_id}"
    elif source == 'Bandcamp':
        track_url = track_id # Asumimos URL completa o ID que yt-dlp puede resolver.
    
    if not track_url:
        return "Source or track_id not sufficient for direct streaming.", 400

    def generate_audio():
        # yt-dlp va a descargar el audio y nosotros lo vamos a transmitir en chunks
        try:
            with yt_dlp.YoutubeDL(YDL_OPTS_DOWNLOAD_STREAM) as ydl:
                # Download con hooks para transmitir a medida que se recibe
                # 'outtmpl': '-' significa escribir a stdout, que en un hook se puede interceptar.
                # Sin embargo, para streaming de un audio que está siendo procesado (ej. a mp3),
                # es mejor que yt-dlp lo haga y luego nosotros enviemos el buffer.
                # Para un streaming REALMENTE directo (sin guardado temporal),
                # yt-dlp puede dar la URL directa (como en stream_html) o hacer streaming a un pipe.
                # Aquí, simularemos streaming directo usando un buffer en memoria.
                
                # Una forma más robusta sería obtener la URL directa y usar requests.stream=True
                # o que yt-dlp realmente pipe el audio.
                # Para este ejemplo, haremos que yt-dlp descargue el archivo entero en memoria
                # y luego lo serviremos como un stream.
                
                # Si queremos el "streaming real" donde servimos mientras se descarga,
                # la implementación es más compleja y requeriría una tubería o
                # un generador que consuma los fragmentos de descarga de yt-dlp.

                # Para simplificar, obtendremos la URL de streaming si es posible y redirigiremos,
                # o si no, usaremos una descarga a buffer y lo serviremos.
                # Dado que stream_html ya obtiene la URL directa, este botón
                # puede ser para casos donde queremos que el servidor actúe como proxy.

                # Si el formato es 'bestaudio' yt-dlp puede darnos una URL directa, que es lo mejor
                # o bien descargar y luego servir.
                
                info = ydl.extract_info(track_url, download=False)
                if 'url' in info:
                    # Si yt-dlp nos da una URL directa, la devolvemos.
                    # El navegador hará el streaming directamente.
                    return redirect(info['url'])
                else:
                    # Si no hay URL directa, descargamos a un buffer y lo servimos como stream.
                    # Esto consume más memoria y recursos del servidor.
                    # Para mp3, podríamos intentar forzar el postprocesado a mp3 si es necesario.
                    
                    # Usaremos un método más sencillo: descargar a un buffer temporal.
                    # Nota: esto puede consumir mucha memoria si los archivos son grandes.
                    buffer_output = io.BytesIO()
                    
                    ydl_opts_buffer = YDL_OPTS_DOWNLOAD_STREAM.copy()
                    ydl_opts_buffer['outtmpl'] = '-' # Escribir a stdout
                    ydl_opts_buffer['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
                    ydl_opts_buffer['quiet'] = True
                    ydl_opts_buffer['no_warnings'] = True
                    ydl_opts_buffer['logtostderr'] = False
                    
                    with yt_dlp.YoutubeDL(ydl_opts_buffer) as ydl_buffer:
                        ydl_buffer.download([track_url]) # Esto descarga y procesa a mp3
                        # Necesitamos capturar la salida de stdout de yt-dlp que va al buffer.
                        # Para eso, yt-dlp con outtmpl='-' normalmente lo envía a stdout.
                        # Para capturarlo en un buffer de Python, es más complejo que solo usar download().
                        # Una estrategia común es reconfigurar sys.stdout temporalmente o usar Popen.

                        # Para el propósito de este ejemplo, la forma más sencilla es usar send_file desde un archivo temporal.
                        # Si el objetivo es *realmente* streaming sin guardar, es un patrón de diseño más avanzado.

                        # Para simplificar, si stream_html no funciona, este botón puede intentar descargar y luego servir.
                        # Pero dado que stream_html ya redirige a la URL directa, este caso es para cuando el servidor actúa de proxy.

                        # Deshabilitamos esta ruta para evitar errores complejos de manejo de buffer/stdout
                        # con yt-dlp, que es difícil de hacer de forma robusta con la API directa de Python.
                        # En su lugar, redirigiremos a `stream_html` si el objetivo es streaming directo del contenido.
                        pass

            # Si llegamos aquí, significa que la lógica de streaming directo como proxy no es trivial
            # con las APIs actuales sin guardar a disco.
            # Por lo tanto, si stream_html no funcionó o si queremos forzar el servidor como proxy,
            # usaremos un enfoque de descarga a archivo temporal y luego servimos ese archivo
            # para simular el "direct stream" desde el servidor.
            
            # Vamos a intentar un enfoque que usa el generador para leer fragmentos del archivo
            # después de que yt-dlp lo descargue a un archivo temporal.

            temp_file_path = f"/tmp/{track_id}.mp3" # Nombre temporal
            # Asegurarse de que el directorio /tmp existe (generalmente sí en Docker)

            ydl_opts_download_temp = YDL_OPTS_DOWNLOAD_STREAM.copy()
            ydl_opts_download_temp['outtmpl'] = temp_file_path
            ydl_opts_download_temp['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            ydl_opts_download_temp['quiet'] = True
            ydl_opts_download_temp['no_warnings'] = True

            with yt_dlp.YoutubeDL(ydl_opts_download_temp) as ydl_temp:
                info = ydl_temp.extract_info(track_url, download=True)
            
            # Ahora, servir el archivo temporal en chunks
            def generate_file_chunks():
                with open(temp_file_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192) # Leer en chunks de 8KB
                        if not chunk:
                            break
                        yield chunk
                os.remove(temp_file_path) # Limpiar el archivo temporal
            
            return Response(generate_file_chunks(), mimetype='audio/mpeg')

        except Exception as e:
            app.logger.error(f"Error direct streaming: {e}")
            return f"Ocurrió un error al intentar el streaming directo desde el servidor: {e}", 500

@app.route('/download/<source>/<track_id>')
@auth.login_required
def download(source, track_id):
    track_url = ""
    if source == 'YouTube':
        track_url = f"https://www.youtube.com/watch?v={track_id}"
    elif source == 'Bandcamp':
        track_url = track_id # Asumimos URL completa o ID que yt-dlp puede resolver.
    
    if not track_url:
        return "Source or track_id not sufficient for download.", 400

    try:
        # Descarga a un archivo temporal en disco
        # Usamos el id de la pista para el nombre del archivo temporal para evitar colisiones simples
        temp_file = f"/tmp/{track_id}.mp3" 

        ydl_opts_download_temp = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': temp_file, # Guarda en el archivo temporal
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'logger': app.logger
        }

        with yt_dlp.YoutubeDL(ydl_opts_download_temp) as ydl_temp:
            info = ydl_temp.extract_info(track_url, download=True)
        
        # Obtener el nombre de archivo final que yt-dlp usó
        # info['requested_downloads'][0]['filepath'] sería más preciso si se procesa
        # Pero para un mp3 simple, el outtmpl + ext es a menudo suficiente
        final_filename = os.path.basename(temp_file) # Usamos el nombre que especificamos

        # Envía el archivo al cliente
        return send_file(temp_file, as_attachment=True, download_name=final_filename, mimetype='audio/mpeg')
    except Exception as e:
        app.logger.error(f"Error downloading: {e}")
        return f"Ocurrió un error al intentar descargar: {e}", 500
    finally:
        # Limpiar el archivo temporal después de enviarlo
        if 'temp_file' in locals() and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError as e:
                app.logger.warning(f"Error removing temporary file {temp_file}: {e}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
