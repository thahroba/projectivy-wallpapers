# Projectivy video wallpapers

The feed is published at:
https://raw.githubusercontent.com/thahroba/projectivy-wallpapers/main/wallpapers.json

## Build a large Pixabay collection

1. Sign in to Pixabay and open https://pixabay.com/api/docs/ to find your API key.
2. In this repository, open **Settings → Secrets and variables → Actions → New repository secret**.
3. Set the name to `PIXABAY_API_KEY`, paste the key into the value field, then save it. Do not put the key into a file or share it in chat.
4. Open **Actions → Fill wallpaper library from Pixabay → Run workflow**.

The workflow searches broad topics from the requested themes, keeps landscape clips that have a 4K or Full HD URL, and caps the list at 1000 entries for Projectivy Overflight. It caches Pixabay API responses for 24 hours and never downloads the video files.

Pixabay contributes stock footage (nature, animals, cities, cars, sports, technology, and similar topics). It will not provide licensed game, film, anime, or celebrity scenes; those need separate direct-video sources.
