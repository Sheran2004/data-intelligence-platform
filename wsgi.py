"""WSGI entry-point for production servers (gunicorn, uwsgi, etc.).

Usage:
    gunicorn -w 2 -k gthread --threads 4 -b 0.0.0.0:$PORT wsgi:app
"""

from app import app

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)