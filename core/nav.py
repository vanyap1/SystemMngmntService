"""Top bar navigation registry: the work sections of the panel, each with one or more pages.

A section with several pages shows them as sub-tabs while one of its pages is open (e.g. Tests → Run / Logs);
otherwise the section links to its first visible page. Add a page to an existing section, or a new Section.
Global tools (Monitor, Devices, Services, Settings, power menu) are not sections — see templates/base.html.
"""
from collections import namedtuple

NavItem = namedtuple('NavItem', 'endpoint label icon public')
Section = namedtuple('Section', 'id label icon items')

SECTIONS = [
    Section('main', 'Main', 'fa-solid fa-house', [
        NavItem('dashboard.index', 'Main', 'fa-solid fa-house', True),
    ]),
    Section('code', 'Code', 'fa-solid fa-code', [
        NavItem('editor.editor', 'Code Editor', 'fa-solid fa-code', False),
    ]),
    Section('docs', 'Docs', 'fa-solid fa-book', [
        NavItem('help.help_page', 'Docs', 'fa-solid fa-book', False),
    ]),
    Section('tests', 'Tests', 'fa-solid fa-vial', [
        NavItem('tests.tests', 'Run', 'fa-solid fa-play', False),
        NavItem('logs.logs', 'Logs', 'fa-solid fa-file-lines', False),
    ]),
]

SETTINGS = NavItem('settings.settings', 'Settings', 'fa-solid fa-gear', False)


def sections(logged_in, current_endpoint):
    """Sections visible to this visitor: [{id, label, icon, endpoint, active, pages: [{endpoint, label, icon, active}]}]."""
    out = []
    for s in SECTIONS:
        items = [{'endpoint': i.endpoint, 'label': i.label, 'icon': i.icon, 'active': i.endpoint == current_endpoint}
                 for i in s.items if logged_in or i.public]
        if items:
            out.append({'id': s.id, 'label': s.label, 'icon': s.icon, 'endpoint': items[0]['endpoint'],
                        'active': any(i['active'] for i in items), 'pages': items})
    return out


def endpoints():
    """Every page endpoint in the navigation (for tests)."""
    return [i.endpoint for s in SECTIONS for i in s.items] + [SETTINGS.endpoint]
