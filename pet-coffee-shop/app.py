# Brewskers main application
# Entry point only. All logic lives under backend and frontend folders.
# Run with: python app.py

from backend.auth import app
from backend.security import env_flag

# Importing routes registers every page and API endpoint on the app.
import backend.routes  # noqa: F401,E402


if __name__ == "__main__":
    # Never run with debug mode on a real server. It exposes a remote console.
    app.run(debug=env_flag("FLASK_DEBUG"))
