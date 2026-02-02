import requests
import os
import json
import time
import re

TOKEN = ''
PEER_IDS = []
API_VERSION = '5.131'
SAVE_DIR = 'sferum_dump'

COOKIES = {
    "httoken": "",
    "prcl": "",
    "remixsid": "",
    "remixstid": "",
    "remixstlid": ""
}

session = requests.Session()
session.cookies.update(COOKIES)
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
})

def vk_api(method, params):
    params.update({'access_token': TOKEN, 'v': API_VERSION})
    try:
        resp = session.post(f"https://api.vk.com/method/{method}", data=params).json()
        if 'error' in resp:
            print(f"[!] Ошибка API {method}: {resp['error']['error_msg']}")
            return None
        return resp.get('response')
    except Exception as e:
        print(f"[!] Сбой сети при вызове {method}: {e}")
        return None

def save_file(url, path):
    if os.path.exists(path): return True
    try:
        r = session.get(url, stream=True, timeout=10)
        if r.status_code == 200:
            with open(path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
    except Exception as e:
        print(f"[!] Ошибка скачивания: {e}")
    return False

def get_user_data(user_ids):
    if not user_ids: return {}
    print(f"[*] Получение данных об участниках ({len(user_ids)} чел.)...")

    users = vk_api("users.get", {"user_ids": ",".join(map(str, user_ids)), "fields": "photo_id,photo_200"})
    if not users: return {}

    user_map = {u['id']: u for u in users}
    photo_ids = [u['photo_id'] for u in users if u.get('photo_id')]
    photo_to_user = {u['photo_id']: u['id'] for u in users if u.get('photo_id')}

    if photo_ids:
        photos = vk_api("photos.getById", {"photos": ",".join(photo_ids), "extended": 1})
        if photos:
            for p in photos:
                uid = photo_to_user.get(f"{p['owner_id']}_{p['id']}")
                if uid:
                    best_url = p.get('orig_photo', {}).get('url')
                    if not best_url:
                        best_url = sorted(p['sizes'], key=lambda x: x.get('width', 0))[-1]['url']
                    user_map[uid]['high_res_url'] = best_url
    return user_map

def generate_html(history, user_cache, chat_dir):
    style = """
    body { font-family: -apple-system, system-ui, sans-serif; background: #ebedf0; padding: 20px; }
    .chat { max-width: 700px; margin: auto; background: white; border-radius: 12px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
    .msg { display: flex; margin-bottom: 18px; }
    .av { width: 48px; height: 48px; border-radius: 50%; margin-right: 12px; flex-shrink: 0; background-size: cover; background-position: center; border: 1px solid #eee; }
    .info { flex: 1; }
    .name { font-weight: 600; color: #2a5885; font-size: 14px; margin-bottom: 2px; }
    .time { color: #939393; font-size: 11px; margin-left: 8px; font-weight: normal; }
    .txt { font-size: 15px; line-height: 1.4; white-space: pre-wrap; color: #222; }
    .att-box { margin-top: 8px; }
    .att-img { max-width: 100%; border-radius: 8px; border: 1px solid #ddd; display: block; margin-bottom: 5px; }
    .file-link { display: inline-block; padding: 8px 12px; background: #f0f2f5; border-radius: 6px; text-decoration: none; color: #2a5885; font-size: 13px; border: 1px solid #e1e3e6; }
    """

    msg_html = ""
    history.sort(key=lambda x: x['date'])

    for m in history:
        if not m['text'].strip() and not m['attachments']: continue

        uid = m['from_id']
        u = user_cache.get(uid, {"first_name": "ID", "last_name": str(uid)})
        name = f"{u.get('first_name', '')} {u.get('last_name', '')}"
        av_path = u.get('local_path', '')
        time_str = time.strftime('%d.%m.%y %H:%M:%S', time.localtime(m['date']))

        att_html = ""
        for a in m['attachments']:
            rel_a = os.path.relpath(a, chat_dir)
            ext = os.path.splitext(a)[1].lower()
            if ext in ['.jpg','.png','.jpeg','.webp', '.gif']:
                att_html += f'<div class="att-box"><a href="{rel_a}" target="_blank"><img src="{rel_a}" class="att-img"></a></div>'
            elif ext in ['.mp4', '.webm', '.mov']:
                att_html += f'<div class="att-box"><video src="{rel_a}" controls class="att-img"></video></div>'
            elif ext in ['.mp3']:
                att_html += f'<div class="att-box"><audio src="{rel_a}" controls class="att-img"></audio></div>'
            else:
                att_html += f'<div class="att-box"><a href="{rel_a}" class="file-link">📎 {os.path.basename(a)}</a></div>'

        msg_html += f"""
        <div class="msg">
            <div class="av" style="background-image: url('{av_path}')"></div>
            <div class="info">
                <div class="name">{name}<span class="time">{time_str}</span></div>
                <div class="txt">{m['text']}</div>
                {att_html}
            </div>
        </div>
        """

    full_html = f"<html><head><meta charset='utf-8'><style>{style}</style></head><body><div class='chat'>{msg_html}</div></body></html>"
    with open(os.path.join(chat_dir, 'chat.html'), 'w', encoding='utf-8') as f:
        f.write(full_html)

def process_chat(peer_id):
    print(f"\n[*] Обработка чата {peer_id}")
    chat_dir = os.path.join(SAVE_DIR, str(peer_id))
    attach_dir = os.path.join(chat_dir, 'attachments')
    av_dir = os.path.join(chat_dir, 'avatars')
    os.makedirs(attach_dir, exist_ok=True)
    os.makedirs(av_dir, exist_ok=True)

    all_messages = []
    offset = 0
    uids = set()

    while True:
        data = vk_api('messages.getHistory', {'peer_id': peer_id, 'offset': offset, 'count': 200})
        if not data or not data['items']: break

        for msg in data['items']:
            uids.add(msg['from_id'])
            msg_data = {
                'date': msg['date'],
                'from_id': msg['from_id'],
                'text': msg['text'],
                'attachments': []
            }

            if 'attachments' in msg:
                for att in msg['attachments']:
                    att_type = att['type']
                    url, title = "", ""

                    if att_type == 'photo':
                        url = att['photo']['sizes'][-1]['url']
                    elif att_type == 'doc':
                        url = att['doc']['url']
                        title = att['doc']['title']
                    elif att_type == 'video':
                        v = att['video']
                        files = v.get('files', {})
                        if 'src' in files:
                            url = files['src']
                        else:
                            mp4_keys = sorted([k for k in files.keys() if k.startswith('mp4_')], key=lambda x: int(x.split('_')[1]) if '_' in x else 0)
                            if mp4_keys:
                                url = files[mp4_keys[-1]]
                            else:
                                url = v.get('player', v.get('direct_url', ''))
                        title = v.get('title', '')
                    elif att_type == 'audio_message':
                        url = att['audio_message']['link_mp3']
                    elif att_type == 'sticker':
                        url = att['sticker']['images'][-1]['url']
                        title = f"sticker_{att['sticker']['sticker_id']}.png"
                    elif att_type == 'graffiti':
                        url = att['graffiti']['url']
                        title = f"graffiti_{att['graffiti']['id']}.png"

                    if url:
                        url_path = url.split('?')[0]
                        url_ext = os.path.splitext(url_path)[1].lower()

                        clean_title = re.sub(r'[\\/*?:"<>|]', "", title) if title else ""

                        if clean_title:
                            if not os.path.splitext(clean_title)[1]:
                                filename = f"{msg['date']}_{clean_title}{url_ext}"
                            else:
                                filename = f"{msg['date']}_{clean_title}"
                        else:
                            raw_name = url_path.split('/')[-1]
                            filename = f"{msg['date']}_{att_type}_{raw_name}"

                        if '.' not in filename:
                            if att_type == 'photo': filename += ".jpg"
                            elif att_type == 'video': filename += ".mp4"
                            elif att_type == 'audio_message': filename += ".mp3"
                            elif not url_ext: filename += ".dat"

                        filepath = os.path.join(attach_dir, filename)
                        if not os.path.exists(filepath):
                            print(f"[+] Скачивание {att_type}: {filename}")
                            save_file(url, filepath)
                        msg_data['attachments'].append(filepath)

            all_messages.append(msg_data)
        offset += 200
        print(f"Прогресс: {len(all_messages)} сообщений...")
        time.sleep(0.2)

    with open(os.path.join(chat_dir, 'history.json'), 'w', encoding='utf-8') as f:
        json.dump(all_messages, f, ensure_ascii=False, indent=4)

    user_ids = [u for u in uids if u > 0]
    user_cache = get_user_data(user_ids)

    print("[*] Сохранение изображений профилей...")
    for uid, info in user_cache.items():
        img_url = info.get('high_res_url') or info.get('photo_200')
        if img_url:
            av_filename = f"user_{uid}.jpg"
            av_filepath = os.path.join(av_dir, av_filename)
            if save_file(img_url, av_filepath):
                user_cache[uid]['local_path'] = f"avatars/{av_filename}"
            else:
                user_cache[uid]['local_path'] = img_url

    print("[*] Генерация HTML...")
    generate_html(all_messages, user_cache, chat_dir)
    print(f"[+] Готово! Чат {peer_id} сохранен в JSON и HTML.")

if __name__ == "__main__":
    if not os.path.exists(SAVE_DIR): os.makedirs(SAVE_DIR)
    for target in PEER_IDS:
        process_chat(target)
    print("\n[!] Все задачи выполнены.")