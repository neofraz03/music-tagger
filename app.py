import os
import re
import shutil
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
import musicbrainzngs
from mutagen.easyid3 import EasyID3
from mutagen.id3 import error, ID3NoHeaderError
from mutagen.mp3 import MP3
import mutagen

app = Flask(__name__)
musicbrainzngs.set_useragent("AudioTaggerDockerApp", "1.0", "contact@example.com")

SUPPORTED_EXTENSIONS = ('.mp3', '.flac', '.m4a', '.wav', '.ogg')

def parse_year_from_path(file_path):
    parent_dir = os.path.basename(os.path.dirname(file_path))
    match = re.search(r'\((\d{4})\)', parent_dir)
    if match:
        return match.group(1)
    return None

def check_file_already_organized(file_path):
    has_metadata = False
    try:
        audio_tags = EasyID3(file_path)
        if audio_tags.get('artist') and audio_tags.get('album') and audio_tags.get('title'):
            has_metadata = True
    except (error, Exception):
        has_metadata = False

    structure_pattern = re.compile(r'.*[/\\][^/\\]+[/\\]\(\d{4}\)\s+[^/\\]+[/\\]\d{2}\s*-\s*[^/\\]+$', re.IGNORECASE)
    has_correct_structure = bool(structure_pattern.match(file_path))

    return has_metadata and has_correct_structure

def fetch_studio_track_and_metadata(file_path, artist, title):
    track_number = "1"
    official_title = title
    official_album = None
    official_year = None

    try:
        enforced_year = parse_year_from_path(file_path)

        clean_query_title = re.sub(r'[\(\[].*?(official|music video|lyrics|remastered|version|hq|hd|from|search|mix|remix|4k|video).*?[\)\]]', '', title, flags=re.IGNORECASE)
        clean_query_title = re.sub(r'\b(official music video|official video|lyrics|hq|hd|remastered|4k)\b', '', clean_query_title, flags=re.IGNORECASE)
        clean_query_title = clean_query_title.strip(' -()[]')
        if not clean_query_title:
            clean_query_title = title

        result = musicbrainzngs.search_recordings(artist=artist, recording=clean_query_title, limit=25)
        recordings = result.get('recording-list', [])
        
        if not recordings and artist != "Unknown Artist":
            fallback_result = musicbrainzngs.search_recordings(query=clean_query_title, limit=15)
            recordings = fallback_result.get('recording-list', [])

        best_release = None
        valid_candidates = []
        
        for rec in recordings:
            if not isinstance(rec, dict):
                continue
            releases = rec.get('release-list', [])
            for rel in releases:
                if not isinstance(rel, dict):
                    continue
                rel_title = rel.get('title', '')
                rel_title_lower = rel_title.lower()
                release_date = rel.get('date', '')
                
                release_group = rel.get('release-group', {})
                if not release_date and isinstance(release_group, dict):
                    release_date = release_group.get('first-release-date', '')

                release_year = release_date[:4] if len(release_date) >= 4 else '9999'
                
                artist_credit = rel.get('artist-credit', [])
                is_various = False
                for ac in artist_credit:
                    if isinstance(ac, dict):
                        ac_artist = ac.get('artist', {})
                        if isinstance(ac_artist, dict) and 'various' in ac_artist.get('name', '').lower():
                            is_various = True

                primary_type = release_group.get('type', '').lower() if isinstance(release_group, dict) else ''
                secondary_type_list = release_group.get('secondary-type-list', []) if isinstance(release_group, dict) else []
                secondary_types = [st.lower() for st in secondary_type_list if isinstance(st, str)]
                
                skip_secondary = ['live', 'dj-mix', 'spokenword', 'interview', 'bootleg', 'remix']
                if any(st in secondary_types for st in skip_secondary):
                    continue

                score = 0
                
                if primary_type == 'album' and not is_various:
                    score += 400
                elif primary_type == 'single' or primary_type == 'ep':
                    score += 300  
                elif 'soundtrack' in secondary_types or 'soundtrack' in rel_title_lower:
                    score += 200

                compilation_keywords = [
                    'greatest hits', 'best of', 'anthology', 'collection', 'remix', 
                    'anniversary', 'deluxe', 'huge hits', 'demo', 'demos', 'early demos', 
                    'platinum collection', 'essential', 'hits', '90\'s', '90s', 
                    'bridesmaid', 'party', 'now that is what', 'radio', 'eurochart', 'charts',
                    'musik', 'bildung', 'captured', 'glorious', 'school', 'curriculum'
                ]
                if any(ck in rel_title_lower for ck in compilation_keywords):
                    score -= 1000  

                if is_various and 'soundtrack' not in secondary_types:
                    score -= 800

                if enforced_year and release_year == enforced_year:
                    score += 100

                valid_candidates.append((score, int(release_year) if release_year.isdigit() else 9999, rec, rel))

        if valid_candidates:
            valid_candidates.sort(key=lambda x: (-x[0], x[1]))
            _, _, rec, rel = valid_candidates[0]
            best_release = (rec, rel)

        if best_release:
            rec, rel = best_release
            official_title = rec.get('title', title)
            official_album = rel.get('title')
            
            release_id = rel.get('id')
            if release_id:
                try:
                    rel_data = musicbrainzngs.get_release_by_id(release_id, includes=['recordings', 'release-groups', 'media'])
                    release_node = rel_data.get('release', {})
                    if isinstance(release_node, dict):
                        date_str = release_node.get('date', '')
                        rg_node = release_node.get('release-group', {})
                        if not date_str and isinstance(rg_node, dict):
                            date_str = rg_node.get('first-release-date', '')
                        
                        if len(date_str) >= 4 and date_str[:4].isdigit():
                            official_year = date_str[:4]

                        media_list = release_node.get('medium-list', [])
                        for medium in media_list:
                            if not isinstance(medium, dict):
                                continue
                            for track in medium.get('track-list', []):
                                if not isinstance(track, dict):
                                    continue
                                recording_node = track.get('recording', {})
                                if isinstance(recording_node, dict) and recording_node.get('id') == rec.get('id'):
                                    pos = track.get('position')
                                    if pos:
                                        track_number = str(pos)
                                        break
                            if track_number != "1":
                                break
                except Exception as ex:
                    print(f"Release ID lookup fallback error: {ex}")

            if not official_year:
                date_str = rel.get('date', '')
                rg_node = rel.get('release-group', {})
                if not date_str and isinstance(rg_node, dict):
                    date_str = rg_node.get('first-release-date', '')
                if len(date_str) >= 4 and date_str[:4].isdigit():
                    official_year = date_str[:4]

        if not official_album or not isinstance(official_album, str) or official_album.lower() in ("unknown album", "none", ""):
            official_album = official_title

    except Exception as e:
        print(f"MusicBrainz query error: {e}")

    return track_number, official_title, official_album, official_year

