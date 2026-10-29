"""Top bar navigation registry. Add an entry here to show a new page in the top bar."""
from collections import namedtuple

NavItem = namedtuple('NavItem', 'endpoint label icon public')

NAV_ITEMS = [
    NavItem('dashboard.index', 'Main', 'fa-solid fa-house', True),
    NavItem('tests.tests', 'Tests', 'fa-solid fa-vial', False),
    NavItem('logs.logs', 'Logs', 'fa-solid fa-file-lines', False),
    NavItem('editor.editor', 'Code Editor', 'fa-solid fa-code', False),
    NavItem('settings.settings', 'Settings', 'fa-solid fa-gear', False),
]


def visible_items(logged_in, current_endpoint):
    return [item for item in NAV_ITEMS
            if item.endpoint != current_endpoint and (logged_in or item.public)]
