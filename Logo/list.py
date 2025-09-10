import requests
import json

# Konfiguration für Ihr Repository
OWNER = "ALXRITR"
REPO = "Korte-Hoffmann"
BASE_PATH = "Logo"

# Liste, um alle finalen Datei-URLs zu speichern
all_file_urls = []

def get_repo_contents(path=""):
    """
    Ruft rekursiv die Inhalte eines GitHub-Repository-Pfades ab.
    """
    api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{path}"
    headers = {'Accept': 'application/vnd.github.v3+json'}
    response = requests.get(api_url, headers=headers)
    
    if response.status_code == 200:
        contents = response.json()
        for item in contents:
            if item['type'] == 'file':
                # Wenn es eine Datei ist, füge die download_url zur Liste hinzu
                if item.get('download_url'):
                    all_file_urls.append(item['download_url'])
            elif item['type'] == 'dir':
                # Wenn es ein Ordner ist, rufe die Funktion für diesen Ordner erneut auf
                get_repo_contents(item['path'])
    else:
        print(f"Fehler beim Abrufen von {api_url}: {response.status_code} - {response.text}")

# Starte den Prozess im Haupt-Logo-Ordner
print("Rufe Dateilinks vom GitHub Repo ab...")
get_repo_contents(BASE_PATH)

# Gib alle gefundenen URLs aus
print("\n--- Alle korrekten Download-URLs ---")
for url in sorted(all_file_urls):
    print(url)

print(f"\nInsgesamt {len(all_file_urls)} Dateien gefunden.")