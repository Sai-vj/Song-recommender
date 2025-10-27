import os
import datetime
import logging
from flask import Flask, render_template, request, redirect, url_for, session
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# -------------------------
# Load environment
# -------------------------
load_dotenv()

# -------------------------
# App + logging
# -------------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback_key")

# Configure logger to show info + traceback
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

# -------------------------
# Database setup
# -------------------------
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///history.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


class SearchHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mood = db.Column(db.String(50))
    playlist_name = db.Column(db.String(200))
    playlist_url = db.Column(db.String(300))
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)


with app.app_context():
    db.create_all()

# -------------------------
# Spotify Auth setup
# -------------------------
SPOTIFY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:5000/callback")

sp_oauth = SpotifyOAuth(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET,
    redirect_uri=SPOTIFY_REDIRECT_URI,
    scope="user-library-read user-top-read playlist-read-private",
)

# client credentials manager for public searches (dev fallback)
client_creds_manager = SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID,
    client_secret=SPOTIFY_CLIENT_SECRET
)

# -------------------------
# Helpers
# -------------------------
def ensure_token():
    """
    Return token_info dict if available and refreshed.
    If no valid token available, return None.
    """
    token_info = session.get("token_info")
    if not token_info:
        return None

    # sp_oauth.is_token_expired expects the same token_info structure returned by get_access_token
    try:
        if sp_oauth.is_token_expired(token_info):
            app.logger.info("User token expired — attempting refresh")
            try:
                refreshed = sp_oauth.refresh_access_token(token_info.get("refresh_token"))
                session["token_info"] = refreshed
                token_info = refreshed
                app.logger.info("Token refreshed ok")
            except Exception as e:
                app.logger.exception("Failed to refresh token: %s", e)
                return None
    except Exception:
        # if anything unexpected with token_info shape, drop it
        app.logger.exception("Error checking token expiry — clearing session token")
        session.pop("token_info", None)
        return None

    return token_info


# inject current year (used in base.html)
@app.context_processor
def inject_now():
    return {'now': datetime.datetime.utcnow}


# -------------------------
# Routes
# -------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/login")
def login():
    # redirect user to spotify authorization
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    error = request.args.get("error")
    if error:
        app.logger.error("Authorization error from Spotify: %s", error)
        return f"Authorization failed: {error}", 400
    if not code:
        return "No code provided", 400

    try:
        # exchange code for token_info
        token_info = sp_oauth.get_access_token(code)
    except Exception as e:
        app.logger.exception("Token exchange failed: %s", e)
        return f"Token exchange failed: {e}", 500

    # store token in session (keep minimal)
    session["token_info"] = token_info
    app.logger.info("Got token_info (keys): %s", list(token_info.keys()) if isinstance(token_info, dict) else None)
    return redirect(url_for("recommend"))


@app.route("/recommend", methods=["GET", "POST"])
def recommend():
    # attempt to use user token; if absent/invalid, fallback to client creds (public search)
    token_info = ensure_token()
    if token_info:
        sp = Spotify(auth=token_info["access_token"])
        using_fallback = False
    else:
        app.logger.info("No valid user token — using Client Credentials fallback for public search")
        sp = Spotify(client_credentials_manager=client_creds_manager)
        using_fallback = True

    playlists = []
    if request.method == "POST":
        mood = (request.form.get("mood", "") or "").strip().lower()
        if not mood or len(mood) > 100:
            return "Invalid mood input", 400

        try:
            results = sp.search(q=mood, type="playlist", limit=5)
            app.logger.info("Spotify search OK (query=%s)", mood)
        except Exception as e:
            app.logger.exception("Spotify search failed")
            # include error text but not full stack in client response
            return f"Spotify search failed: {e}", 502

        # safe extraction of playlist items
        playlists_container = results.get("playlists") if isinstance(results, dict) else None
        items = playlists_container.get("items") if isinstance(playlists_container, dict) else None

        if not items:
            app.logger.info("No playlist items in Spotify response for mood=%s", mood)
            return render_template("result.html", mood=mood.capitalize(), playlists=[])

        entries = []
        for p in items:
            if not p or not isinstance(p, dict):
                continue

            name = p.get("name") or "Unknown playlist"
            url = None
            ext = p.get("external_urls")
            if isinstance(ext, dict):
                url = ext.get("spotify")

            playlists.append({"name": name, "url": url})

            # Save history row — we can save even if URL is None, but you may choose to skip
            entries.append(SearchHistory(mood=mood, playlist_name=name, playlist_url=url))

        # commit once
        if entries:
            try:
                db.session.add_all(entries)
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.exception("DB commit failed")

        # If using fallback, you might want to show notice in UI — templates can read `using_fallback`
        return render_template("result.html", mood=mood.capitalize(), playlists=playlists, using_fallback=using_fallback)

    return render_template("recommend.html")


@app.route("/history")
def history():
    records = SearchHistory.query.order_by(SearchHistory.timestamp.desc()).all()
    return render_template("history.html", records=records)


# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    # For dev use only; in production use a proper WSGI server
    app.run(debug=True)