def parse_metadata(file_path, base_dir):
    path = Path(file_path)
    
    existing_artist = None
    existing_album = None
    existing_title = None
    existing_year = None
    existing_track = None
    
    try:
        audio_file = mutagen.File(file_path, easy=True)
        if audio_file is not None:
            if 'artist' in audio_file and audio_file['artist']:
                existing_artist = audio_file['artist'][0]
            if 'album' in audio_file and audio_file['album']:
                existing_album = audio_file['album'][0]
            if 'title' in audio_file and audio_file['title']:
                existing_title = audio_file['title'][0]
            if 'date' in audio_file and audio_file['date']:
                date_val = audio_file['date'][0]
                m = re.search(r'\b(19\d{2}|20\d{2})\b', date_val)
                if m:
                    existing_year = m.group(1)
            if 'tracknumber' in audio_file and audio_file['tracknumber']:
                t_val = audio_file['tracknumber'][0].split('/')[0]
                if t_val.isdigit():
                    existing_track = t_val.lstrip('0') or "0"
    except Exception:
        pass

    has_valid_embedded_album = (
        existing_artist and existing_album and existing_title 
        and existing_artist != "Unknown Artist" 
        and existing_album.lower() != existing_title.lower()
        and existing_album.lower() not in ("unknown album", "single")
    )

    if has_valid_embedded_album:
        safe_artist = "".join(c for c in existing_artist if c not in '<>:"/\\|?*').strip()
        safe_album = "".join(c for c in existing_album if c not in '<>:"/\\|?*').strip()
        safe_title = "".join(c for c in existing_title if c not in '<>:"/\\|?*').strip()
        safe_track = (existing_track or "1").zfill(2)

        path_parts_list = list(path.parts)
        if "music" in path_parts_list:
            music_idx = path_parts_list.index("music")
            root_music_dir = Path(*path_parts_list[:music_idx+1])
        else:
            root_music_dir = Path(base_dir).parents[0] if len(Path(base_dir).parts) > 1 else Path(base_dir)

        formatted_year = f"({existing_year}) " if existing_year else ""
        new_album_folder = f"{formatted_year}{safe_album}".strip()
        proposed_rel_path = os.path.join(safe_artist, new_album_folder, f"{safe_track} - {safe_title}{path.suffix}")
        proposed_full_path = os.path.join(str(root_music_dir), proposed_rel_path)

        original_normalized = os.path.normpath(str(path))
        proposed_normalized = os.path.normpath(str(proposed_full_path))
        is_path_correct = (original_normalized == proposed_normalized)

        return {
            "original_path": str(path),
            "proposed_path": str(proposed_full_path),
            "artist": safe_artist,
            "album": safe_album,
            "year": existing_year or "",
            "tracknumber": existing_track or "1",
            "title": existing_title,
            "is_path_correct": is_path_correct
        }, None

    filename = path.name
    abs_parts = path.parts

    artist = "Unknown Artist"
    album_folder = ""
    year = None
    album = "Unknown Album"
    track_number = "1"

    name_wo_ext = os.path.splitext(filename)[0]
    title = name_wo_ext

    is_flat_file = (len(abs_parts) <= 3 and abs_parts[-2].lower() in ("music", "", "/"))

    if not is_flat_file and len(abs_parts) >= 3:
        album_folder = abs_parts[-2]
        artist = abs_parts[-3]
        
        if artist.lower() in ("music", "", "/"):
            artist = "Unknown Artist"
    else:
        if " - " in name_wo_ext:
            parts_split = name_wo_ext.split(" - ", 1)
            artist = parts_split[0].strip()
            title = parts_split[1].strip()

    if artist in ("Unknown Artist", "music", "", "/") or re.search(r'\b(19\d{2}|20\d{2})\b', artist):
        for p in reversed(abs_parts[:-1]):
            if p.lower() not in ("music", "/", "") and not re.search(r'\b(19\d{2}|20\d{2})\b', p):
                artist = p
                break

    track_match = re.match(r'^(\d+)[^\w]*(.*)$', name_wo_ext)
    if track_match:
        track_number = track_match.group(1).lstrip('0') or "0"
        title = track_match.group(2).strip()
    elif " - " in name_wo_ext and not is_flat_file:
        split_name = name_wo_ext.split(" - ", 1)
        if split_name[0].strip().isdigit():
            track_number = split_name[0].strip().lstrip('0') or "0"
            title = split_name[1].strip()

    if album_folder and not is_flat_file:
        year_match = re.search(r'(?:[\(\[]\s*|\b)(19\d{2}|20\d{2})(?:\s*[\)\]]|\b)', album_folder)
        if year_match:
            year = year_match.group(1)
        
        clean_album = re.sub(r'[\(\[]?\s*\b(19\d{2}|20\d{2})\b\s*[\)\]]?', '', album_folder).strip()
        clean_album = re.sub(r'\s{2,}', ' ', clean_album).strip(' -')
        if clean_album:
            album = clean_album

    title = re.sub(r'[\(\[].*?(official music video|official video|lyrics|remastered|hq|hd|from|search|4k|video).*?[\)\]]', '', title, flags=re.IGNORECASE)
    title = re.sub(r'\s{2,}', ' ', title).strip(' -')
    if not title:
        title = name_wo_ext

    if is_flat_file or artist == "Unknown Artist" or album == "Unknown Album" or not year or album.lower() == title.lower() or album.lower() == "unknown album":
        if artist != "Unknown Artist" and artist != "/" and title:
            mb_track, mb_title, mb_album, mb_year = fetch_studio_track_and_metadata(file_path, artist, title)
            if (not track_number or track_number == "1") and mb_track:
                track_number = mb_track
            if not year and mb_year:
                year = mb_year
            if (album == "Unknown Album" or not album or album.lower() == title.lower() or album.lower() == "unknown album") and mb_album:
                clean_mb_album = re.sub(r'[\(\[]?\s*\b(19\d{2}|20\d{2})\b\s*[\)\]]?', '', mb_album).strip()
                if clean_mb_album:
                    album = clean_mb_album
            if mb_title and len(mb_title) > 1:
                title = mb_title

    if not album or album.lower() in ("unknown album", "none", ""):
        album = title

    formatted_year = f"({year}) " if year else ""
    safe_artist = "".join(c for c in artist if c not in '<>:"/\\|?*').strip()
    safe_album = "".join(c for c in album if c not in '<>:"/\\|?*').strip()
    safe_title = "".join(c for c in title if c not in '<>:"/\\|?*').strip()
    safe_track = track_number.zfill(2)

    if not safe_artist:
        safe_artist = "Unknown Artist"
    if not safe_album:
        safe_album = "Unknown Album"

    path_parts_list = list(path.parts)
    if "music" in path_parts_list:
        music_idx = path_parts_list.index("music")
        root_music_dir = Path(*path_parts_list[:music_idx+1])
    else:
        root_music_dir = Path(base_dir).parents[0] if len(Path(base_dir).parts) > 1 else Path(base_dir)

    new_album_folder = f"{formatted_year}{safe_album}".strip()
    proposed_rel_path = os.path.join(safe_artist, new_album_folder, f"{safe_track} - {safe_title}{path.suffix}")
    proposed_full_path = os.path.join(str(root_music_dir), proposed_rel_path)

    original_normalized = os.path.normpath(str(path))
    proposed_normalized = os.path.normpath(str(proposed_full_path))
    is_path_correct = (original_normalized == proposed_normalized)

    return {
        "original_path": str(path),
        "proposed_path": str(proposed_full_path),
        "artist": safe_artist,
        "album": safe_album,
        "year": year or "",
        "tracknumber": track_number,
        "title": title,
        "is_path_correct": is_path_correct
    }, None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/music-tagger_logo.png')
