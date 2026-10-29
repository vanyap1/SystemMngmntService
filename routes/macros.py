"""Command macros (top bar buttons in the code editor), stored in macros.json."""
import json
import os

from flask import Blueprint, jsonify, request

from core import config
from core.auth import login_required

bp = Blueprint('macros', __name__)

MACRO_FIELDS = ('name', 'command', 'tooltip', 'icon', 'color')

DEFAULT_MACROS = [
    {"name": "Git Status", "command": "git status", "tooltip": "Check Git repository status",
     "icon": "fa-brands fa-git-alt", "color": "#162638"},
    {"name": "Disk Free", "command": "df -h", "tooltip": "Free disk space",
     "icon": "fa-solid fa-hard-drive", "color": "#162638"},
    {"name": "Top Mem", "command": "ps aux --sort=-%mem | head -n 15",
     "tooltip": "Top memory consuming processes", "icon": "fa-solid fa-microchip",
     "color": "#162638"},
    {"name": "Uptime", "command": "uptime", "tooltip": "System uptime",
     "icon": "fa-solid fa-clock", "color": "#162638"},
]


def load_macros():
    """Load macros from macros.json, creating the file with defaults if missing."""
    if not os.path.exists(config.MACROS_PATH):
        try:
            save_macros(DEFAULT_MACROS)
        except Exception:
            pass
        return DEFAULT_MACROS
    try:
        with open(config.MACROS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_macros(macros):
    with open(config.MACROS_PATH, 'w', encoding='utf-8') as f:
        json.dump(macros, f, indent=4, ensure_ascii=False)


@bp.route('/api/macros', methods=['GET'])
@login_required
def api_get_macros():
    return jsonify(load_macros())


@bp.route('/api/macros', methods=['POST'])
@login_required
def api_save_macros():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'No data provided'}), 400
    raw_list = data if isinstance(data, list) else data.get('macros', [])
    if not isinstance(raw_list, list):
        return jsonify({'error': 'Macros must be a list'}), 400
    clean = [{k: str(item.get(k, '')).strip() for k in MACRO_FIELDS}
             for item in raw_list if isinstance(item, dict)]
    try:
        save_macros(clean)
        return jsonify({'success': True, 'macros': clean})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