def serve_logo():
    return send_from_directory('.', 'music-tagger_logo.png')

@app.route('/scan', methods=['POST'])
def scan_directory():
    data = request.json
    music_dir = data.get('directory', '/music')
    
    if not os.path.exists(music_dir):
        return jsonify({"items": [], "failed": [], "logs": ["Directory not found!"]})

    items = []
    failed = []
    logs = []

    for root, dirs, files in os.walk(music_dir):
        for file in files:
            if file.lower().endswith(SUPPORTED_EXTENSIONS):
                file_path = os.path.join(root, file)
                
                if check_file_already_organized(file_path):
                    logs.append(f"Bypassing already organized file: {file_path}")
                    continue

                logs.append(f"Scanning file: {file_path}")
                
                result, error_reason = parse_metadata(file_path, music_dir)
                if result:
                    items.append(result)
                    logs.append(f"-> Successfully parsed: {result['artist']} / {result['title']}")
                else:
                    failed.append({"path": file_path, "reason": error_reason})
                    logs.append(f"-> Failed parsing: {file_path} ({error_reason})")

    return jsonify({"items": items, "failed": failed, "logs": logs})

@app.route('/browse', methods=['POST'])
def browse_directory():
    data = request.get_json() or {}
    target_dir = data.get('directory', '/music')
    
    safe_base = os.path.abspath('/music')
    target_abs = os.path.abspath(target_dir)
    if not target_abs.startswith(safe_base):
        return jsonify({'error': 'Unauthorized path access'}), 403
        
    subdirs = []
    parent_dir = os.path.dirname(target_abs)
    
    try:
        with os.scandir(target_abs) as entries:
            for entry in entries:
                if entry.is_dir() and not entry.name.startswith('.'):
                    subdirs.append({
                        'name': entry.name,
                        'path': entry.path
                    })
        subdirs = sorted(subdirs, key=lambda x: x['name'].lower())
        
        return jsonify({
            'current': target_abs,
            'parent': parent_dir if target_abs != safe_base else None,
            'subdirectories': subdirs
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/apply-metadata', methods=['POST'])
def apply_metadata():
    return jsonify({"success": True})

@app.route('/apply-restructure', methods=['POST'])
def apply_restructure():
    data = request.json
    items = data.get('items', [])
    success_count = 0

    for item in items:
        if item.get('restruct_action') == 'deny' or item.get('approve') is False:
            continue

        orig_path = item['original_path']
        prop_path = item['proposed_path']
        is_path_correct = item.get('is_path_correct', False)

        if not os.path.exists(orig_path) or os.path.getsize(orig_path) == 0:
            print(f"Skipping non-existent or empty path: {orig_path}")
            continue

        try:
            # Safely instantiate and guard against header corruption / pointer faults
            try:
                audio = MP3(orig_path, ID3=EasyID3)
            except ID3NoHeaderError:
                audio = MP3(orig_path)
                audio.add_tags()
                audio = MP3(orig_path, ID3=EasyID3)
            except Exception as init_err:
                print(f"Skipping malformed audio frame header on {orig_path}: {init_err}")
                continue

            try:
                audio.add_tags()
            except error:
                pass

            audio['title'] = [item['title']]
            audio['artist'] = [item['artist']]
            audio['album'] = [item['album']]
            if item['year']:
                audio['date'] = [str(item['year'])]
            audio['tracknumber'] = [str(item['tracknumber'])]
            
            # Save safely enforcing boundaries to avoid invalid memory reference pointer drops
            audio.save(orig_path, v1=2)

            if not is_path_correct and orig_path != prop_path:
                os.makedirs(os.path.dirname(prop_path), exist_ok=True)
                shutil.move(orig_path, prop_path)

            success_count += 1
        except Exception as e:
            print(f"Error processing {orig_path}: {e}")

    return jsonify({"message": f"Successfully processed {success_count} item(s) with conditional restructuring and tagging!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)